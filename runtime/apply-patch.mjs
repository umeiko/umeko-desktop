// Adapted from openai/codex, rust-v0.172.0, codex-rs/apply-patch/src/
// parser.rs, streaming_parser.rs, seek_sequence.rs, file_update.rs, text_file.rs
// and lib.rs. Apache-2.0. See ../licenses/codex-apply-patch-APACHE.txt.
import fs from 'node:fs';
import path from 'node:path';

export const APPLY_PATCH = 'apply_patch';
const approvedPatches = new WeakMap();
const begin = '*** Begin Patch';
const end = '*** End Patch';
const eof = '*** End of File';
const move = '*** Move to: ';
const fileHeader = /^\*\*\* (Add|Delete|Update) File: (.+)$/u;

const newChunk = context => ({context, old: [], new: [], anchors: [], eof: false});
const emptyChunk = chunk => chunk && !chunk.old.length && !chunk.new.length;

export function parsePatch(patch) {
  if (typeof patch !== 'string') throw new Error('Provide the patch as a string in the patch argument.');
  let lines = patch.trim().split(/\r?\n/u);
  if (lines.length >= 4 && ['<<EOF', "<<'EOF'", '<<"EOF"'].includes(lines[0]) && lines.at(-1).endsWith('EOF')) {
    lines = lines.slice(1, -1);
  }
  if (lines[0].trim() !== begin) throw new Error(`The first line of the patch must be '${begin}'.`);
  if (lines.at(-1).trim() !== end) throw new Error(`The last line of the patch must be '${end}'.`);

  const hunks = [];
  let hunk;
  let chunk;
  for (let index = 1; index < lines.length; index++) {
    const line = lines[index];
    const marker = hunk?.kind === 'update' ? line.trimEnd() : line.trim();
    const header = marker.match(fileHeader);
    const invalid = message => new Error(`Invalid patch at line ${index + 1}: ${message}`);
    if (header || index === lines.length - 1) {
      if (hunk?.kind === 'update' && (!chunk || emptyChunk(chunk))) {
        throw invalid(`Update for '${hunk.path}' is empty. Include a context, added, or removed line.`);
      }
      if (!header) break;
      hunk = {kind: header[1].toLowerCase(), path: header[2], chunks: [], added: []};
      hunks.push(hunk);
      chunk = undefined;
      continue;
    }
    if (hunk?.kind === 'add' && line.startsWith('+')) {
      hunk.added.push(line.slice(1));
      continue;
    }
    if (hunk?.kind !== 'update') {
      throw invalid("Use '*** Add File: path', '*** Delete File: path', or '*** Update File: path'. Prefix added lines with '+'.");
    }
    if (!chunk && !hunk.destination && marker.startsWith(move)) {
      hunk.destination = marker.slice(move.length);
      continue;
    }
    if (marker === '@@' || marker.startsWith('@@ ')) {
      if (emptyChunk(chunk)) throw invalid('Include change lines before starting another @@ chunk.');
      chunk = newChunk(marker.slice(3) || undefined);
      hunk.chunks.push(chunk);
      continue;
    }
    if (chunk?.eof) {
      if (!marker) continue;
      throw invalid("Use '@@' to start another chunk after '*** End of File'.");
    }
    if (marker === eof && chunk && !emptyChunk(chunk)) {
      chunk.eof = true;
      continue;
    }
    const prefix = line[0] ?? ' ';
    if (![' ', '+', '-'].includes(prefix)) {
      throw invalid("Prefix each change line with ' ' (context), '+' (addition), or '-' (removal).");
    }
    if (!chunk) {
      chunk = newChunk();
      hunk.chunks.push(chunk);
    }
    const text = line.slice(1);
    if (prefix === ' ') chunk.anchors.push([chunk.old.length, chunk.new.length]);
    if (prefix !== '+') chunk.old.push(text);
    if (prefix !== '-') chunk.new.push(text);
  }
  if (!hunks.length) throw new Error('The patch is empty. Include at least one file header.');
  return hunks;
}

