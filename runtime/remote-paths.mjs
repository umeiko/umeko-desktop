/**
 * Pure remote path helpers supporting both POSIX and Windows remote platforms.
 * Adapted from dsh-remote 1.4.1 (lib/paths.js), Copyright (c) 2026 dsh-remote contributors (MIT).
 * Full license: ../licenses/dsh-remote-MIT.txt.
 */

export function isWindowsRemotePath(value) {
  return /^(?:[a-zA-Z]:(?:[\\/]|$)|\\\\)/.test(String(value || "").trim());
}

export function normalizeRemotePath(input, platform) {
  let s = String(input ?? "").trim();
  if (!s) return platform === "windows" ? "" : "/";
  if (platform === "windows") {
    const slashDrive = s.match(/^\/([a-zA-Z]):(?:\/(.*))?$/s);
    if (slashDrive) s = `${slashDrive[1].toUpperCase()}:\\${(slashDrive[2] || "").replace(/\//g, "\\")}`;
  }
  // Windows UNC: \\server\share\...
  const unc = s.match(/^(\\\\[^\\]+(?:\\[^\\]+)?)(?:\\|$)(.*)$/s);
  if (unc) {
    const [, prefix, rest] = unc;
    const parts = [];
    for (const seg of rest.split(/[\\/]+/)) {
      if (seg === "" || seg === ".") continue;
      if (seg === "..") { parts.pop(); continue; }
      parts.push(seg);
    }
    return parts.length ? `${prefix}\\${parts.join("\\")}` : prefix;
  }
  // Windows drive: X:\... or X:/...
  const drive = s.match(/^([a-zA-Z]:)(?:[\\/]|$)(.*)$/s);
  if (drive) {
    const prefix = drive[1].toUpperCase();
    const parts = [];
    for (const seg of drive[2].split(/[\\/]+/)) {
      if (seg === "" || seg === ".") continue;
      if (seg === "..") { parts.pop(); continue; }
      parts.push(seg);
    }
    return `${prefix}\\${parts.join("\\")}`;
  }
  // POSIX: /a/b/c
  const parts = [];
  for (const seg of s.replace(/\\/g, "/").split("/")) {
    if (seg === "" || seg === ".") continue;
    if (seg === "..") { parts.pop(); continue; }
    parts.push(seg);
  }
  return "/" + parts.join("/");
}

export function joinRemotePath(dir, name, platform) {
  const d = String(dir ?? "");
  const n = String(name ?? "");
  if (!d) return n;
  if (!n) return d;
  if (d.endsWith("/") || d.endsWith("\\")) return d + n;
  const sep = platform === "windows" || d.includes("\\") || /^[a-zA-Z]:/.test(d) ? "\\" : "/";
  return d + sep + n;
}

export function joinRemoteRel(base, rel, platform) {
  let out = base;
  for (const segment of String(rel || "").split(/[\\/]+/)) {
    if (!segment || segment === ".") continue;
    out = joinRemotePath(out, segment, platform);
  }
  return out;
}

export function remoteDirname(p, platform) {
  const norm = normalizeRemotePath(p, platform);
  if (!norm) return "";
  if (norm === "/") return "/";
  if (/^[a-zA-Z]:\\?$/.test(norm)) return "";
  if (/^\\\\[^\\]+\\[^\\]+$/.test(norm)) return norm;
  const sep = norm.includes("\\") ? "\\" : "/";
  const idx = norm.lastIndexOf(sep);
  if (idx <= 0) {
    const drive = norm.match(/^([a-zA-Z]:)\\/);
    return drive ? `${drive[1]}\\` : sep === "/" && norm.startsWith("/") ? "/" : norm;
  }
  const parent = norm.slice(0, idx);
  if (sep === "\\" && /^[a-zA-Z]:$/.test(parent)) return `${parent}\\`;
  return parent;
}

export function remotePathBase(p) {
  const norm = normalizeRemotePath(p).replace(/[\\/]+$/, "");
  const base = norm.split(/[\\/]/).pop();
  if (!base || /^[a-zA-Z]:$/.test(base)) return "workspace";
  return base;
}

