/**
 * Pi Coding Agent inline extension that routes the 7 built-in workspace tools
 * (read, write, edit, bash/powershell, ls, find, grep), user `!` commands, and
 * working-directory system prompt to a remote machine over Umeko's exec-server.
 *
 * Adapted from Pi Coding Agent 1.5.2 examples/extensions/ssh.ts (MIT, Mario Zechner).
 * Full license in THIRD_PARTY_NOTICES.md.
 * Keeps Pi itself unmodified and preserves remote_command / remote_files.
 */
import nodePath from "node:path";
import { Minimatch } from "minimatch";
import { runRemoteProcess } from "./remote-environments.mjs";
import {
  joinRemotePath,
  nativePathFromUri,
  normalizeRemotePath,
  relPathUnder,
  remoteDirname,
  remotePathToUri,
  resolveRemoteWorkspacePath,
} from "./remote-paths.mjs";

const DEFAULT_FIND_LIMIT = 1000;
const DEFAULT_GREP_LIMIT = 100;
const MAX_FALLBACK_FILE_BYTES = 512 * 1024;
const MAX_FALLBACK_FILES = 5000;
const isMissingError = error => /ENOENT|not found|no such file|cannot find|os error 2\b|os error 3\b|系统找不到指定的文件|系统找不到指定的路径/i.test(String(error?.message ?? error));
const isSpawnMissing = error => /ENOENT|not found|no such file|cannot find|SpawnNotFound|os error 2\b|系统找不到指定的文件/i.test(String(error?.message ?? error));