function normalizePunctuation(text) {
  return text.trim()
    .replace(/[\u2010-\u2015\u2212]/gu, '-')
    .replace(/[\u2018-\u201b]/gu, "'")
    .replace(/[\u201c-\u201f]/gu, '"')
    .replace(/[\u00a0\u2002-\u200a\u202f\u205f\u3000]/gu, ' ');
}

export function seekSequence(lines, pattern, start = 0, atEnd = false) {
  if (!pattern.length) return start;
  const last = lines.length - pattern.length;
  const first = atEnd ? Math.max(start, last) : start;
  for (const normalize of [text => text, text => text.trimEnd(), text => text.trim(), normalizePunctuation]) {
    const expected = pattern.map(normalize);
    for (let index = first; index <= last; index++) {
      if (expected.every((line, offset) => line === normalize(lines[index + offset]))) return index;
    }
  }
  return -1;
}

function updateContents(contents, hunks, originalPath) {
  const lines = [];
  let ending = '';
  for (const [, text, terminator] of contents.matchAll(/([^\r\n]*)(\r\n|[\r\n]|$)/gu)) {
    if (!text && !terminator) break;
    ending ||= terminator;
    lines.push({text, terminator});
  }
  ending ||= '\n';
  const texts = lines.map(line => line.text);
  const replacements = [];
  let cursor = 0;
  for (const chunk of hunks) {
    if (chunk.context !== undefined) {
      const anchor = seekSequence(texts, [chunk.context], cursor);
      if (anchor < 0) throw new Error(`Failed to find context '${chunk.context}' in ${originalPath}. Use a complete existing line after @@.`);
      cursor = anchor + 1;
    }
    let {old: before, new: after} = chunk;
    if (!before.length) {
      replacements.push([lines.length, 0, after]);
      continue;
    }
    let start = seekSequence(texts, before, cursor, chunk.eof);
    if (start < 0 && before.at(-1) === '') {
      before = before.slice(0, -1);
      if (after.at(-1) === '') after = after.slice(0, -1);
      start = seekSequence(texts, before, cursor, chunk.eof);
    }
    if (start < 0) throw new Error(`Failed to find expected lines in ${originalPath}:\n${chunk.old.join('\n')}`);

    // Preserve original whitespace and terminators on context lines.
    let fromOld = 0;
    let fromNew = 0;
    for (const [oldIndex, newIndex] of chunk.anchors) {
      if (oldIndex >= before.length || newIndex >= after.length) break;
      if (oldIndex !== fromOld || newIndex !== fromNew) {
        replacements.push([start + fromOld, oldIndex - fromOld, after.slice(fromNew, newIndex)]);
      }
      fromOld = oldIndex + 1;
      fromNew = newIndex + 1;
    }
    if (fromOld !== before.length || fromNew !== after.length) {
      replacements.push([start + fromOld, before.length - fromOld, after.slice(fromNew)]);
    }
    cursor = start + before.length;
  }

  replacements.sort(([a], [b]) => a - b);
  const result = [];
  cursor = 0;
  for (const [start, length, inserted] of replacements) {
    for (; cursor < start; cursor++) result.push(lines[cursor].text + (lines[cursor].terminator || ending));
    for (const text of inserted) result.push(text + ending);
    cursor = start + length;
  }
  for (; cursor < lines.length; cursor++) result.push(lines[cursor].text + (lines[cursor].terminator || ending));
  return result.join('');
}

function inspect(file) {
  return fs.lstatSync(file, {throwIfNoEntry: false});
}

function canonicalPath(file) {
  const info = inspect(file);
  if (info) return fs.realpathSync.native(file);
  const parent = path.dirname(file);
  return parent === file ? file : path.join(canonicalPath(parent), path.basename(file));
}