export function relPathUnder(root, p) {
  const canonical = x => {
    const n = normalizeRemotePath(x).replace(/[\\/]+$/, "");
    const m = n.match(/^\/?([a-zA-Z]):(.*)$/s);
    if (m) return { win: true, path: `/${m[1].toLowerCase()}:/${m[2] ? m[2].replace(/\\/g, "/").replace(/^\/+/, "") : ""}` };
    return { win: false, path: n.replace(/\\/g, "/") };
  };
  const r = canonical(root);
  const n = canonical(p);
  const rCmp = r.win ? r.path.toLowerCase() : r.path;
  const nCmp = n.win ? n.path.toLowerCase() : n.path;
  if (nCmp === rCmp) return "";
  const prefix = rCmp === "/" ? "/" : `${rCmp}/`;
  if (nCmp.startsWith(prefix)) return n.path.slice(prefix.length);
  return null;
}

export function nativePathFromUri(value, platform) {
  if (typeof value !== "string" || !value || value.includes("\0")) throw new Error("A valid remote path is required");
  if (!/^file:/i.test(value)) return value;
  const url = new URL(value);
  if (url.protocol !== "file:" || url.search || url.hash) throw new Error("Expected a file URI");
  const pathname = decodeURIComponent(url.pathname);
  if (platform === "windows") {
    if (url.hostname && url.hostname !== "localhost") return `\\\\${url.hostname}${pathname.replaceAll("/", "\\")}`;
    return pathname.replace(/^\/([A-Za-z]:)/, "$1").replaceAll("/", "\\");
  }
  if (url.hostname && url.hostname !== "localhost") throw new Error("Remote Linux file URI must have no host");
  return pathname;
}

export function remotePathToUri(value, platform) {
  if (/^file:/i.test(value)) return value;
  if (platform === "windows") {
    const normalized = String(value).replaceAll("\\", "/");
    if (normalized.startsWith("//")) {
      const [host, ...parts] = normalized.slice(2).split("/");
      return `file://${host}/` + parts.map(encodeURIComponent).join("/");
    }
    return "file:///" + normalized.split("/").map((part, index) => (index === 0 && /^[a-z]:$/i.test(part) ? part : encodeURIComponent(part))).join("/");
  }
  return "file://" + String(value).split("/").map(encodeURIComponent).join("/");
}

/**
 * Resolve a tool's `path` argument against a remote workspace root.
 * Handles empty/relative paths, `~`/`~/...` against remote home, local mirror
 * paths mapped back onto the remote workspace, and remote absolute paths.
 */
export function resolveRemoteWorkspacePath(ws, raw, { mirrorDir = "", platform = "linux", homeDir = "" } = {}) {
  const s = String(raw ?? "").trim().replace(/^@/, "");
  if (mirrorDir && ws && s) {
    const mirrorRel = relPathUnder(mirrorDir, s);
    if (mirrorRel !== null) {
      return normalizeRemotePath(mirrorRel ? joinRemoteRel(ws, mirrorRel, platform) : ws, platform);
    }
  }
  if (s === "~" || /^~[\\/]/.test(s)) {
    const baseHome = homeDir ? normalizeRemotePath(homeDir, platform) : ws;
    if (!baseHome) throw new Error("Remote home directory is unavailable");
    const rest = s.slice(2);
    return normalizeRemotePath(rest ? joinRemoteRel(baseHome, rest, platform) : baseHome, platform);
  }
  if (platform === "windows" && /^[a-zA-Z]:(?:$|[^\\/])/.test(s)) {
    if (/^[a-zA-Z]:$/.test(s)) return `${s.toUpperCase()}\\`;
    throw new Error("Drive-relative paths are unsupported; use C:\\path");
  }
  const absolute = s.startsWith("\\\\") || /^[a-zA-Z]:[\\/]/.test(s) || (platform !== "windows" && s.startsWith("/")) || (platform === "windows" && /^\/[a-zA-Z]:\//.test(s));
  if (absolute) return normalizeRemotePath(s, platform);
  const rel = s.replace(/^\.[\\/]/, "");
  if (!rel || rel === ".") return normalizeRemotePath(ws || "", platform);
  return normalizeRemotePath(ws ? joinRemoteRel(ws, rel, platform) : rel, platform);
}
