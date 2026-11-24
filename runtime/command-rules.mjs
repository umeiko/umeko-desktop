/**
 * Command prefix matching and persistent approvals adapted from OpenAI Codex
 * rust-v0.172.0, codex-rs/execpolicy/src/{rule,policy,amend}.rs and
 * codex-rs/core/src/exec_policy.rs. Notice: ../licenses/codex-execpolicy.txt.
 */
import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

const FILE = 'command-rules.json';
const scopes = ['user', 'workspace'];
const shells = ['bash', 'powershell'];
const rank = new Map([['allow', 0], ['ask', 1], ['forbid', 2]]);

function ruleFile(scope, {dataDir, workspace}) {
  if (scope === 'user') return dataDir ? path.join(dataDir, FILE) : null;
  if (scope === 'workspace') return workspace ? path.join(workspace, '.umeko', FILE) : null;
  throw new Error('Rule scope must be user or workspace.');
}

function ruleEntry({pattern, decision, shell}) {
  if (!Array.isArray(pattern) || !pattern[0]?.trim?.() ||
      pattern.some(token => typeof token !== 'string' || token.includes('\0')))
    throw new Error('Rule pattern must be a nonempty array of command tokens.');
  if (!rank.has(decision)) throw new Error('Rule decision must be allow, ask or forbid.');
  if (shell !== undefined && !shells.includes(shell)) throw new Error('Rule shell must be bash or powershell.');
  return shell === undefined ? {pattern, decision} : {pattern, decision, shell};
}

function readRules(file) {
  if (!file) return [];
  try {
    const data = JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
    if (!Array.isArray(data)) throw new Error('Expected an array of prefix rules.');
    return data.map((item, index) => {
      try { return ruleEntry(item); }
      catch (error) { throw new Error(`Rule ${index + 1}: ${error.message}`); }
    });
  } catch (error) {
    if (error.code === 'ENOENT') return [];
    throw new Error(`${file}: ${error.message}`, {cause: error});
  }
}

export function listCommandRules(context, scope) {
  return (scope === undefined ? scopes : [scope]).flatMap(name =>
    readRules(ruleFile(name, context)).map(rule => ({scope: name, ...rule})),
  );
}

export function changeCommandRule(action, {scope, ...input}, context) {
  const rule = ruleEntry(input);
  const file = ruleFile(scope, context);
  if (!file) throw new Error(`The ${scope} rule file is unavailable in this session.`);
  if (action === 'remove' && !fs.existsSync(file)) return {changed: false, scope, ...rule};
  fs.mkdirSync(path.dirname(file), {recursive: true});
  // Separate bridge processes can write the same profile. Lock the read/modify/write
  // and rename into place so readers always see a whole policy file.
  const lock = `${file}.lock`;
  const fd = fs.openSync(lock, 'wx');
  const temp = `${file}.${randomUUID()}.tmp`;
  try {
    const rules = readRules(file);
    const same = entry => JSON.stringify(entry) === JSON.stringify(rule);
    const exists = rules.some(same);
    const changed = action === 'add' ? !exists : exists;
    if (changed) {
      const next = action === 'add' ? [...rules, rule] : rules.filter(entry => !same(entry));
      fs.writeFileSync(temp, `${JSON.stringify(next, null, 2)}\n`, {flag: 'wx'});
      fs.renameSync(temp, file);
    }
    return {changed, scope, ...rule};
  } finally {
    fs.closeSync(fd);
    fs.unlinkSync(lock);
    fs.rmSync(temp, {force: true});
  }
}

function matchesPrefix(pattern, tokens, shell) {
  if (pattern.length > tokens.length) return false;
  return pattern.every((token, index) => shell === 'powershell' && index === 0
    ? token.toLowerCase() === tokens[index].toLowerCase()
    : token === tokens[index]);
}

export function evaluateCommandRules({parts, plain}, rules, shell, mode) {
  const applicable = rules.filter(rule => !rule.shell || rule.shell === shell);
  let strictest;
  let allAllowed = plain && parts.length > 0;
  for (const tokens of parts) {
    let allowed = false;
    for (const rule of applicable) {
      if (!matchesPrefix(rule.pattern, tokens, shell)) continue;
      if (!strictest || rank.get(rule.decision) > rank.get(strictest.decision)) strictest = rule;
      if (rule.decision === 'allow') allowed = true;
    }
    allAllowed &&= allowed;
  }
  if (strictest?.decision === 'forbid' || strictest?.decision === 'ask') return strictest;
  if (allAllowed) return {decision: 'allow'};
  if (mode === 'ask') return {decision: 'ask', remember: plain && parts.length === 1 ? parts[0] : undefined};
  // A script whose executable tokens cannot all be determined needs a person
  // to review it when a restriction could apply to one of those tokens.
  if (!plain && applicable.some(rule => rule.decision !== 'allow')) return {decision: 'ask'};
  return null;
}

export function isCommandRuleOperation(operation) {
  return ['command_rules.list', 'command_rules.add', 'command_rules.remove'].includes(operation);
}

export async function commandRuleOperation(operation, args, context, confirm) {
  if (operation === 'command_rules.list') return {rules: listCommandRules(context, args.scope || undefined)};
  if (context.readOnly) throw new Error('Command rules are read-only in this session.');
  const action = operation === 'command_rules.add' ? 'add' : 'remove';
  const rule = ruleEntry({...args, shell: args.shell === '' ? undefined : args.shell});
  if (!ruleFile(args.scope, context)) throw new Error(`The ${args.scope} rule file is unavailable in this session.`);
  if (action === 'add' && args.scope === 'workspace' && rule.decision === 'allow' && context.workspaceTrusted === false)
    throw new Error('Workspace allow rules require a trusted workspace.');
  const relaxes = action === 'add' ? rule.decision === 'allow' : rule.decision !== 'allow';
  if (relaxes) {
    const zh = context.language === 'zh';
    const title = zh ? '批准命令规则变更' : 'Approve command rule change';
    if (typeof confirm !== 'function' || await confirm(title, JSON.stringify({action, scope: args.scope, ...rule}, null, 2)) !== true)
      throw new Error(zh ? '未批准命令规则变更。' : 'Command rule change was not approved.');
  }
  return changeCommandRule(action, {scope: args.scope, ...rule}, context);
}
