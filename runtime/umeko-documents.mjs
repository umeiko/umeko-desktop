// Instance-local, on-demand documentation. Model names never enter the prompt.
import { mkdirSync, readFileSync, readdirSync, renameSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';

const bundled = fileURLToPath(new URL('./umeko-docs/', import.meta.url));
const cell = value => String(value ?? '').replace(/[\r\n]/g, ' ').replaceAll('|', '\\|').replaceAll('`', '\\`');
export function availableModels(models = []) {
  return [...new Map(models.filter(row => typeof row.id === 'string' && row.id).map(row =>
    [row.id, { model: 'umeko/' + row.id, id: row.id, provider: 'umeko',
      displayProvider: row.owned_by || 'Umeko', contextWindow: row.contextWindow || 128000,
      vision: row.input?.includes('image') || false }])).values()].sort((a,b) => a.model.localeCompare(b.model));
}
export function modelTable(models) {
  const rows = availableModels(models);
  return rows.length ? [
    '| 直接填入 subagent.model 的调用名称 | 界面供应商 | 上下文窗口 | 图片输入 |',
    '| --- | --- | --- | --- |',
    ...rows.map(row => '| `' + cell(row.model) + '` | ' + cell(row.displayProvider) + ' | ' + row.contextWindow + ' | ' + (row.vision ? '支持' : '不支持') + ' |'),
    '', '调用示例：`' + JSON.stringify({prompt:'检查实现并报告结果',model:rows[0].model}) + '`'
  ].join('\n') : '当前实例尚无可用模型。先在 Umeko 添加供应商并配置模型，再调用 config_umeko 的 models.list。';
}
export function prepareDocumentation({ directory, models = [] }) {
  const target = resolve(directory);
  if (target === resolve(bundled)) throw new Error('Generated docs must use the current user profile');
  mkdirSync(target, { recursive: true });
  for (const name of readdirSync(bundled).filter(name => name.endsWith('.md'))) {
    let text = readFileSync(join(bundled, name), 'utf8');
    if (name === 'delegate-subagents.md') text = text.replace('<!-- UMEKO_AVAILABLE_MODELS -->', modelTable(models));
    const temporary = join(target, '.' + name + '.' + randomUUID() + '.tmp');
    writeFileSync(temporary, text, { mode: 0o600 });
    renameSync(temporary, join(target, name));
  }
  return { docsRoot: target, entry: join(target, 'README.md') };
}
