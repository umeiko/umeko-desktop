import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

// The dialog's QML library is plain JS once its pragma is removed.
const source = readFileSync(new URL('../app/qml/approval-view.js', import.meta.url), 'utf8').replace('.pragma library', '');
const context = vm.createContext({});
vm.runInContext(source, context);
const present = request => JSON.parse(JSON.stringify(context.present(request)));

const shell = {
  command: "Set-Content ../notes.txt -Value '便笺。'", description: 'Write text to ../notes.txt',
  justification: '../notes.txt 超出当前工作区范围，请批准这一次性命令。', sandbox_permissions: 'danger-full-access',
};
const dshRequest = (title, rawInput, extra = {}) => ({
  type: 'ui_request', backend: 'dsh', id: 'p1', method: 'confirm', title: 'DeepSeek Harness 请求授权',
  detail: [title, JSON.stringify(rawInput)].join('\n'), toolTitle: title, rawInput, ...extra,
});

test('dsh shell approval shows command, explanation and a plain permission line', () => {
  const request = dshRequest('pwsh', shell);
  assert.deepEqual(present(request), {
    structured: true, raw: request.detail, action: '运行命令', description: 'Write text to ../notes.txt',
    sections: [
      { label: '执行的命令', text: shell.command, mono: true },
      { label: '模型说明', text: shell.justification, mono: false },
    ],
    permissionLevel: 'danger-full-access', permission: '需要完全访问权限（超出当前工作目录）', permissionValue: '',
  });
});

test('dsh file write shows the path and content; unknown levels stay verbatim', () => {
  const view = present(dshRequest('write', { file_path: '../out/summary.txt', content: 'x'.repeat(1300), sandbox_permissions: 'custom-level' }));
  assert.equal(view.action, '写入文件');
  assert.deepEqual(view.sections.map(row => row.label), ['目标文件', '写入内容']);
  assert.equal(view.sections[0].text, '../out/summary.txt');
  assert.ok(view.sections[1].text.endsWith('\n…') && view.sections[1].text.length < 1300);
  assert.equal(view.permission, '');
  assert.equal(view.permissionValue, 'custom-level');
});

test('ACP tool kind and explanation are used when the title is a sentence', () => {
  const view = present(dshRequest('Run the formatter', { command: ['npm', 'run', 'format'] },
    { toolKind: 'execute', toolContent: 'Umeko 每次询问：执行工具 pwsh 前需要本次授权。' }));
  assert.equal(view.action, '运行命令');
  assert.deepEqual(view.sections, [
    { label: '执行的命令', text: 'npm run format', mono: true },
    { label: '说明', text: 'Umeko 每次询问：执行工具 pwsh 前需要本次授权。', mono: false },
  ]);
});

test('requests from older bridges are parsed from detail; unparseable ones keep the raw view', () => {
  const legacy = present({ backend: 'dsh', method: 'confirm', detail: `pwsh\n${JSON.stringify(shell)}` });
  assert.equal(legacy.structured, true);
  assert.equal(legacy.sections[0].text, shell.command);
  assert.deepEqual(present({ backend: 'dsh', method: 'confirm', detail: 'Write notes file\nCached write explanation' }), { structured: false });
});

test('Pi tool approvals split reason and command; other Pi dialogs are unchanged', () => {
  assert.deepEqual(present({ method: 'confirm', detail: '原因：递归删除的目标是 Umeko 数据。\n\n原始命令：\nrm -rf ~/.umeko' }).sections, [
    { label: '原因', text: '递归删除的目标是 Umeko 数据。', mono: false },
    { label: '原始命令', text: 'rm -rf ~/.umeko', mono: true },
  ]);
  assert.deepEqual(present({ method: 'confirm', detail: 'Reason: Writes outside.\n\nOriginal path/input:\n../x' }).sections, [
    { label: '原因', text: 'Writes outside.', mono: false },
    { label: 'Original path/input', text: '../x', mono: true },
  ]);
  assert.deepEqual(present({ method: 'confirm', detail: '插件 demo 想要读取剪贴板内容。' }), { structured: false });
  assert.deepEqual(present({ method: 'input', detail: '原因：x\n\n原始命令：\ny' }), { structured: false });
  assert.deepEqual(present({}), { structured: false });
});
