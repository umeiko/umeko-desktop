// Remote files use the official exec-server filesystem RPC. Large uploads use
// independent immutable chunks: reopening a lost replace handle would truncate
// completed bytes. Downloads reopen read handles at the last committed offset.
// Protocol adaptation sources at Codex tag rust-v0.172.0:
// codex-rs/exec-server/src/remote_file_system.rs and remote_file_stream.rs.
// Transfer staging and recovery orchestration below are Umeko-specific.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { remoteFileHelperCommand } from './remote-files-native.mjs';

export const REMOTE_FILE_CHUNK_BYTES = 256 * 1024;
const DEFAULT_READ_BYTES = 1024 * 1024;
const MAX_READ_BYTES = 8 * 1024 * 1024;
const positive = (value, fallback, max) => value === undefined ? fallback : Number.isInteger(value) && value > 0 && value <= max ? value : (() => { throw new Error(`Expected integer between 1 and ${max}`); })();
const nativePath = (value, windows) => {
  if (typeof value !== 'string' || value.includes('\0')) throw new Error('A valid remote path is required');
  if (!value.startsWith('file:')) return value;
  const url = new URL(value);
  if (url.protocol !== 'file:' || url.search || url.hash) throw new Error('Expected a file URI');
  const pathname = decodeURIComponent(url.pathname);
  if (windows) return url.hostname ? `\\\\${url.hostname}${pathname.replaceAll('/', '\\')}` : pathname.replace(/^\/([A-Za-z]:)/, '$1').replaceAll('/', '\\');
  if (url.hostname && url.hostname !== 'localhost') throw new Error('Remote Linux file URI must have no host');
  return pathname;
};
export function resolveRemotePath(input, info, platform, cwd) {
  const windows = platform === 'windows', paths = windows ? path.win32 : path.posix;
  let value = nativePath(input || '.', windows);
  const base = nativePath(cwd || info.cwd, windows);
  if (!paths.isAbsolute(base)) throw new Error('Remote working directory must be absolute');
  if (value === '~' || /^[~][\\/]/.test(value)) {
    if (!info.userHomeDir) throw new Error('Remote home directory is unavailable');
    value = paths.join(nativePath(info.userHomeDir, windows), value.slice(2));
  }
  if (windows && /^[A-Za-z]:[^\\/]/.test(value)) throw new Error('Drive-relative paths are unsupported; use C:\\path');
  return paths.resolve(base, value);
}
export function remotePathUri(value, platform) {
  if (platform === 'windows') {
    const normalized = value.replaceAll('\\', '/');
    if (normalized.startsWith('//')) {
      const [host, ...parts] = normalized.slice(2).split('/');
      return `file://${host}/` + parts.map(encodeURIComponent).join('/');
    }
    return 'file:///' + normalized.split('/').map((part, index) => index === 0 && /^[a-z]:$/i.test(part) ? part : encodeURIComponent(part)).join('/');
  }
  return 'file://' + value.split('/').map(encodeURIComponent).join('/');
}
const handleLost = error => error?.code === 'REMOTE_SESSION_CHANGED' || /(?:unknown|invalid|missing|not found|closed).*handle|handle.*(?:unknown|invalid|missing|not found|closed)|session.*(?:replaced|expired)/i.test(error?.message || '');
const recoverable = error => error?.code !== 'REMOTE_RECONNECT_TIMEOUT' && (error?.transport || handleLost(error));