export function resolvePatchPaths(hunks, cwd) {
  const targets = new Map();
  for (const name of hunks.flatMap(hunk => hunk.destination ? [hunk.path, hunk.destination] : [hunk.path])) {
    if (targets.has(name)) continue;
    const absolute = path.resolve(cwd, name);
    targets.set(name, {absolute, canonical: canonicalPath(absolute)});
  }
  return targets;
}

export function preparePatchPermission(input, cwd) {
  const hunks = parsePatch(input.patch);
  const targets = resolvePatchPaths(hunks, cwd);
  const patch = input.patch;
  return {
    targets,
    approve: () => approvedPatches.set(input, {patch, cwd, hunks, targets}),
  };
}

export function createApplyPatchExtension(isEnabled) {
  return pi => {
    pi.on('model_select', ({model}) => {
      if (!pi.getAllTools().some(tool => tool.name === APPLY_PATCH)) return;
      const active = pi.getActiveTools().filter(name => name !== APPLY_PATCH);
      if (isEnabled(model)) active.push(APPLY_PATCH);
      pi.setActiveTools(active);
    });
    pi.registerTool({
      name: APPLY_PATCH, label: 'Apply patch', exposure: 'model-only', defaultActive: false,
      executionMode: 'sequential', annotations: {readOnlyHint: false, destructiveHint: true},
      description: `Apply one patch to add, update, move or delete one or more files. Send the raw patch text in the patch string.
Start with *** Begin Patch and end with *** End Patch. Each file starts with *** Add File: path, *** Delete File: path, or *** Update File: path.
Prefix each added line with +. In an update optionally put *** Move to: path immediately below the file header. Start a chunk with @@ or @@ followed by a complete existing line to start matching after that line. Follow with lines prefixed by a space for unchanged context, - for removals, or + for additions. Use more context or an @@ anchor for repeated lines. *** End of File limits matching to the file's end. Use workspace-relative paths when possible. If any file fails, the patch is rolled back.`,
      parameters: {type: 'object', properties: {patch: {type: 'string'}}, required: ['patch'], additionalProperties: false},
      async execute(_id, input, signal, _update, ctx) {
        signal?.throwIfAborted();
        if (!isEnabled(ctx.model)) throw new Error('apply_patch is disabled for this model.');
        const approved = approvedPatches.get(input);
        approvedPatches.delete(input);
        if (!approved || approved.patch !== input.patch || approved.cwd !== ctx.cwd) {
          throw new Error('The patch did not pass the write-permission check.');
        }
        const {files, warnings} = applyPatch(approved.hunks, approved.targets);
        const labels = {added: 'A', modified: 'M', deleted: 'D'};
        const text = files.length ? ['Success. Updated the following files:',
          ...files.map(file => `${labels[file.kind]} ${file.path}`)] : ['Success. No files changed.'];
        if (warnings.length) text.push('Temporary patch files could not be removed:', ...warnings);
        return {content: [{type: 'text', text: text.join('\n')}], details: {patchFiles: files}};
      },
    });
  };
}

function planChanges(hunks, targets) {
  const files = new Map();
  function file(name) {
    const {absolute, canonical} = targets.get(name);
    const key = process.platform === 'win32' ? canonical.toLowerCase() : canonical;
    if (inspect(absolute)?.isSymbolicLink()) throw new Error(`Use the regular file path instead of the symbolic link: ${name}`);
    if (!files.has(key)) {
      const stat = inspect(canonical);
      if (stat && !stat.isFile()) throw new Error(`Expected a regular file: ${name}`);
      files.set(key, {name, file: canonical, stat, exists: !!stat, content: undefined, mode: stat?.mode});
    }
    return files.get(key);
  }

  for (const hunk of hunks) {
    const source = file(hunk.path);
    if (hunk.kind === 'add') {
      source.exists = true;
      source.content = Buffer.from(hunk.added.map(line => line + '\n').join(''));
      continue;
    }
    if (!source.exists) throw new Error(`File to ${hunk.kind} does not exist: ${hunk.path}`);
    if (hunk.kind === 'delete') {
      source.exists = false;
      source.content = undefined;
      continue;
    }
    let original;
    try {
      original = new TextDecoder('utf-8', {fatal: true, ignoreBOM: true}).decode(source.content ?? fs.readFileSync(source.file));
    } catch (error) {
      throw new Error(`Cannot read ${hunk.path} as UTF-8: ${error.message}`, {cause: error});
    }
    const destination = hunk.destination ? file(hunk.destination) : source;
    if (destination !== source) {
      source.exists = false;
      source.content = undefined;
    }
    destination.exists = true;
    destination.mode ??= source.mode;
    destination.content = Buffer.from(updateContents(original, hunk.chunks, hunk.path));
  }
  return [...files.values()].filter(item => item.exists ? item.content !== undefined : item.stat);
}

