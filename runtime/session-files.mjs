// Filesystem work for session import/deletion runs in a separate Node process.
// Imported history is data: this module never loads extensions or runs tools.
import fs from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import { createInterface } from 'node:readline';
import { Transform } from 'node:stream';
import { resolve, relative, dirname, basename, join, sep } from 'node:path';
import { randomUUID, createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';

const hash = (text, size = 64) => createHash('sha256').update(text).digest('hex').slice(0, size);
const object = value => value && typeof value === 'object' && !Array.isArray(value);
const text = value => typeof value === 'string' && value.length > 0;
const kinds = new Set(['message', 'model_change', 'thinking_level_change', 'usage', 'compaction',
  'branch_summary', 'custom', 'custom_message', 'context_edit', 'label', 'session_info']);
const roles = new Set(['user', 'assistant', 'toolResult', 'system', 'bashExecution', 'custom', 'hookMessage']);
function content(value) {
  return typeof value === 'string' || Array.isArray(value) && value.every(block => object(block) &&
    (block.type === 'text' ? typeof block.text === 'string' :
      block.type === 'thinking' ? typeof block.thinking === 'string' :
      block.type === 'image' ? text(block.data) && text(block.mimeType) :
      block.type === 'toolCall' ? text(block.id) && text(block.name) && object(block.arguments) : false));
}

export async function importSession({ source, sessionDir, cwd }) {
  source = resolve(source); sessionDir = await fs.realpath(sessionDir);
  const before = await fs.stat(source);
  if (!before.isFile() || !source.toLowerCase().endsWith('.jsonl')) throw new Error('请选择 Pi JSONL 会话文件');
  if (!before.size || before.size > 1024 * 1024 * 1024) throw new Error('会话文件为空或超过 1 GiB');
  const id = randomUUID(), now = new Date().toISOString();
  const target = join(sessionDir, now.replace(/[:.]/g, '-') + '_' + id + '.jsonl');
  const temporary = join(sessionDir, '.import-' + id + '.part');
  const output = await fs.open(temporary, 'wx', 0o600);
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let tailLength = 0;
  const utf8 = new Transform({ transform(chunk, _, done) {
    try {
      const decoded = decoder.decode(chunk, { stream: true });
      let start = 0, end;
      while ((end = decoded.indexOf('\n', start)) !== -1) {
        if (tailLength + end - start > 64 * 1024 * 1024) throw new Error('单条记录过大');
        tailLength = 0; start = end + 1;
      }
      tailLength += decoded.length - start;
      if (tailLength > 64 * 1024 * 1024) throw new Error('单条记录过大');
      done(null, decoded);
    } catch (error) { done(error); }
  }, flush(done) { try { done(null, decoder.decode()); } catch (error) { done(error); } } });
  const input = createReadStream(source); input.on('error', error => utf8.destroy(error)); input.pipe(utf8);
  const lines = createInterface({ input: utf8, crlfDelay: Infinity });
  const ids = new Set(), positions = [];
  let line = 0, entries = 0, version, header, previous = null, title = '', firstUser = '';
  const invalid = reason => { throw new Error('第 ' + line + ' 行：' + reason); };
  try {
    for await (let raw of lines) {
      line++;
      if (!raw.trim()) continue;
      if (raw.length > 64 * 1024 * 1024) invalid('单条记录过大');
      let entry;
      try { entry = JSON.parse(raw); } catch { invalid('JSON 不完整或格式错误'); }
      if (!object(entry)) invalid('会话记录必须是对象');
      if (!header) {
        if (entry.type !== 'session' || !text(entry.id) || !text(entry.cwd) || !text(entry.timestamp) || !Number.isFinite(Date.parse(entry.timestamp)))
          invalid('缺少合法的 Pi 会话头');
        version = entry.version ?? 1;
        if (![1, 2, 3].includes(version)) invalid('不支持此会话版本');
        header = { ...entry, id, version: 3, cwd: resolve(cwd), timestamp: now };
        // A copied session has no filesystem authority over its source/parent.
        delete header.parentSession;
        await output.write(JSON.stringify(header) + '\n'); positions.push(null); continue;
      }
      if (!kinds.has(entry.type)) invalid('未知的会话记录类型');
      if (!text(entry.timestamp) || !Number.isFinite(Date.parse(entry.timestamp))) invalid('记录时间无效');
      if (version === 1) {
        entry.id = randomUUID().slice(0, 8); entry.parentId = previous;
        if (entry.type === 'compaction' && Number.isInteger(entry.firstKeptEntryIndex)) {
          entry.firstKeptEntryId = positions[entry.firstKeptEntryIndex]; delete entry.firstKeptEntryIndex;
        }
      }
      if (!text(entry.id) || entry.id.length > 160 || ids.has(entry.id)) invalid('记录 ID 无效或重复');
      if (entry.parentId !== null && (!text(entry.parentId) || !ids.has(entry.parentId))) invalid('会话分支缺少父记录');
      const reference = key => entry[key] === entry.id || text(entry[key]) && ids.has(entry[key]);
      if (entry.type === 'message') {
        const message = entry.message;
        if (!object(message) || !roles.has(message.role)) invalid('消息角色无效');
        if (message.role === 'bashExecution') {
          if (typeof message.command !== 'string' || typeof message.output !== 'string') invalid('终端消息不完整');
        } else if (!content(message.content)) invalid('消息内容不完整');
        if (message.role === 'toolResult' && (!text(message.toolCallId) || !text(message.toolName))) invalid('工具结果不完整');
        if (message.role === 'hookMessage') message.role = 'custom';
        if (!firstUser && message.role === 'user') firstUser = typeof message.content === 'string' ? message.content : message.content.filter(b => b.type === 'text').map(b => b.text).join(' ');
      } else if (entry.type === 'compaction' && (!reference('firstKeptEntryId') || typeof entry.summary !== 'string')) invalid('压缩记录缺少原始上下文');
      else if (entry.type === 'branch_summary' && (!reference('fromId') || typeof entry.summary !== 'string')) invalid('分支摘要引用不存在');
      else if (['label', 'context_edit'].includes(entry.type) && !ids.has(entry.targetId)) invalid('记录引用不存在');
      else if (['custom', 'custom_message'].includes(entry.type) && !text(entry.customType)) invalid('扩展记录类型缺失');
      if (entry.type === 'context_edit' && entry.replacement !== null && (!object(entry.replacement) || !content(entry.replacement.content))) invalid('上下文编辑内容不完整');
      if (entry.type === 'usage' && (!text(entry.kind) || !text(entry.provider) || !text(entry.model) || !object(entry.usage))) invalid('用量记录不完整');
      if (entry.type === 'label' && entry.label !== undefined && typeof entry.label !== 'string') invalid('标签内容无效');
      if (entry.type === 'session_info' && entry.name !== undefined && typeof entry.name !== 'string') invalid('会话名称无效');
      if (entry.type === 'custom_message' && !content(entry.content)) invalid('扩展消息内容不完整');
      if (entry.type === 'model_change' && (!text(entry.provider) || !text(entry.modelId))) invalid('模型记录不完整');
      if (entry.type === 'thinking_level_change' && !text(entry.thinkingLevel)) invalid('思考强度记录不完整');
      if (entry.type === 'session_info' && typeof entry.name === 'string') title = entry.name;
      ids.add(entry.id); positions.push(entry.id); previous = entry.id; entries++;
      await output.write(JSON.stringify(entry) + '\n');
    }
    if (!header || !entries) throw new Error('会话没有可导入的记录');
    const after = await fs.stat(source);
    if (before.ino !== after.ino || before.size !== after.size || before.mtimeMs !== after.mtimeMs) throw new Error('导入期间源文件发生变化，请重试');
    await output.sync(); await output.close();
    await fs.rename(temporary, target);
    return { id, title: (title || firstUser.slice(0, 28) || '新会话'), file: target, workspace: cwd };
  } catch (error) {
    await output.close().catch(() => {}); await fs.rm(temporary, { force: true }); throw error;
  } finally { lines.close(); input.destroy(); utf8.destroy(); }
}

// Check every ancestor. A symlink/junction inside an owned tree must never
// redirect deletion to another directory. Removing the leaf link is safe.
async function owned(path, root) {
  path = resolve(path); root = resolve(root);
  const rel = relative(root, path);
  if (!rel || rel === '..' || rel.startsWith('..' + sep) || resolve(root, rel) !== path) throw new Error('只能清理应用托管的会话数据');
  let at = root;
  const parts = rel.split(sep);
  for (let i = 0; i < parts.length - 1; i++) {
    at = join(at, parts[i]);
    try { if ((await fs.lstat(at)).isSymbolicLink()) throw new Error('会话目录包含链接，无法安全删除'); }
    catch (error) { if (error.code === 'ENOENT') return path; throw error; }
  }
  return path;
}
async function removeTree(path) {
  // Node's rm removes leaf symlinks rather than traversing them.
  await fs.rm(path, { recursive: true, force: true, maxRetries: 2, retryDelay: 100 });
}

export async function deleteSession({ profile, session }) {
  profile = await fs.realpath(profile);
  let file = session.file ? resolve(session.file) : '';
  if (session.backend === 'dsh' && !file) {
    if (!/^dsh-[a-zA-Z0-9]+$/.test(session.id)) throw new Error('会话编号无效');
    file = join(profile, 'dsh/transcripts', session.id + '.json');
  }
  const root = join(profile, session.backend === 'dsh' ? 'dsh/transcripts' : 'pi/sessions');
  const related = [];
  if (file) {
    await owned(join(root, 'boundary'), profile);
    await owned(file, root);
    if (!file.toLowerCase().endsWith(session.backend === 'dsh' ? '.json' : '.jsonl')) throw new Error('会话文件类型无效');
    related.push(file);
    if (session.backend !== 'dsh') {
      const tree = file.slice(0, -6);
      async function children(directory) {
        let rows; try { rows = await fs.readdir(directory, { withFileTypes: true }); } catch (error) { if (error.code === 'ENOENT') return; throw error; }
        for (const row of rows) {
          const path = join(directory, row.name);
          if (row.isDirectory()) await children(path);
          else if (row.isFile() && row.name.endsWith('.jsonl')) related.push(path);
        }
      }
      try { if (!(await fs.lstat(tree)).isSymbolicLink()) await children(tree); } catch (error) { if (error.code !== 'ENOENT') throw error; }
      await owned(tree, root); await owned(file + '.images', root);
      // Keep the primary transcript visible/retryable until dependent deletion succeeds.
      await removeTree(tree); await removeTree(file + '.images');
    }
    if (session.backend === 'dsh') {
      const home = !session.dshOwnConfig ? session.dshHome : session.dshSessionRoot ? dirname(session.dshSessionRoot) : '';
      if (home) {
        await owned(join(profile, 'dsh/profiles/boundary'), profile);
        await removeTree(await owned(home, join(profile, 'dsh/profiles')));
      }
    }
  }
  for (const source of related) {
    const sqlite = join(profile, 'cache/chat-index', hash(source));
    for (const suffix of ['.sqlite', '.sqlite-wal', '.sqlite-shm']) await fs.rm(await owned(sqlite + suffix, profile), { force: true });
  }
  // Search projections contain plaintext and are not part of the transcript.
  const cache = join(profile, 'cache/conversation-search-v1', hash(session.workspace || 'unassigned', 32));
  for (const key of [hash(session.id + '\0' + (file || 'live'), 32), hash(session.id + ':live\0live', 32)])
    for (const suffix of ['.txt', '.json', '.json.tmp']) await fs.rm(await owned(join(cache, key + suffix), profile), { force: true });
  if (file) await fs.rm(file, { force: true });
  return { id: session.id, files: related };
}

export async function execute(input) {
  if (input.operation === 'import') {
    if (input.profile) await owned(join(input.sessionDir, 'boundary'), await fs.realpath(input.profile));
    await fs.mkdir(input.sessionDir, { recursive: true });
    const sessions = [], errors = [];
    for (const source of input.sources) {
      try { sessions.push(await importSession({ ...input, source })); }
      catch (error) { errors.push({ name: basename(source), error: error.message }); }
    }
    return { sessions, errors };
  }
  if (input.operation === 'delete') {
    const deleted = [], errors = [];
    const sessions = [...input.sessions];
    if (input.workspace) {
      const directory = join(await fs.realpath(input.profile), 'pi/sessions');
      await owned(join(directory, 'boundary'), input.profile);
      let names = []; try { names = await fs.readdir(directory); } catch (error) { if (error.code !== 'ENOENT') throw error; }
      const canonical = async path => { const clean = await fs.realpath(path).catch(() => resolve(path)); return process.platform === 'win32' ? clean.toLowerCase() : clean; };
      const workspace = await canonical(input.workspace);
      for (const name of names.filter(name => name.endsWith('.jsonl'))) {
        const file = join(directory, name);
        if (sessions.some(s => resolve(s.file || '.') === file)) continue;
        if (!(await fs.lstat(file)).isFile()) continue;
        const handle = await fs.open(file, 'r');
        try {
          const buffer = Buffer.alloc(65536), { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
          const first = buffer.subarray(0, bytesRead).toString('utf8').split('\n')[0];
          let header; try { header = JSON.parse(first); } catch { continue; }
          if (header?.type === 'session' && text(header.cwd) && await canonical(header.cwd) === workspace)
            sessions.push({ id: header.id, file, workspace: input.workspace, title: '会话记录' });
        } finally { await handle.close(); }
      }
    }
    for (const session of sessions) {
      try { deleted.push(await deleteSession({ ...input, session })); }
      catch (error) { errors.push({ id: session.id, name: session.title, error: error.message }); }
    }
    // A legacy catalog may have multiple files carrying the same native ID.
    // Retain its sidebar entry if any one of those files could not be erased.
    const failed = new Set(errors.map(row => row.id));
    const completed = deleted.filter(row => !failed.has(row.id));
    // Old profile migrations can leave a plaintext history backup. Delete its
    // matching rows as well; never leave a hidden copy of a deleted chat.
    if (completed.length) {
      const legacy = await owned(join(input.profile, 'sessions-legacy.json'), input.profile);
      try {
        const rows = JSON.parse(await fs.readFile(legacy, 'utf8'));
        if (!Array.isArray(rows)) throw new Error('旧会话备份格式无效');
        const ids = new Set(completed.map(row => row.id)), remaining = rows.filter(row => !ids.has(row.id));
        if (remaining.length !== rows.length) {
          if (remaining.length) {
            const temporary = await owned(legacy + '.tmp', input.profile);
            await fs.writeFile(temporary, JSON.stringify(remaining), { mode: 0o600, flag: 'wx' });
            await fs.rename(temporary, legacy);
          } else await fs.rm(legacy);
        }
      } catch (error) {
        if (error.code !== 'ENOENT') {
          for (const row of completed) errors.push({ id: row.id, error: '旧会话备份未能清理：' + error.message });
          return { deleted: [], errors };
        }
      }
    }
    return { deleted: completed, errors };
  }
  throw new Error('未知的会话文件操作');
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    let raw = ''; for await (const chunk of process.stdin) raw += chunk;
    console.log(JSON.stringify({ ok: true, ...await execute(JSON.parse(raw)) }));
  } catch (error) { console.log(JSON.stringify({ ok: false, error: error.message })); process.exitCode = 1; }
}
