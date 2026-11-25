/**
 * Read-only OpenSSH ~/.ssh/config alias discovery (Host blocks + Include expansion).
 * Adapted from dsh-remote 1.4.1 (lib/sshconfig.js), Copyright (c) 2026 dsh-remote contributors (MIT).
 * Full license: ../licenses/dsh-remote-MIT.txt.
 * Umeko never writes ~/.ssh/config or opens private key material.
 */
import { readFileSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";

const VALID_ALIAS = /^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$/;
const KNOWN_PARAMS = new Set(["hostname", "user", "port", "proxyjump", "proxycommand"]);

export function sshConfigPath() {
  const override = process.env.UMEKO_SSH_CONFIG;
  if (override && String(override).trim()) return path.resolve(String(override).trim());
  return path.join(homedir(), ".ssh", "config");
}

function sshConfigDir(filePath) {
  const override = process.env.UMEKO_SSH_CONFIG;
  if (override && String(override).trim()) return path.dirname(path.resolve(String(override).trim()));
  return filePath ? path.dirname(path.resolve(filePath)) : path.join(homedir(), ".ssh");
}

const stripQuotes = s => String(s || "").replace(/^"(.*)"$/s, "$1").replace(/^'(.*)'$/s, "$1");

export function splitValue(value) {
  return (String(value || "").match(/"[^"]*"|'[^']*'|\S+/g) || [])
    .map(stripQuotes)
    .filter(token => token !== "");
}

function globRegex(pattern) {
  let re = "";
  for (const ch of String(pattern || "")) {
    if (ch === "*") re += ".*";
    else if (ch === "?") re += ".";
    else re += ch.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
  return new RegExp(`^${re}$`, "i");
}

function globFiles(target, listDir) {
  const base = path.basename(target);
  if (!/[*?]/.test(base)) return [target];
  const dir = path.dirname(target);
  let entries;
  try { entries = listDir(dir); } catch { return []; }
  const re = globRegex(base);
  return entries.filter(name => re.test(name)).map(name => path.join(dir, name));
}

function expandIncludePath(pattern, callerDir, baseDir, listDir) {
  const raw = stripQuotes(pattern);
  if (!raw) return [];
  if (path.isAbsolute(raw)) return globFiles(raw, listDir).sort();
  if (raw.startsWith("~")) return globFiles(path.join(homedir(), raw.replace(/^~[\\/]?/, "")), listDir).sort();
  const primary = globFiles(path.join(baseDir, raw), listDir);
  if (primary.length) return primary.sort();
  if (callerDir && path.resolve(callerDir) !== path.resolve(baseDir)) {
    return globFiles(path.join(callerDir, raw), listDir).sort();
  }
  return [];
}

function joinContinuations(text) {
  const lines = [];
  let pending = "";
  for (const raw of String(text).split(/\r?\n/)) {
    const line = pending + raw;
    if (/\\\s*$/.test(line) && !/\\\\\s*$/.test(line)) {
      pending = line.replace(/\\\s*$/, " ") + " ";
      continue;
    }
    pending = "";
    lines.push(line);
  }
  if (pending) lines.push(pending);
  return lines;
}

function matchInclude(line) {
  const match = String(line).match(/^\s*include\s+(.+?)\s*$/i);
  return match ? splitValue(match[1]) : null;
}

function expandFile(file, state) {
  let text;
  try { text = state.readFile(file); } catch { return ""; }
  if (typeof text !== "string") return "";
  if (state.depth >= state.maxDepth) return text;
  const out = [];
  for (const line of joinContinuations(text)) {
    const patterns = matchInclude(line);
    if (!patterns) { out.push(line); continue; }
    for (const pattern of patterns) {
      for (const included of expandIncludePath(pattern, path.dirname(file), state.baseDir, state.listDir)) {
        const key = path.resolve(included);
        if (state.seen.has(key)) continue;
        state.seen.add(key);
        const child = expandFile(included, { ...state, depth: state.depth + 1 });
        if (child.trim()) out.push(child);
      }
    }
  }
  return out.join("\n");
}

export function loadSshConfigText(filePath = sshConfigPath(), io = {}) {
  const readFile = io.readFile || (p => readFileSync(p, "utf8"));
  const listDir = io.listDir || (p => readdirSync(p));
  const baseDir = io.baseDir || sshConfigDir(filePath);
  return expandFile(filePath, { readFile, listDir, baseDir, maxDepth: io.maxDepth ?? 3, depth: 0, seen: new Set([path.resolve(filePath)]) });
}

export function parseHostBlocks(text) {
  const blocks = [];
  let current = null;
  for (const raw of joinContinuations(text)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const match = line.match(/^(\S+)(?:\s*=\s*|\s+)(.*)$/);
    if (!match) continue;
    const key = match[1].toLowerCase();
    const value = match[2].trim();
    if (key === "host") {
      current = { patterns: splitValue(value), values: {} };
      blocks.push(current);
      continue;
    }
    if (key === "match") {
      current = null;
      continue;
    }
    if (!current || !KNOWN_PARAMS.has(key)) continue;
    if (Object.prototype.hasOwnProperty.call(current.values, key)) continue;
    current.values[key] = key === "port" ? (Number(value) || value) : stripQuotes(value);
  }
  return blocks;
}

export function hostBlockMatches(patterns, name) {
  const list = Array.isArray(patterns) ? patterns : splitValue(patterns);
  const negative = list.filter(p => p.startsWith("!")).map(p => p.slice(1));
  const positive = list.filter(p => !p.startsWith("!"));
  if (negative.some(p => globRegex(p).test(String(name || "")))) return false;
  return positive.some(p => globRegex(p).test(String(name || "")));
}

export function resolveSshHost(alias, text) {
  const name = String(alias || "").trim();
  const out = { alias: name, hostName: "", user: "", port: 0, proxyJump: "", proxyCommand: "" };
  if (!name) return out;
  for (const block of parseHostBlocks(text)) {
    if (!hostBlockMatches(block.patterns, name)) continue;
    for (const [key, value] of Object.entries(block.values)) {
      if (key === "hostname" && !out.hostName) out.hostName = String(value);
      else if (key === "user" && !out.user) out.user = String(value);
      else if (key === "port" && !out.port) out.port = Number(value) || 0;
      else if (key === "proxyjump" && !out.proxyJump) out.proxyJump = String(value);
      else if (key === "proxycommand" && !out.proxyCommand) out.proxyCommand = String(value);
    }
  }
  if (!out.hostName) out.hostName = name;
  return out;
}

/** Return concrete (non-wildcard, safe) Host aliases defined in ~/.ssh/config. */
export function listSshConfigHosts(opts = {}) {
  const text = opts.text !== undefined ? String(opts.text) : loadSshConfigText(opts.file || sshConfigPath(), opts.io || {});
  const seen = new Set();
  const out = [];
  for (const block of parseHostBlocks(text)) {
    for (const pattern of block.patterns) {
      if (!pattern || /[*?!]/.test(pattern) || !VALID_ALIAS.test(pattern)) continue;
      if (seen.has(pattern)) continue;
      seen.add(pattern);
      out.push(resolveSshHost(pattern, text));
    }
  }
  return out.sort((a, b) => (a.alias < b.alias ? -1 : a.alias > b.alias ? 1 : 0));
}