function sniffImageMime(buf) {
  if (!Buffer.isBuffer(buf) || buf.length < 12) return null;
  if (buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47) return "image/png";
  if (buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return "image/jpeg";
  if (buf[0] === 0x47 && buf[1] === 0x49 && buf[2] === 0x46 && buf[3] === 0x38) return "image/gif";
  if (buf[0] === 0x52 && buf[1] === 0x49 && buf[2] === 0x46 && buf[3] === 0x46 &&
      buf[8] === 0x57 && buf[9] === 0x45 && buf[10] === 0x42 && buf[11] === 0x50) return "image/webp";
  return null;
}

function powershellUtf8Argv(command) {
  const full = "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)\n" +
    "[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)\n" +
    "$OutputEncoding = [Console]::OutputEncoding\n" +
    String(command || "");
  return ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", Buffer.from(full, "utf16le").toString("base64")];
}

function decodeRgText(data) {
  if (typeof data?.text === "string") return data.text;
  if (typeof data?.bytes === "string") return Buffer.from(data.bytes, "base64").toString("utf8");
  return "";
}

function buildGlobMatcher(pattern, isPathPattern) {
  let effective = String(pattern || "").replaceAll("\\", "/").replace(/^(!?)(?:\.\/)+/, "$1");
  if (isPathPattern && !effective.startsWith("/") && !effective.startsWith("**/") && effective !== "**") {
    effective = `**/${effective}`;
  }
  return new Minimatch(effective.replace(/\/\*\*$/, "/**/*"), {
    dot: true,
    noext: true,
    nocase: effective === effective.toLowerCase(),
  });
}

function shouldIgnoreRel(relPosix, ignoreMatchers) {
  return ignoreMatchers.some(matcher => matcher.match(relPosix) || matcher.match(`${relPosix}/`));
}

export function createRemoteWorkspaceExtension({
  remoteWorkspace,
  getEntry,
  emit,
  localCwd,
  toolsApi,
}) {
  if (!remoteWorkspace?.environment || !remoteWorkspace?.remotePath) {
    throw new Error("remoteWorkspace requires environment and remotePath");
  }
  const { environment: envName, host, platform: configuredPlatform, remotePath: rawRemotePath } = remoteWorkspace;

  async function resolveContext(signal, ctx) {
    const entry = await getEntry(envName, signal);
    const platform = entry.platform || configuredPlatform || "linux";
    const remoteRoot = normalizeRemotePath(rawRemotePath, platform);
    if (entry.connection.state === "reconnecting") {
      ctx?.ui?.setStatus?.("remote", "正在重新连接");
      emit?.({ type: "status", text: "正在重新连接" });
    }
    const info = await entry.connection.ready();
    const homeDir = nativePathFromUri(info.userHomeDir || info.cwd, platform);
    return { entry, platform, remoteRoot, homeDir, info };
  }

  function mapRemotePath(raw, { remoteRoot, platform, homeDir }) {
    return resolveRemoteWorkspacePath(remoteRoot, raw, { mirrorDir: localCwd, platform, homeDir });
  }

  async function detectWindowsBash(entry, signal) {
    if (entry.windowsBashPath !== undefined) return entry.windowsBashPath;
    const candidates = [
      "C:\\Program Files\\Git\\bin\\bash.exe",
      "C:\\Program Files\\Git\\usr\\bin\\bash.exe",
      "C:\\Program Files (x86)\\Git\\bin\\bash.exe",
    ];
    for (const candidate of candidates) {
      try {
        const meta = await entry.connection.rpc("fs/getMetadata", {
          path: remotePathToUri(candidate, "windows"),
          followSymlinks: true,
        }, { signal });
        if (meta?.isFile) {
          entry.windowsBashPath = candidate;
          return candidate;
        }
      } catch {
        // Try next candidate.
      }
    }
    try {
      const probe = await runRemoteProcess(entry.connection, "windows", {
        argv: ["where.exe", "bash.exe"],
        timeoutMs: 10_000,
        signal,
      });
      const found = probe.stdout
        .split(/\r?\n/)
        .map(line => line.trim())
        .find(line => line && !/\\system32\\bash\.exe$/i.test(line));
      entry.windowsBashPath = found || null;
    } catch {
      entry.windowsBashPath = null;
    }
    return entry.windowsBashPath;
  }

  async function remoteShellExec(shellKind, command, cwd, { onData, signal, timeout }, ctx) {
    const { entry, platform, remoteRoot, homeDir, info } = await resolveContext(signal, ctx);
    const targetCwd = cwd ? mapRemotePath(cwd, { remoteRoot, platform, homeDir }) : remoteRoot;
    let argv;
    if (shellKind === "powershell") {
      argv = platform === "windows"
        ? powershellUtf8Argv(command)
        : ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command];
    } else if (platform === "windows") {
      const gitBash = await detectWindowsBash(entry, signal);
      argv = gitBash ? [gitBash, "-c", command] : powershellUtf8Argv(command);
    } else {
      const detected = typeof info.shell === "string" ? info.shell : info.shell?.path;
      const posixShell = detected && /(?:^|\/)(?:bash|zsh|sh)$/.test(detected) ? detected : "/bin/sh";
      argv = [posixShell, "-c", command];
    }
    const result = await runRemoteProcess(entry.connection, platform, {
      argv,
      cwd: targetCwd,
      timeoutMs: timeout ? timeout * 1000 : undefined,
      onData: chunk => onData?.(chunk),
      signal,
    });
    if (result.aborted || signal?.aborted) throw new Error("aborted");
    if (result.timedOut) throw new Error(`timeout:${timeout}`);
    return { exitCode: result.exitCode };
  }

  async function walkRemoteFiles(entry, platform, rootDir, { ignore = ["**/node_modules/**", "**/.git/**"], signal, maxFiles = MAX_FALLBACK_FILES } = {}) {
    const ignoreMatchers = ignore.map(pat => new Minimatch(pat, { dot: true, noext: true }));
    const queue = [{ dir: rootDir, rel: "" }];
    const results = [];
    let visited = 0;
    while (queue.length && visited < maxFiles) {
      signal?.throwIfAborted();
      const current = queue.shift();
      let listing;
      try {
        listing = await entry.connection.rpc("fs/readDirectory", { path: remotePathToUri(current.dir, platform) }, { signal });
      } catch {
        continue;
      }
      const entries = (listing.entries || [])
        .filter(item => item?.fileName && item.fileName !== "." && item.fileName !== ".." && !/[\\/\0]/.test(item.fileName))
        .sort((a, b) => a.fileName.toLowerCase().localeCompare(b.fileName.toLowerCase()));
      for (const item of entries) {
        const relPosix = current.rel ? `${current.rel}/${item.fileName}` : item.fileName;
        if (shouldIgnoreRel(relPosix, ignoreMatchers)) continue;
        const fullPath = joinRemotePath(current.dir, item.fileName, platform);
        results.push({ relPosix, fullPath, isDirectory: item.isDirectory === true, isFile: item.isFile === true });
        visited++;
        if (item.isDirectory) queue.push({ dir: fullPath, rel: relPosix });
        if (visited >= maxFiles) break;
      }
    }
    return results;
  }

  return pi => {
    const {
      createReadToolDefinition,
      createWriteToolDefinition,
      createEditToolDefinition,
      createBashToolDefinition,
      createPowerShellToolDefinition,
      createLsToolDefinition,
      createFindToolDefinition,
      createGrepToolDefinition,
      truncateHead,
      truncateLine,
      formatSize,
      DEFAULT_MAX_BYTES,
    } = toolsApi;

    const baseRead = createReadToolDefinition(localCwd);
    const baseWrite = createWriteToolDefinition(localCwd);
    const baseEdit = createEditToolDefinition(localCwd);
    const baseBash = createBashToolDefinition(localCwd);
    const basePowerShell = createPowerShellToolDefinition(localCwd);
    const baseLs = createLsToolDefinition(localCwd);
    const baseFind = createFindToolDefinition(localCwd);
    const baseGrep = createGrepToolDefinition(localCwd);

    // 1. read
    pi.registerTool({
      ...baseRead,
      async execute(id, params, signal, onUpdate, ctx) {
        const remote = await resolveContext(signal, ctx);
        const target = mapRemotePath(params.path, remote);
        const uri = remotePathToUri(target, remote.platform);
        let cachedBuffer = null;
        const loadBuffer = async () => {
          if (cachedBuffer) return cachedBuffer;
          const res = await remote.entry.connection.rpc("fs/readFile", { path: uri, followSymlinks: true }, { signal });
          cachedBuffer = Buffer.from(res.dataBase64, "base64");
          return cachedBuffer;
        };
        const tool = createReadToolDefinition(localCwd, {
          operations: {
            access: async () => {
              const meta = await remote.entry.connection.rpc("fs/getMetadata", { path: uri, followSymlinks: true }, { signal });
              if (meta?.isDirectory) throw new Error(`EISDIR: illegal operation on a directory, read '${target}'`);
            },
            readFile: () => loadBuffer(),
            detectImageMimeType: async () => sniffImageMime(await loadBuffer()),
          },
        });
        return tool.execute(id, params, signal, onUpdate, ctx);
      },
    });

    // 2. write
    pi.registerTool({
      ...baseWrite,
      async execute(id, params, signal, onUpdate, ctx) {
        const remote = await resolveContext(signal, ctx);
        const target = mapRemotePath(params.path, remote);
        const parent = remoteDirname(target, remote.platform);
        const tool = createWriteToolDefinition(localCwd, {
          operations: {
            mkdir: async () => {
              if (!parent || parent === "/" || /^[A-Za-z]:\\?$/.test(parent)) return;
              await remote.entry.connection.rpc("fs/createDirectory", {
                path: remotePathToUri(parent, remote.platform),
                recursive: true,
                followSymlinks: false,
              }, { signal, retry: true });
            },
            writeFile: async (_p, content) => {
              await remote.entry.connection.rpc("fs/writeFile", {
                path: remotePathToUri(target, remote.platform),
                dataBase64: Buffer.from(content, "utf8").toString("base64"),
                followSymlinks: false,
              }, { signal, retry: true });
            },
          },
        });
        return tool.execute(id, params, signal, onUpdate, ctx);
      },
    });

    // 3. edit
    pi.registerTool({
      ...baseEdit,
      async execute(id, params, signal, onUpdate, ctx) {
        const remote = await resolveContext(signal, ctx);
        const target = mapRemotePath(params.path, remote);
        const uri = remotePathToUri(target, remote.platform);
        const tool = createEditToolDefinition(localCwd, {
          operations: {
            access: async () => {
              const meta = await remote.entry.connection.rpc("fs/getMetadata", { path: uri, followSymlinks: true }, { signal });
              if (!meta?.isFile) throw new Error(`File not found: ${target}`);
            },
            readFile: async () => {
              const res = await remote.entry.connection.rpc("fs/readFile", { path: uri, followSymlinks: true }, { signal });
              return Buffer.from(res.dataBase64, "base64");
            },
            writeFile: async (_p, content) => {
              await remote.entry.connection.rpc("fs/writeFile", {
                path: uri,
                dataBase64: Buffer.from(content, "utf8").toString("base64"),
                followSymlinks: false,
              }, { signal, retry: true });
            },
          },
        });
        return tool.execute(id, params, signal, onUpdate, ctx);
      },
    });

    // 4. bash (and powershell)
    pi.registerTool({
      ...baseBash,
      async execute(id, params, signal, onUpdate, ctx) {
        const tool = createBashToolDefinition(localCwd, {
          operations: {
            exec: (command, cwd, opts) => remoteShellExec("bash", command, cwd, opts, ctx),
          },
        });
        return tool.execute(id, params, signal, onUpdate, ctx);
      },
    });

    pi.registerTool({
      ...basePowerShell,
      async execute(id, params, signal, onUpdate, ctx) {
        const tool = createPowerShellToolDefinition(localCwd, {
          operations: {
            exec: (command, cwd, opts) => remoteShellExec("powershell", command, cwd, opts, ctx),
          },
        });
        return tool.execute(id, params, signal, onUpdate, ctx);
      },
    });

    // 5. ls
    pi.registerTool({
      ...baseLs,
      async execute(id, params, signal, onUpdate, ctx) {
        const remote = await resolveContext(signal, ctx);
        const targetDir = mapRemotePath(params.path || ".", remote);
        const uri = remotePathToUri(targetDir, remote.platform);
        let rootMeta = null;
        let rootKey = "";
        const entryMap = new Map();
        const tool = createLsToolDefinition(localCwd, {
          operations: {
            exists: async p => {
              rootKey = p;
              try {
                rootMeta = await remote.entry.connection.rpc("fs/getMetadata", { path: uri, followSymlinks: true }, { signal });
                return true;
              } catch (error) {
                if (isMissingError(error)) return false;
                throw error;
              }
            },
            stat: async p => {
              if (p === rootKey) {
                if (!rootMeta) {
                  rootMeta = await remote.entry.connection.rpc("fs/getMetadata", { path: uri, followSymlinks: true }, { signal });
                }
                return { isDirectory: () => rootMeta.isDirectory === true };
              }
              const name = p.startsWith(rootKey + nodePath.sep) ? p.slice(rootKey.length + 1) : nodePath.basename(p);
              const cached = entryMap.get(name);
              if (cached) return { isDirectory: () => cached.isDirectory === true };
              const childMeta = await remote.entry.connection.rpc("fs/getMetadata", {
                path: remotePathToUri(joinRemotePath(targetDir, name, remote.platform), remote.platform),
                followSymlinks: true,
              }, { signal });
              return { isDirectory: () => childMeta.isDirectory === true };
            },
            readdir: async () => {
              const listing = await remote.entry.connection.rpc("fs/readDirectory", { path: uri }, { signal });
              entryMap.clear();
              const names = [];
              for (const item of listing.entries || []) {
                if (!item?.fileName || item.fileName === "." || item.fileName === "..") continue;
                entryMap.set(item.fileName, item);
                names.push(item.fileName);
              }
              return names;
            },
          },
        });
        return tool.execute(id, params, signal, onUpdate, ctx);
      },
    });

    // 6. find
    pi.registerTool({
      ...baseFind,
      async execute(id, params, signal, onUpdate, ctx) {
        const remote = await resolveContext(signal, ctx);
        const searchDir = mapRemotePath(params.path || ".", remote);
        const tool = createFindToolDefinition(localCwd, {
          operations: {
            exists: async () => {
              try {
                await remote.entry.connection.rpc("fs/getMetadata", {
                  path: remotePathToUri(searchDir, remote.platform),
                  followSymlinks: true,
                }, { signal });
                return true;
              } catch (error) {
                if (isMissingError(error)) return false;
                throw error;
              }
            },
            glob: async (pattern, _searchPath, options = {}) => {
              const limit = Math.max(1, Number(options.limit || DEFAULT_FIND_LIMIT));
              const ignore = options.ignore || ["**/node_modules/**", "**/.git/**"];
              const walked = await walkRemoteFiles(remote.entry, remote.platform, searchDir, { ignore, signal });
              const normalizedPattern = String(pattern || "").replaceAll("\\", "/");
              const isPathPattern = normalizedPattern.includes("/");
              const matcher = buildGlobMatcher(normalizedPattern, isPathPattern);
              const matches = [];
              for (const item of walked) {
                const candidate = isPathPattern ? item.relPosix : item.relPosix.split("/").pop();
                if (matcher.match(candidate) || matcher.match(item.relPosix)) {
                  matches.push(item.isDirectory ? `${item.relPosix}/` : item.relPosix);
                  if (matches.length >= limit) break;
                }
              }
              return matches;
            },
          },
        });
        return tool.execute(id, params, signal, onUpdate, ctx);
      },
    });

    // 7. grep (prefer remote rg -> fallback remote grep -rn -> fallback remote fs walk)
    pi.registerTool({
      ...baseGrep,
      async execute(_id, { pattern, path: searchDir, glob, ignoreCase, literal, context, limit }, signal, _onUpdate, ctx) {
        signal?.throwIfAborted();
        const remote = await resolveContext(signal, ctx);
        const target = mapRemotePath(searchDir || ".", remote);
        let meta;
        try {
          meta = await remote.entry.connection.rpc("fs/getMetadata", {
            path: remotePathToUri(target, remote.platform),
            followSymlinks: true,
          }, { signal });
        } catch {
          throw new Error(`Path not found: ${target}`);
        }
        const isDirectory = meta.isDirectory === true;
        const effectiveLimit = Math.max(1, Math.floor(limit ?? DEFAULT_GREP_LIMIT));
        const contextValue = context && context > 0 ? Math.min(Math.floor(context), 50) : 0;

        const formatResult = (outputLines, matchCount, matchLimitReached, linesTruncated) => {
          if (matchCount === 0) return { content: [{ type: "text", text: "No matches found" }], details: undefined };
          const rawOutput = outputLines.join("\n");
          const truncation = truncateHead(rawOutput, { maxLines: Number.MAX_SAFE_INTEGER });
          let output = truncation.content;
          const details = {};
          const notices = [];
          if (matchLimitReached) {
            notices.push(`${effectiveLimit} matches limit reached. Use limit=${effectiveLimit * 2} for more, or refine pattern`);
            details.matchLimitReached = effectiveLimit;
          }
          if (truncation.truncated) {
            notices.push(`${formatSize(DEFAULT_MAX_BYTES)} limit reached`);
            details.truncation = truncation;
          }
          if (linesTruncated) {
            notices.push("Some lines truncated. Use read tool to see full lines");
            details.linesTruncated = true;
          }
          if (notices.length) output += `\n\n[${notices.join(". ")}]`;
          return { content: [{ type: "text", text: output }], details: Object.keys(details).length ? details : undefined };
        };

        const formatRel = filePath => {
          if (!isDirectory) return filePath.replaceAll("\\", "/").split("/").pop() || filePath;
          const cleaned = String(filePath).replace(/^\.[\\/]/, "").replaceAll("\\", "/");
          const rel = relPathUnder(target, filePath);
          return rel !== null ? rel : cleaned;
        };

        // Strategy A: remote ripgrep (rg)
        const rgArgs = ["--no-config", "--json", "--line-number", "--color=never", "--hidden"];
        if (ignoreCase) rgArgs.push("--ignore-case");
        if (literal) rgArgs.push("--fixed-strings");
        if (glob) rgArgs.push("--glob", glob.replace(/^(!?)(?:\.\/)+/, "$1"));
        if (contextValue > 0) rgArgs.push("--context", String(contextValue));
        rgArgs.push("--", pattern, isDirectory ? "." : target);
        try {
          const rgRun = await runRemoteProcess(remote.entry.connection, remote.platform, {
            argv: ["rg", ...rgArgs],
            cwd: isDirectory ? target : remoteDirname(target, remote.platform),
            timeoutMs: 60_000,
            signal,
          });
          if (rgRun.exitCode === 0 || rgRun.exitCode === 1) {
            const outputLines = [];
            let matchCount = 0, matchLimitReached = false, linesTruncated = false;
            for (const rawLine of rgRun.stdout.split(/\r?\n/)) {
              if (!rawLine.trim()) continue;
              let event;
              try { event = JSON.parse(rawLine); } catch { continue; }
              const isMatch = event.type === "match";
              if (!isMatch && event.type !== "context") continue;
              const filePath = decodeRgText(event.data?.path);
              const lineNumber = event.data?.line_number;
              if (!filePath || typeof lineNumber !== "number") continue;
              if (isMatch) {
                if (matchCount >= effectiveLimit) { matchLimitReached = true; break; }
                matchCount++;
              } else if (matchCount >= effectiveLimit) {
                continue;
              }
              const sanitized = decodeRgText(event.data?.lines).replace(/\r?\n?$/, "");
              const { text: truncatedText, wasTruncated } = truncateLine(sanitized);
              if (wasTruncated) linesTruncated = true;
              const rel = formatRel(filePath);
              outputLines.push(isMatch ? `${rel}:${lineNumber}: ${truncatedText}` : `${rel}-${lineNumber}- ${truncatedText}`);
            }
            return formatResult(outputLines, matchCount, matchLimitReached, linesTruncated);
          }
        } catch (error) {
          if (error?.name === "AbortError" || signal?.aborted) throw new Error("Operation aborted");
          if (!isSpawnMissing(error)) {
            // Fall through to grep / fs search.
          }
        }

        // Strategy B: remote GNU/POSIX grep -rn (Linux or Windows with grep on PATH)
        if (remote.platform !== "windows") {
          const grepArgs = ["-n", "-I", "--color=never"];
          if (isDirectory) grepArgs.push("-r", "--exclude-dir=.git", "--exclude-dir=node_modules");
          if (ignoreCase) grepArgs.push("-i");
          if (literal) grepArgs.push("-F");
          else grepArgs.push("-E");
          if (contextValue > 0) grepArgs.push("-C", String(contextValue));
          if (glob && isDirectory) grepArgs.push(`--include=${glob.replace(/^(!?)(?:\.\/)+/, "$1")}`);
          grepArgs.push("--", pattern, isDirectory ? "." : target);
          try {
            const grepRun = await runRemoteProcess(remote.entry.connection, remote.platform, {
              argv: ["grep", ...grepArgs],
              cwd: isDirectory ? target : remoteDirname(target, remote.platform),
              timeoutMs: 60_000,
              signal,
            });
            if (grepRun.exitCode === 0 || grepRun.exitCode === 1) {
              const outputLines = [];
              let matchCount = 0, matchLimitReached = false, linesTruncated = false;
              for (const rawLine of grepRun.stdout.split(/\r?\n/)) {
                if (!rawLine || rawLine === "--") continue;
                let rel, lineNo, text, isMatch;
                if (isDirectory) {
                  const m = rawLine.match(/^(.+?)([:\-])(\d+)\2(.*)$/);
                  if (!m) continue;
                  rel = formatRel(m[1]);
                  isMatch = m[2] === ":";
                  lineNo = Number(m[3]);
                  text = m[4];
                } else {
                  const m = rawLine.match(/^(\d+)([:\-])(.*)$/);
                  if (!m) continue;
                  rel = formatRel(target);
                  lineNo = Number(m[1]);
                  isMatch = m[2] === ":";
                  text = m[3];
                }
                if (isMatch) {
                  if (matchCount >= effectiveLimit) { matchLimitReached = true; break; }
                  matchCount++;
                } else if (matchCount >= effectiveLimit) {
                  continue;
                }
                const { text: truncatedText, wasTruncated } = truncateLine(text);
                if (wasTruncated) linesTruncated = true;
                outputLines.push(isMatch ? `${rel}:${lineNo}: ${truncatedText}` : `${rel}-${lineNo}- ${truncatedText}`);
              }
              return formatResult(outputLines, matchCount, matchLimitReached, linesTruncated);
            }
          } catch (error) {
            if (error?.name === "AbortError" || signal?.aborted) throw new Error("Operation aborted");
          }
        }

        // Strategy C: remote filesystem walk + match (works on bare Windows/Linux without rg or grep)
        const files = isDirectory
          ? (await walkRemoteFiles(remote.entry, remote.platform, target, { signal })).filter(item => item.isFile)
          : [{ relPosix: formatRel(target), fullPath: target, isFile: true }];
        const globMatcher = glob ? buildGlobMatcher(glob, glob.includes("/")) : null;
        const regex = literal
          ? null
          : new RegExp(pattern, ignoreCase ? "i" : "");
        const needle = ignoreCase ? pattern.toLowerCase() : pattern;
        const outputLines = [];
        let matchCount = 0, matchLimitReached = false, linesTruncated = false;
        for (const file of files) {
          signal?.throwIfAborted();
          if (globMatcher) {
            const base = file.relPosix.split("/").pop();
            if (!globMatcher.match(file.relPosix) && !globMatcher.match(base)) continue;
          }
          let fileBuf;
          try {
            const fmeta = await remote.entry.connection.rpc("fs/getMetadata", { path: remotePathToUri(file.fullPath, remote.platform), followSymlinks: true }, { signal });
            if (!fmeta?.isFile || fmeta.size > MAX_FALLBACK_FILE_BYTES) continue;
            const readRes = await remote.entry.connection.rpc("fs/readFile", { path: remotePathToUri(file.fullPath, remote.platform), followSymlinks: true }, { signal });
            fileBuf = Buffer.from(readRes.dataBase64, "base64");
          } catch {
            continue;
          }
          if (fileBuf.includes(0)) continue;
          const lines = fileBuf.toString("utf8").split(/\r?\n/);
          const matchedIndexes = [];
          for (let i = 0; i < lines.length; i++) {
            const hit = regex ? regex.test(lines[i]) : (ignoreCase ? lines[i].toLowerCase().includes(needle) : lines[i].includes(needle));
            if (hit) matchedIndexes.push(i);
          }
          if (!matchedIndexes.length) continue;
          const emitted = new Set();
          for (const idx of matchedIndexes) {
            if (matchCount >= effectiveLimit) { matchLimitReached = true; break; }
            matchCount++;
            const start = Math.max(0, idx - contextValue);
            const end = Math.min(lines.length - 1, idx + contextValue);
            for (let row = start; row <= end; row++) {
              if (emitted.has(row)) continue;
              emitted.add(row);
              const isMatch = row === idx || matchedIndexes.includes(row);
              const { text: truncatedText, wasTruncated } = truncateLine(lines[row]);
              if (wasTruncated) linesTruncated = true;
              outputLines.push(isMatch ? `${file.relPosix}:${row + 1}: ${truncatedText}` : `${file.relPosix}-${row + 1}- ${truncatedText}`);
            }
          }
          if (matchLimitReached) break;
        }
        return formatResult(outputLines, matchCount, matchLimitReached, linesTruncated);
      },
    });

    // User `!` commands execute on the remote workspace.
    pi.on("user_bash", (_event, ctx) => ({
      operations: {
        exec: (command, cwd, opts) => remoteShellExec("bash", command, cwd, opts, ctx),
      },
    }));

    // Tell the model its real remote location (host:remotePath) instead of the local mirror path.
    pi.on("before_agent_start", async event => {
      const platform = configuredPlatform || "linux";
      const remoteRoot = normalizeRemotePath(rawRemotePath, platform);
      const label = `${host}:${remoteRoot}`;
      const targetLine = `Current working directory: ${localCwd}`;
      const replacement = `Current working directory: ${remoteRoot} (remote workspace ${label}, platform: ${platform})`;
      const prompt = String(event.systemPrompt || "");
      const modified = prompt.includes(targetLine)
        ? prompt.replace(targetLine, replacement)
        : `${prompt}\n\n${replacement}`;
      return { systemPrompt: modified };
    });
  };
}