export function createRemoteFiles(connection, dependencies = {}) {
  let commands;
  const native = dependencies.runNative || (async (task, context) => {
    commands ||= (await import('./remote-command.mjs')).createRemoteCommands(connection);
    let result = await commands.execute({ action: 'run', command: remoteFileHelperCommand(task, context.platform), cwd: context.remoteCwd, yieldMs: 1000, maxOutputBytes: 32768 }, { signal: context.signal });
    let output = result.output || '';
    while (result.status === 'running') {
      context.signal?.throwIfAborted();
      result = await commands.execute({ action: 'read', sessionId: result.sessionId, yieldMs: 1000, maxOutputBytes: 32768 }, { signal: context.signal });
      output += result.output || '';
      if (output.length > 65536) throw new Error('Remote file helper produced excessive output');
    }
    if (result.status !== 'completed' || result.exitCode !== 0) throw new Error(`Remote file helper failed: ${output.trim().slice(-4000) || result.status}`);
    const sha256 = output.trim().split(/\r?\n/).at(-1);
    if (!/^[a-f0-9]{64}$/.test(sha256)) throw new Error('Remote file helper did not return a SHA-256 digest');
    return sha256;
  });

  return { async execute(args, { signal, onUpdate, cwd = process.cwd() } = {}) {
    signal?.throwIfAborted();
    const info = await connection.waitForReady(signal);
    const platform = connection.platform || (info.platformOs === 'windows' ? 'windows' : 'linux');
    const paths = platform === 'windows' ? path.win32 : path.posix;
    const remoteCwd = resolveRemotePath(args.cwd || '.', info, platform);
    const target = resolveRemotePath(args.path || '.', info, platform, remoteCwd);
    const localCwd = path.resolve(cwd);
    const rpc = (method, params, opts = {}) => connection.rpc(method, params, { signal, ...opts });
    const uri = value => remotePathUri(value, platform);
    const context = { platform, remoteCwd, signal };
    const metadata = value => rpc('fs/getMetadata', { path: uri(value), followSymlinks: false });
    const mkdir = value => rpc('fs/createDirectory', { path: uri(value), recursive: true, followSymlinks: false }, { retry: true });
    const progress = event => { signal?.throwIfAborted(); onUpdate?.(event); };
    const readHandle = async value => {
      let handleId, handleSession, handleGeneration;
      const open = async () => {
        for (let attempt = 0; attempt < 3; attempt++) {
          handleId = randomUUID().replaceAll('-', '');
          try {
            await rpc('fs/open', { path: uri(value), handleId, mode: 'read' });
            handleSession = connection.sessionId;
            handleGeneration = connection.sessionGeneration;
            return;
          } catch (error) {
            // fs/open is not replayable at the transport layer. A lost reply to
            // a read-only open can safely be replaced with a fresh handle after
            // reconnecting, even when the old executor session has expired.
            if (attempt === 2 || !recoverable(error)) throw error;
            signal?.throwIfAborted();
            await connection.waitForReady(signal);
          }
        }
      };
      await open();
      return {
        async read(offset, len) {
          // A lost executor session invalidates server-side read handles. A fresh
          // read open is safe and resumes from the caller's confirmed offset.
          for (let attempt = 0; attempt < 3; attempt++) {
            try {
              if (connection.sessionId !== handleSession) await open();
              const result = await rpc('fs/readBlock', { handleId, offset, len }, { sessionGeneration: handleGeneration });
              return Buffer.from(result.chunk, 'base64');
            } catch (error) {
              if (attempt === 2 || error.code === 'REMOTE_RECONNECT_TIMEOUT' || signal?.aborted || !(connection.sessionId !== handleSession || recoverable(error))) throw error;
              if (error.transport) await connection.waitForReady(signal);
              await open();
            }
          }
        },
        async close() { await rpc('fs/close', { handleId }, { retry: false, sessionGeneration: handleGeneration, wait: false }).catch(() => {}); },
      };
    };
    const readBounded = async (value, limit, offset = 0) => {
      const file = await readHandle(value);
      try {
        const pieces = []; let total = 0;
        while (total < limit) {
          const piece = await file.read(offset + total, Math.min(REMOTE_FILE_CHUNK_BYTES, limit - total));
          if (!piece.length) break;
          if (piece.length > limit - total) throw new Error('Remote read exceeded requested limit');
          pieces.push(piece); total += piece.length;
        }
        return Buffer.concat(pieces, total);
      } finally { await file.close(); }
    };
    const directory = value => rpc('fs/readDirectory', { path: uri(value) });
    const childPath = (parent, name) => {
      if (!name || name === '.' || name === '..' || /[\\/\0]/.test(name)) throw new Error('Remote directory returned an unsafe filename');
      return paths.join(parent, name);
    };
    const uploadFile = async (source, destination, counters) => {
      await mkdir(paths.dirname(destination));
      const staging = destination + '.umeko-transfer-' + randomUUID();
      await mkdir(staging);
      const input = Buffer.isBuffer(source) ? null : await fs.open(source, 'r');
      const sha = createHash('sha256'); let chunks = 0, bytes = 0;
      try {
        while (true) {
          signal?.throwIfAborted();
          let piece;
          if (input) {
            const buffer = Buffer.allocUnsafe(REMOTE_FILE_CHUNK_BYTES);
            const { bytesRead } = await input.read(buffer, 0, buffer.length, bytes);
            if (!bytesRead) break;
            piece = buffer.subarray(0, bytesRead);
          } else {
            piece = source.subarray(bytes, bytes + REMOTE_FILE_CHUNK_BYTES);
            if (!piece.length) break;
          }
          sha.update(piece);
          // Exact-param replay writes just one independent chunk, so even a new
          // exec-server session cannot truncate any previously acknowledged data.
          await rpc('fs/writeFile', { path: uri(paths.join(staging, String(chunks).padStart(10, '0'))), dataBase64: piece.toString('base64'), followSymlinks: false }, { retry: true });
          bytes += piece.length; chunks++;
          progress({ action: 'upload', path: destination, bytes: counters.bytes + bytes, files: counters.files });
        }
      } finally { await input?.close(); }
      const sha256 = sha.digest('hex');
      const actual = await native({ kind: 'assemble', directory: staging, part: paths.join(staging, 'assembled.part'), target: destination, chunks, sha256 }, context);
      if (actual !== sha256) throw new Error('Transfer SHA-256 mismatch');
      counters.files++; counters.bytes += bytes;
      counters.changes.push({ path: destination, bytes, sha256 });
    };
    const downloadFile = async (source, destination, counters) => {
      const expected = await native({ kind: 'hash', path: source }, context);
      await fs.mkdir(path.dirname(destination), { recursive: true });
      const temporary = destination + '.umeko-transfer-' + randomUUID() + '.part';
      const input = await readHandle(source);
      const sha = createHash('sha256'); let bytes = 0, committed = false, output;
      try {
        output = await fs.open(temporary, 'wx', 0o600);
        while (true) {
          signal?.throwIfAborted();
          const piece = await input.read(bytes, REMOTE_FILE_CHUNK_BYTES);
          if (!piece.length) break;
          if (piece.length > REMOTE_FILE_CHUNK_BYTES) throw new Error('Remote read exceeded requested limit');
          let written = 0;
          while (written < piece.length) {
            const result = await output.write(piece, written, piece.length - written, bytes + written);
            if (!result.bytesWritten) throw new Error('Local download write made no progress');
            written += result.bytesWritten;
          }
          sha.update(piece); bytes += piece.length;
          progress({ action: 'download', path: source, localPath: destination, bytes: counters.bytes + bytes, files: counters.files });
        }
        const sha256 = sha.digest('hex');
        if (sha256 !== expected) throw new Error('Transfer SHA-256 mismatch; remote source changed or bytes were corrupted');
        await output.sync(); await output.close();
        // Node rename replaces a file atomically on both supported local OSes.
        await fs.rename(temporary, destination); committed = true;
        counters.files++; counters.bytes += bytes;
        counters.changes.push({ path: source, localPath: destination, bytes, sha256 });
      } finally {
        await input.close(); await output?.close().catch(() => {});
        if (!committed) await fs.rm(temporary, { force: true }).catch(() => {});
      }
    };

    if (args.action === 'read') {
      const meta = await metadata(target);
      if (!meta.isFile || meta.isSymlink) throw new Error('Remote path must be a regular file');
      const limit = positive(args.maxBytes, DEFAULT_READ_BYTES, MAX_READ_BYTES);
      const offset = args.offset ?? 0;
      if (!Number.isSafeInteger(offset) || offset < 0) throw new Error('offset must be a nonnegative byte offset');
      const bytes = await readBounded(target, limit, offset);
      return { action: 'read', path: target, content: bytes.toString(args.encoding === 'base64' ? 'base64' : 'utf8'), bytes: bytes.length, offset, truncated: offset + bytes.length < meta.size };
    }
    if (args.action === 'write') {
      if (typeof args.content !== 'string') throw new Error('write requires string content');
      const bytes = Buffer.from(args.content, args.encoding === 'base64' ? 'base64' : 'utf8');
      const counters = { files: 0, bytes: 0, changes: [] };
      await uploadFile(bytes, target, counters);
      return { action: 'write', path: target, ...counters };
    }
    if (args.action === 'list' || args.action === 'search') {
      const searching = args.action === 'search';
      if (searching && (typeof args.query !== 'string' || !args.query)) throw new Error('search requires a nonempty literal query');
      const maxEntries = positive(args.maxEntries, searching ? 2000 : 500, 10000);
      const maxMatches = positive(args.maxMatches, 200, 2000);
      const readLimit = positive(args.maxBytes, 64 * 1024, DEFAULT_READ_BYTES);
      const entries = [], matches = [], pending = [target]; let truncated = false, stopped = false, visited = 0;
      const needle = args.caseSensitive ? args.query : args.query?.toLowerCase();
      while (pending.length && !stopped) {
        const current = pending.pop(), meta = await metadata(current);
        if (meta.isSymlink) continue;
        if (meta.isDirectory) {
          const listing = await directory(current);
          for (const row of listing.entries) {
            if (++visited > maxEntries) { truncated = stopped = true; break; }
            const value = childPath(current, row.fileName);
            if (!searching) entries.push({ name: row.fileName, path: value, type: row.isDirectory ? 'directory' : row.isFile ? 'file' : 'other' });
            if (searching || args.recursive) pending.push(value);
          }
        } else if (searching && meta.isFile) {
          const data = await readBounded(current, readLimit);
          if (data.includes(0)) continue;
          const lines = data.toString('utf8').split(/\r?\n/);
          for (let line = 0; line < lines.length; line++) {
            if ((args.caseSensitive ? lines[line] : lines[line].toLowerCase()).includes(needle)) {
              matches.push({ path: current, line: line + 1, text: lines[line].slice(0, 2000) });
              if (matches.length >= maxMatches) { truncated = stopped = true; break; }
            }
          }
          if (meta.size > data.length) truncated = true;
        }
      }
      return searching ? { action: 'search', path: target, query: args.query, matches, filesVisited: visited, truncated } : { action: 'list', path: target, entries, truncated };
    }
    if (args.action === 'upload' || args.action === 'download') {
      if (typeof args.localPath !== 'string' || !args.localPath || args.localPath.includes('\0')) throw new Error('Transfer requires localPath');
      const local = path.resolve(localCwd, args.localPath);
      const counters = { files: 0, directories: 0, bytes: 0, changes: [] };
      if (args.action === 'upload') {
        const walk = async (source, destination) => {
          signal?.throwIfAborted();
          const meta = await fs.lstat(source);
          if (meta.isSymbolicLink()) throw new Error('Folder transfers do not follow symbolic links');
          if (meta.isDirectory()) {
            await mkdir(destination); counters.directories++;
            for (const row of await fs.readdir(source)) await walk(path.join(source, row), paths.join(destination, row));
          } else if (meta.isFile()) await uploadFile(source, destination, counters);
          else throw new Error('Transfer source must be a regular file or directory');
        };
        await walk(local, target);
      } else {
        const walk = async (source, destination) => {
          signal?.throwIfAborted();
          const meta = await metadata(source);
          if (meta.isSymlink) throw new Error('Folder transfers do not follow symbolic links');
          if (meta.isDirectory) {
            await fs.mkdir(destination, { recursive: true }); counters.directories++;
            for (const row of (await directory(source)).entries) {
              childPath(source, row.fileName);
              // Reject target-platform filenames that would become drive paths
              // or NTFS alternate streams instead of the requested child file.
              if (path.basename(row.fileName) !== row.fileName || process.platform === 'win32' && /[<>:"|?*]|[. ]$/.test(row.fileName))
                throw new Error('Remote filename cannot be represented safely on the local filesystem: ' + row.fileName);
              await walk(paths.join(source, row.fileName), path.join(destination, row.fileName));
            }
          } else if (meta.isFile) await downloadFile(source, destination, counters);
          else throw new Error('Transfer source must be a regular file or directory');
        };
        await walk(target, local);
      }
      return { action: args.action, path: target, localPath: local, cwd: localCwd, ...counters };
    }
    throw new Error('Unknown remote file action');
  } };
}
