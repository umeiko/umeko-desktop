// Desktop commands always use the loaded Pi runtime and its actual configuration.
import { Type } from 'typebox';
import { readFileSync, existsSync, mkdirSync, writeFileSync, renameSync } from 'node:fs';
import { dirname, join, resolve, delimiter } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';

export const PI_COMMAND_TOOL = 'run_pi_command';
export const DESKTOP_PI_PROMPT = 'You are Umeko, powered by Pi embedded in Umeko Desktop. For Pi/MCP/extension management and slash commands, use run_pi_command; it targets this running session and its configuration. Do not invoke a system pi binary or install a separate Pi. Models and credentials are managed in Umeko settings.';

// Parse quoted arguments without evaluating a shell, substitutions or pipelines.
export function commandWords(text) {
  if (typeof text !== 'string' || !text.trim() || text.length > 16384 || /[\0\r\n]/.test(text)) throw new Error('请输入一条 Pi 命令');
  const words = []; let word = '', quote = '', started = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quote) {
      if (c === quote) quote = '';
      else if (c === '\\' && quote === '"' && ['"', '\\'].includes(text[i + 1])) word += text[++i];
      else word += c;
      started = true;
    } else if (c === '"' || c === "'") { quote = c; started = true; }
    else if (/\s/.test(c)) { if (started) { words.push(word); word = ''; started = false; } }
    else if (/[;&|<>`]/.test(c) || c === '$' && text[i + 1] === '(') throw new Error('只接受 Pi 命令，不执行 Shell 组合或替换');
    else if (c === '\\' && /[\s'"\\]/.test(text[i + 1] || '')) { word += text[++i]; started = true; }
    else { word += c; started = true; }
  }
  if (quote) throw new Error('命令中的引号没有闭合');
  if (started) words.push(word);
  return words;
}

function scopedMcpArgs(words, local) {
  const result = []; let positional = 0;
  const takesValue = new Set(['--url','--env','--cwd','--header','--bearer-token-env-var','--oauth-client-id','--oauth-client-secret','--oauth-callback-port','--oauth-client-name','--exposure','--description']);
  for (let i = 0; i < words.length; i++) {
    const word = words[i];
    if (word === '--' || positional >= 2) { result.push(...words.slice(i)); break; }
    if (word === '--local' || word === '-l') continue;
    result.push(word);
    if (takesValue.has(word)) { if (i + 1 < words.length) result.push(words[++i]); }
    else if (!word.startsWith('-')) positional++;
  }
  return local === undefined ? words : [...(local ? ['--local'] : []), ...result];
}

async function mcpModules() {
  const entry = import.meta.resolve('@earendil-works/pi-coding-agent');
  const [cli, config, schema] = await Promise.all([
    import(new URL('./extensions/mcp/cli.js', entry)),
    import(new URL('./extensions/mcp/config.js', entry)),
    import(new URL('./core/mcp-servers.js', entry)),
  ]);
  return { ...cli, ...config, ...schema };
}

export async function addMcpFromInput(input) {
  if (typeof input.text !== 'string' || !input.text.trim() || input.text.length > 1000000) throw new Error('请粘贴 pi mcp add 命令或 MCP JSON');
  const { runMcpCommand, validateMcpServerConfig } = await mcpModules();
  const cwd = resolve(input.cwd), agentDir = resolve(input.agentDir);
  if (input.local && !existsSync(cwd)) throw new Error('请先打开项目目录');
  const path = input.local ? join(cwd, '.pi/mcp.json') : join(agentDir, 'mcp.json');
  const text = input.text.trim();
  if (!text.startsWith('{')) {
    let words = commandWords(text);
    if (words[0] === 'pi') words.shift();
    if (words.shift() !== 'mcp' || words.shift() !== 'add') throw new Error('请使用 pi mcp add <名称> -- <命令>，或 --url <网址>');
    const messages = [], errors = [];
    const code = await runMcpCommand(['add', ...scopedMcpArgs(words, !!input.local)], { cwd, agentDir, log: line => messages.push(line), error: line => errors.push(line) });
    if (code) throw new Error(errors.join('\n') || 'Pi 未接受此 MCP 命令');
    return { path, message: 'MCP 服务器已添加', output: messages.join('\n') };
  }
  const parsed = JSON.parse(text);
  const servers = parsed.mcpServers ?? parsed;
  if (!servers || typeof servers !== 'object' || Array.isArray(servers) || !Object.keys(servers).length) throw new Error('JSON 中需要包含具名的 mcpServers 配置');
  const validated = {};
  for (const [name, value] of Object.entries(servers)) {
    const server = validateMcpServerConfig(name, value);
    if (typeof server === 'string') throw new Error(server);
    Object.defineProperty(validated, name, { value: server, enumerable: true });
  }
  const previous = existsSync(path) ? JSON.parse(readFileSync(path, 'utf8')) : {};
  if (!previous || typeof previous !== 'object' || Array.isArray(previous) || previous.mcpServers && (typeof previous.mcpServers !== 'object' || Array.isArray(previous.mcpServers))) throw new Error('现有 MCP 配置格式无效，请先修复');
  const next = { ...previous, mcpServers: { ...(previous.mcpServers || {}), ...validated } };
  mkdirSync(dirname(path), { recursive: true });
  const temporary = path + '.' + randomUUID() + '.tmp';
  writeFileSync(temporary, JSON.stringify(next, null, 2) + '\n', { mode: 0o600 });
  renameSync(temporary, path);
  return { path, message: `已添加 ${Object.keys(validated).length} 个 MCP 服务器` };
}

export function createPiCommandController({ Pi, getRuntime, getConfig, reload, invokeSlash, notify }) {
  const pending = [];
  const info = () => {
    const session = getRuntime().session, manager = session.sessionManager;
    return { sessionId: manager.getSessionId(), sessionFile: manager.getSessionFile(), workspace: manager.getCwd(), agentDir: getConfig().agentDir };
  };
  const queue = (command, toolCallId) => {
    const sessionId = info().sessionId;
    if (!pending.some(item => item.command === command && item.sessionId === sessionId)) pending.push({ command, sessionId, toolCallId });
    return { ...info(), status: 'queued', command, message: '已排队，将在本轮回复结束后作用于当前 Pi 会话。' };
  };
  const help = () => ({ ...info(), commands: ['pi install <source> [-l]', 'pi remove <source> [-l]', 'pi list', 'pi mcp add …', 'pi mcp remove <server> [-l]', 'pi mcp list', 'pi mcp login/logout <server>', '/reload', '/compact [instructions]', '/session', '/name <title>', ...getRuntime().session.extensionRunner.getRegisteredCommands().map(c => '/' + c.name)] });
  const slash = async command => {
    const session = getRuntime().session;
    const [name, ...rest] = commandWords(command), args = rest.join(' ');
    if (name === '/reload') { if (args) throw new Error('/reload 不接受参数'); await reload(session); return { message: '当前 Pi 已重新加载', ...info() }; }
    if (name === '/compact') { const result = await session.compact(args || undefined); return { message: '当前 Pi 上下文已压缩', tokensBefore: result?.tokensBefore, ...info() }; }
    if (name === '/name') { if (!args) return { name: session.sessionManager.getSessionName(), ...info() }; session.setSessionName(args); return { message: '会话名称已更新', ...info() }; }
    if (!session.extensionRunner.getCommand(name.slice(1))) throw new Error('当前内嵌 Pi 不支持此命令；使用 /help 查看可用命令。');
    return { ...await invokeSlash(command), ...info() };
  };
  const nativeCli = (args, signal) => new Promise((done, fail) => {
    const entry = import.meta.resolve('@earendil-works/pi-coding-agent');
    const context = info();
    const env = { ...process.env, PI_CODING_AGENT_DIR: context.agentDir, PI_SKIP_VERSION_CHECK: '1', NO_COLOR: '1', PATH: dirname(process.execPath) + delimiter + (process.env.PATH || '') };
    delete env.PI_OFFLINE;
    const child = spawn(process.execPath, [fileURLToPath(new URL('./cli.js', entry)), ...args], { cwd: context.workspace, env, windowsHide: true, signal, stdio: ['ignore','pipe','pipe'] });
    let output = '';
    const collect = data => { output = (output + data.toString()).slice(-24000); };
    child.stdout.on('data', collect); child.stderr.on('data', collect);
    child.on('error', fail);
    child.on('close', code => code === 0 ? done({ ...context, status: 'completed', output }) : fail(new Error(signal?.aborted ? 'Pi 操作已取消' : output || `Pi 命令未成功完成（${code}）`)));
  });
  const run = async (text, { signal, toolCallId, scope } = {}) => {
    if (signal?.aborted) throw new Error('Pi 操作已取消');
    let words = commandWords(text);
    if (words[0] === 'pi') words.shift();
    if (!words.length || ['help','--help','-h','/help'].includes(words[0])) return help();
    const session = getRuntime().session;
    if (words[0] === '/session') return { ...info(), contextUsage: session.getContextUsage() };
    if (words[0].startsWith('/')) {
      const name = words[0];
      if (!['/reload','/compact','/name'].includes(name) && !session.extensionRunner.getCommand(name.slice(1))) throw new Error('当前内嵌 Pi 不支持此命令；使用 /help 查看可用命令。');
      return session.isIdle ? slash(text.replace(/^\s*pi\s+/, '')) : queue(text.replace(/^\s*pi\s+/, ''), toolCallId);
    }
    const [action, ...args] = words;
    if (action === 'mcp') {
      const [operation, ...parameters] = args;
      if (['list','login','logout','reconnect'].includes(operation) || !operation) return run('/mcp' + (operation && operation !== 'list' ? ' ' + [operation, ...parameters].join(' ') : ''), { signal, toolCallId });
      if (!['add','remove'].includes(operation)) throw new Error('支持 pi mcp add/remove/list/login/logout/reconnect');
      const { runMcpCommand } = await mcpModules();
      const output = [], errors = [];
      const local = scope === undefined ? undefined : scope === 'project';
      if (getConfig().agent?.safeMode) throw new Error('请先在 Umeko 中关闭恢复模式，再修改 MCP 配置');
      const code = await runMcpCommand([operation, ...scopedMcpArgs(parameters, local)], { cwd: info().workspace, agentDir: info().agentDir, log: line => output.push(line), error: line => errors.push(line) });
      if (code) throw new Error(errors.join('\n') || 'MCP 命令未成功完成');
      if (signal?.aborted) throw new Error('Pi 操作已取消');
      const applied = session.isIdle ? await slash('/reload') : queue('/reload', toolCallId);
      return { ...info(), status: 'completed', output: output.join('\n'), reload: applied.status || 'completed' };
    }
    if (!['install','remove','uninstall','list'].includes(action)) throw new Error('支持 pi install/remove/list、pi mcp 和当前会话的斜杠命令；使用 /help 查看用法。');
    if (action === 'list') {
      if (args.length) throw new Error('用法：pi list');
      const settingsManager = Pi.SettingsManager.create(info().workspace, info().agentDir, { projectTrusted: !getConfig().agent?.safeMode });
      const manager = new Pi.DefaultPackageManager({ cwd: info().workspace, agentDir: info().agentDir, settingsManager });
      return { ...info(), packages: manager.listConfiguredPackages() };
    }
    if (getConfig().agent?.safeMode) throw new Error('请先在 Umeko 中关闭恢复模式，再修改 Pi 扩展');
    const local = scope === 'project' || scope === undefined && args.some(a => ['--local','-l'].includes(a));
    const sources = args.filter(a => !['--local','-l'].includes(a));
    if (sources.length !== 1 || !sources[0] || sources[0].startsWith('-')) throw new Error('一次操作一个 npm、Git 或本地扩展来源');
    const result = await nativeCli([action === 'uninstall' ? 'remove' : action, sources[0], local ? '--approve' : '--no-approve', ...(local ? ['--local'] : [])], signal);
    if (signal?.aborted) throw new Error('Pi 操作已取消');
    const applied = session.isIdle ? await slash('/reload') : queue('/reload', toolCallId);
    return { ...result, reload: applied.status || 'completed' };
  };
  return {
    run,
    async flush() {
      const reports = [];
      while (pending.length) {
        const item = pending.shift();
        if (item.sessionId !== info().sessionId) { notify('Pi 命令未执行：原会话已经切换'); continue; }
        try {
          const result = await slash(item.command);
          getRuntime().session.sessionManager.appendCustomEntry('umeko-pi-command', { toolCallId: item.toolCallId, command: item.command, status: 'completed', result });
          reports.push({ command: item.command, status: 'completed', result });
          notify(result.message || `Pi ${item.command.split(' ')[0]} 已完成`);
        } catch (error) {
          getRuntime().session.sessionManager.appendCustomEntry('umeko-pi-command', { toolCallId: item.toolCallId, command: item.command, status: 'failed', message: error.message });
          reports.push({ command: item.command, status: 'failed', message: error.message });
          notify(`Pi 命令失败：${error.message}`);
        }
      }
      return reports;
    },
    clear() { pending.length = 0; },
    extension(pi) {
      pi.registerTool({ name: PI_COMMAND_TOOL, label: '运行当前 Pi 命令', exposure: 'direct',
        description: 'Manage this embedded Pi instance, its extensions and MCP servers. Accepts pi install/remove/list, pi mcp commands, /session, /name, /reload, /compact and commands registered by loaded extensions. This is not a shell. Reload, compaction and extension commands requested during a turn are queued until the response finishes; queued is not completed. Use /help for current paths and supported commands.',
        promptSnippet: 'Run Pi administration and slash commands in the current Umeko session.',
        promptGuidelines: ['Use run_pi_command instead of shell pi commands or a separate Pi install. For MCP additions use pi mcp add; for extensions use pi install. Report queued commands as queued until completion is reported.'],
        parameters: Type.Object({ command: Type.String({ minLength: 1, maxLength: 16384 }), scope: Type.Optional(Type.Union([Type.Literal('global'), Type.Literal('project')])) }),
        async execute(id, params, signal) {
          const result = await run(params.command, { signal, toolCallId: id, scope: params.scope });
          return { content: [{ type: 'text', text: JSON.stringify(result) }], details: { umekoPiCommand: result } };
        },
      });
    },
  };
}

if (process.argv.includes('--add-mcp') && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    let raw = ''; for await (const chunk of process.stdin) raw += chunk;
    const input = JSON.parse(raw);
    const result = await addMcpFromInput(input);
    process.stdout.write(JSON.stringify({ ok: true, ...result }) + '\n');
  } catch (error) { process.stdout.write(JSON.stringify({ ok: false, error: error.message }) + '\n'); process.exitCode = 1; }
}