function commitChanges(changes) {
  const directories = [];
  const staged = [];
  function ensureParent(parent) {
    const stat = inspect(parent);
    if (stat?.isDirectory()) return;
    if (stat) throw new Error(`Expected a directory: ${parent}`);
    ensureParent(path.dirname(parent));
    fs.mkdirSync(parent);
    directories.push(parent);
  }

  try {
    for (const change of changes) {
      if (process.platform === 'win32' && change.stat) fs.accessSync(change.file, fs.constants.W_OK);
      const parent = path.dirname(change.file);
      ensureParent(parent);
      const directory = fs.mkdtempSync(path.join(parent, '.umeko-patch-'));
      const entry = {change, directory, original: path.join(directory, 'original'), next: path.join(directory, 'next')};
      staged.push(entry);
      if (change.exists) {
        fs.writeFileSync(entry.next, change.content, {flag: 'wx'});
        if (change.mode !== undefined) fs.chmodSync(entry.next, change.mode & 0o777);
      }
    }
    for (const entry of staged) {
      const {change} = entry;
      const current = inspect(change.file);
      if (Boolean(current) !== Boolean(change.stat) || (current &&
          ['dev', 'ino', 'mode', 'size', 'mtimeMs', 'ctimeMs'].some(key => current[key] !== change.stat[key]))) {
        throw new Error(`File changed while preparing the patch: ${change.name}. Read it again and retry.`);
      }
      if (change.stat) {
        fs.renameSync(change.file, entry.original);
        entry.backedUp = true;
      }
      if (change.exists) {
        fs.renameSync(entry.next, change.file);
        entry.installed = true;
      }
    }
  } catch (error) {
    const rollbackErrors = [];
    for (const entry of staged.reverse()) {
      try {
        if (entry.installed) fs.unlinkSync(entry.change.file);
        if (entry.backedUp) fs.renameSync(entry.original, entry.change.file);
        cleanStage(entry);
      } catch (rollbackError) {
        rollbackErrors.push(`${entry.change.name}: ${rollbackError.message}`);
      }
    }
    for (const directory of directories.reverse()) {
      try { fs.rmdirSync(directory); }
      catch (rollbackError) { rollbackErrors.push(rollbackError.message); }
    }
    if (rollbackErrors.length) throw new Error(`${error.message}\nRollback needs attention:\n${rollbackErrors.join('\n')}`, {cause: error});
    throw error;
  }
  const warnings = [];
  for (const entry of staged) {
    try { cleanStage(entry); }
    catch (error) { warnings.push(error.message); }
  }
  return warnings;
}

function cleanStage(entry) {
  for (const file of [entry.original, entry.next]) {
    if (inspect(file)) fs.unlinkSync(file);
  }
  fs.rmdirSync(entry.directory);
}

export function applyPatch(hunks, targets) {
  const changes = planChanges(hunks, targets);
  const warnings = commitChanges(changes);
  return {files: changes.map(change => ({path: change.name, kind: change.exists ? change.stat ? 'modified' : 'added' : 'deleted'})), warnings};
}
