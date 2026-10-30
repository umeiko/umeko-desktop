import test from 'node:test';
import assert from 'node:assert/strict';
import { performance } from 'node:perf_hooks';
import { classifyCommand, classifyPath, createToolPermissionExtension } from '../runtime/tool-permissions.mjs';

// Known answers reuse the cc-safety-net command/target/wrapper checklist and
// pix-gate executable-position shapes, narrowed to experiments/.../RULES.md.
// All command strings are inert classifier input. This suite never executes them.
const raw = String.raw;
const context = {
  cwd: 'C:\\Users\\tester\\work\\demo',
  home: 'C:\\Users\\tester',
  userProfile: 'C:\\Users\\tester',
  dataDir: 'C:\\Users\\tester\\AppData\\Roaming\\Umeko',
  env: {
    HOME: 'C:\\Users\\tester', USERPROFILE: 'C:\\Users\\tester',
    SystemRoot: 'C:\\Windows', windir: 'C:\\Windows',
    ProgramFiles: 'C:\\Program Files', 'ProgramFiles(x86)': 'C:\\Program Files (x86)',
    ProgramData: 'C:\\ProgramData',
  },
};

// Each family contains different real operations, rather than generated spelling
// variants of one command. Family sizes are exposed by the summary test below.
export const allowFamilies = {
  'workspace deletion': [
    'rm -rf node_modules', 'rm -rf dist', 'rm -rf ./build', 'rm --recursive ./coverage',
    'rm -r ./tmp ./cache', 'rm ./notes.txt', 'rm -f /tmp/demo-output.txt',
    raw`rm -rf "C:\Users\tester\work\demo\node_modules"`,
    raw`Remove-Item .\build -Recurse`, raw`Remove-Item -LiteralPath '.\cache' -Force -Recurse`,
    raw`Remove-Item .\report.txt`, 'rd /s /q out', raw`rmdir /s /q .\dist`,
    raw`del /s /q .\build\*`, raw`erase /s .\cache\*`,
    raw`rm -rf "$HOME/work/demo/dist"`, 'rm -rf /c/Users/tester/work/demo/dist',
    raw`rm -rf "C:\Windows-backup"`, 'rm -rf /etc-backup',
    raw`rm -rf "C:\Users\tester\AppData\Roaming\Umeko-backup"`,
  ],
  'ordinary Git': [
    'git status --short --branch', 'git diff --stat', 'git log -5 --oneline',
    'git reset --hard HEAD', 'git reset --hard origin/main', 'git clean -fd', 'git clean -fdx',
    'git checkout -- src/index.ts', 'git restore --staged README.md',
    'git push origin main', 'git push origin master', 'git push',
    'git push --force origin feature/demo', 'git push -f origin feature/reboot',
    'git push --force-with-lease origin feature/docs', 'git push origin +HEAD:feature/demo',
    'git push --force origin Main', 'git push --force-if-includes origin HEAD:main',
    'git fetch --all --prune', 'git branch -D feature/old',
    'git commit -m "fix kill handling"', 'git commit -m "rm -rf /; shutdown /s"',
    "git commit -m 'document bcdedit /set testsigning on'",
    'git show HEAD:runtime/shutdown.ts', 'git grep -n kill',
  ],
  'package build and execution': [
    'npm install', 'npm ci', 'npm run build', 'npm test -- --run', 'pnpm install --frozen-lockfile',
    'yarn add vite --dev', 'pip install -r requirements.txt', 'uv sync', 'cargo build --release',
    'go test ./...', 'node scripts/build.mjs', 'python scripts/report.py',
    'sudo npm install -g example', 'sudo', 'doas echo hello',
    'irm https://example.invalid/install.ps1 | iex', 'curl https://example.invalid/install.sh | sh',
    'curl -fsSL https://example.invalid/install.sh | bash', 'wget -O ./archive.zip https://example.invalid/a.zip',
    'docker compose up -d', 'taskkill /PID 123 /F', 'pkill -f demo-worker',
  ],
  'search and literal dangerous data': [
    "rg -n 'kill' runtime", 'grep shutdown README.md', 'rg --fixed-strings "rm -rf /" docs',
    "grep -R 'Format-Volume' scripts", 'find . -name "reboot*"',
    'echo taskkill', 'echo shutdown', 'echo rm -rf /', 'echo bcdedit /set testsigning on',
    "echo 'shutdown /s; rm -rf /'", 'echo "netsh advfirewall set allprofiles state off"',
    "printf '%s' 'pkill'", "printf '%s\\n' 'dd of=/dev/sda'",
    "printf '%s' 'chmod -R 777 /etc'", "printf '%s' 'git push -f origin main'",
    "Write-Output 'Remove-Item C:\\ -Recurse'", 'Write-Output shutdown',
    'Write-Output "reg add HKLM\\Software\\Demo"', 'Write-Host "Restart-Computer; Stop-Computer"',
    "Set-Content ./notes.txt 'bcdedit /set testsigning on'", 'cat ./shutdown.log',
    'git commit -m "fix kill"', "git commit -m 'printf pkill; echo taskkill'",
    'echo "$(literal-looking-data)"', "echo '$(shutdown /s)'",
  ],
  'read-only system and near misses': [
    'Get-Disk', 'Get-Volume', 'Get-ComputerInfo', 'Get-Service WinDefend',
    'reg query HKLM\\Software', 'reg export HKLM\\Software ./software.reg',
    'reg add HKCU\\Software\\Demo /v Enabled /d 1',
    "Set-ItemProperty -Path 'HKCU:\\Software\\Demo' -Name Enabled -Value 1",
    'Set-MpPreference -DisableRealtimeMonitoring $false', 'netsh advfirewall show allprofiles',
    'Set-NetFirewallProfile -Enabled $true', 'sc query WinDefend', 'net stop DemoWorker',
    'Stop-Service DemoWorker', 'Set-Service DemoWorker -StartupType Disabled',
    'setx DEMO value', "$env:DEMO='value'", "[Environment]::SetEnvironmentVariable('DEMO','value','User')",
    'chmod -R u+rw ./build', 'chown -R tester:tester ./cache', 'chmod 644 /etc/example.conf',
    'icacls .\\build /grant Administrators:F /T', 'icacls "C:\\Windows"',
    raw`icacls "C:\Users\tester" /grant Administrators:F`,
    'takeown /F .\\build /R', 'dd if=/dev/zero of=./fixture.bin count=1',
    'cat image.bin > ./image-copy.bin', 'printf hello | tee ./output.txt',
    'fdisk -l /dev/sda', 'parted /dev/sda print', 'diskutil list', 'mkfs.ext4 --help',
    'systemctl status firewalld', 'systemctl status reboot', 'systemctl restart demo-worker', 'init 3',
    'echo text > /etc/example.conf', // category 7 is structured edit/write only
  ],
  'literal shell wrappers': [
    "bash -lc 'npm run build'", "sh -c 'rm -rf ./build'", 'cmd /c "rd /s /q out"',
    "powershell -Command 'Remove-Item .\\build -Recurse'",
    'pwsh -c "Write-Output shutdown"', "bash -c 'echo shutdown'",
    "bash -lc 'git push --force origin feature/demo'", "sh -c 'printf pkill'",
    'cmd /c "echo taskkill"', "pwsh -Command 'git reset --hard HEAD'",
    "echo 'bash -c \"rm -rf /\"'", 'node -e "console.log(\'shutdown\')"',
  ],
};

const dangerFamilies = {
  1: [
    'rm -rf /', 'rm --recursive "$HOME"', raw`rm -rf "C:\Windows\Temp"`,
    raw`rd /s /q "C:\"`, 'Remove-Item -LiteralPath "$env:USERPROFILE" -Recurse',
    raw`Remove-Item -Path "C:\ProgramData\Demo" -Rec -Force`,
    raw`RM   -rF   "C:\Users\tester\AppData\Roaming\Umeko"`,
    raw`& "C:\Windows\System32\cmd.exe" /c 'rd /s /q C:\'`,
    "bash -lc 'sudo rm -rf /'", "pwsh -Command 'Remove-Item C:\\Windows -Recurse'",
    'echo prepare && rm -rf /', 'rm /etc/demo --recursive', 'rm -rf ~/.umeko',
    raw`rm -rf c:\users\TESTER`,
  ],
  2: [
    'Format-Volume -DriveLetter D', 'Clear-Disk -Number 1', 'Initialize-Disk -Number 2',
    raw`"C:\Windows\System32\format.com" D: /q`, 'diskpart', 'mkfs.ext4 /dev/sda1',
    'wipefs --all /dev/nvme0n1', 'parted /dev/sda mklabel gpt',
    'dd if=image.bin of=/dev/sda', 'dd if=image.bin of = "/dev/nvme0n1"',
    'cat image.bin > "/dev/mmcblk0"', 'cat image.bin | tee /dev/sdb',
    raw`dd if=image.bin of="\\.\PhysicalDrive0"`,
    "bash -lc 'mkfs.ext4 /dev/vda1'", 'echo prepare; FoRmAt-VoLuMe   -DriveLetter E',
  ],
  3: [
    'shutdown /r /t 0', 'reboot', 'halt', 'poweroff', 'logoff',
    'Stop-Computer -Force', 'Restart-Computer', 'systemctl reboot', 'init 0',
    raw`& "C:\Windows\System32\logoff.exe"`,
    raw`"C:\Windows\System32\shutdown.exe" /s /t 0`,
    'echo done && ReStArT-CoMpUtEr', "bash -lc 'reboot'", 'cmd /c "shutdown /s /t 0"',
    'rundll32 user32.dll,ExitWindowsEx',
  ],
  4: [
    raw`reg add "HKLM\Software\Demo" /v Enabled /d 1`,
    raw`REG   DELETE   HKEY_LOCAL_MACHINE\Software\Demo /f`,
    raw`Set-ItemProperty -Path 'HKLM:\Software\Demo' -Name Enabled -Value 1`,
    'bcdedit /set testsigning on', 'bcdedit /enum',
    raw`"C:\Windows\System32\bcdedit.exe" /deletevalue safeboot`,
    'Set-MpPreference -DisableRealtimeMonitoring $true',
    'Add-MpPreference -ExclusionPath ./build',
    'netsh advfirewall set allprofiles state off', 'Set-NetFirewallProfile -Enabled $false',
    'sc stop WinDefend', 'net stop MpsSvc', 'Stop-Service WinDefend',
    'Set-Service MpsSvc -StartupType Disabled', 'ufw disable', 'systemctl disable firewalld',
    'setx DEMO value /M', "[Environment]::SetEnvironmentVariable('DEMO','value','Machine')",
    "pwsh -Command 'Set-MpPreference -DisableRealtimeMonitoring $true'",
    'echo go && netsh advfirewall set allprofiles state off',
  ],
  5: [
    'chmod -R 777 /etc', 'sudo chown --recursive root:root /', 'chgrp -R root /usr',
    raw`takeown /F "C:\Windows" /R`, raw`icacls "C:\" /grant Administrators:F`,
    raw`icacls "C:\Program Files\Demo" /reset /T`,
    raw`ICACLS   "C:\Windows\Temp"   /deny Users:W`,
    'chmod -R 700 "$HOME"', "bash -lc 'chown -R root:root /etc'",
    raw`cmd /c "icacls C:\ /grant Administrators:F"`,
  ],
  6: [
    'git push --force origin main', 'git push -f origin master',
    'git push --force-with-lease origin refs/heads/main',
    'git push --force-with-lease --force-if-includes origin HEAD:main', 'git push origin +HEAD:refs/heads/master',
    'git push --force origin feature:refs/heads/main', 'git push --force-with-lease=main origin',
    'git push --force --all origin', 'git push --force --mirror origin',
    raw`"C:\Program Files\Git\cmd\git.exe" push -f origin main`,
    "bash -lc 'git push --force origin main'", 'echo prepared && git push -f origin master',
  ],
};

for (const [family, commands] of Object.entries(allowFamilies)) {
  for (const command of commands) {
    test(`auto allows ${family}: ${command}`, () => {
      assert.equal(classifyCommand(command, context), null);
    });
  }
}
for (const [category, commands] of Object.entries(dangerFamilies)) {
  for (const command of commands) {
    test(`category ${category} detects actual operation: ${command}`, () => {
      const result = classifyCommand(command, context);
      assert.equal(result?.category, Number(category), JSON.stringify(result));
      assert.ok(result.reason?.trim(), 'a visible plain-language reason is required');
    });
  }
}

const protectedPaths = [
  raw`C:\Windows\Temp\demo.txt`, 'C:/Windows/Temp/demo.txt', raw`c:\wInDoWs\system32\demo.txt`,
  raw`C:\Program Files\Demo\config.json`, 'C:/Program Files (x86)/Demo/config.json',
  raw`C:\ProgramData\Demo\settings.json`, '/c/Windows/Temp/demo.txt', '/etc/hosts',
  '/usr/local/bin/demo', '/System/Library/demo.plist', '/Library/demo.plist',
  raw`%SystemRoot%\Temp\demo.txt`, raw`$env:windir\Temp\demo.txt`,
  raw`C:\Users\tester\work\demo\..\..\..\..\Windows\Temp\demo.txt`,
];
const ordinaryPaths = [
  './docs/windows-notes.md', './src/index.ts', raw`C:\Users\tester\work\demo\report.md`,
  raw`C:\Windows-backup\notes.txt`, '/etc-backup/hosts', './umeko-config.json',
  raw`C:\Users\tester\AppData\Roaming\Umeko\prefs.json`,
  raw`C:\Users\tester\.ssh\config`, '/home/tester/project/main.ts',
];
for (const path of protectedPaths) {
  test(`category 7 detects structured system target: ${path}`, () => {
    assert.equal(classifyPath(path, context)?.category, 7);
  });
}
for (const path of ordinaryPaths) {
  test(`category 7 allows ordinary structured target: ${path}`, () => {
    assert.equal(classifyPath(path, context), null);
  });
}

test('known-answer dataset has at least 120 distinct ordinary commands and each category has 3 cases', t => {
  const commands = Object.values(allowFamilies).flat();
  assert.ok(commands.length >= 120);
  assert.equal(new Set(commands).size, commands.length);
  for (const rows of Object.values(dangerFamilies)) assert.ok(rows.length >= 3);
  assert.ok(protectedPaths.length >= 3);
  t.diagnostic(JSON.stringify({ ordinary: commands.length, families: Object.fromEntries(
    Object.entries(allowFamilies).map(([key, rows]) => [key, rows.length])),
    dangerousByCategory: Object.fromEntries(Object.entries(dangerFamilies).map(([key, rows]) => [key, rows.length])),
    structuredSystemPaths: protectedPaths.length }));
});

function harness({ mode = 'auto', approve = true, hasUI = true, classify } = {}) {
  let policy = { mode, language: 'en', ...context };
  const prompts = [];
  const notices = [];
  const handlers = new Map();
  const pi = {
    on(event, fn) { handlers.set(event, fn); },
    getAllTools() { return [
      { name: 'inspect_project', annotations: { readOnlyHint: true } },
      { name: 'mutate_project', annotations: { readOnlyHint: false, destructiveHint: true } },
    ]; },
  };
  createToolPermissionExtension({ getPolicy: () => policy, ...(classify ? { classify } : {}) })(pi);
  return {
    prompts, notices,
    setMode(value) { policy = { ...policy, mode: value }; },
    call(toolName, input) {
      return handlers.get('tool_call')({ toolName, toolCallId: 'known-answer', input }, {
        cwd: context.cwd, hasUI,
        ui: { confirm: async (...args) => { prompts.push(args); return approve; },
          notify: (...args) => { notices.push(args); } },
      });
    },
  };
}

test('hook auto permits ordinary shell input without prompting or replacing input', async () => {
  const h = harness();
  const input = { command: 'node -e "console.log(42)"', timeout: 10 };
  const result = await h.call('bash', input);
  assert.ok(!result?.block);
  assert.deepEqual(input, { command: 'node -e "console.log(42)"', timeout: 10 });
  assert.equal(h.prompts.length, 0);
});
test('hook auto dangerous command approval delegates original command unchanged', async () => {
  const h = harness();
  const input = { command: 'shutdown /s /t 0' };
  assert.ok(!(await h.call('bash', input))?.block);
  assert.equal(input.command, 'shutdown /s /t 0');
  assert.equal(h.prompts.length, 1);
  assert.match(h.prompts[0].join(' '), /shutdown/);
});
test('hook denial returns visible reason including original operation', async () => {
  const h = harness({ approve: false });
  const result = await h.call('bash', { command: 'git push -f origin main' });
  assert.equal(result?.block, true);
  assert.match(result.reason, /denied|declined|拒绝|取消/i);
  assert.match(h.prompts[0].join(' '), /git push -f origin main/);
});
test('hook missing UI blocks required approval and reports why', async () => {
  const h = harness({ hasUI: false });
  const result = await h.call('bash', { command: 'shutdown /s' });
  assert.equal(result?.block, true);
  assert.match(result.reason, /UI|approval|确认|批准/i);
});
test('hook reads current mode on each call', async () => {
  const h = harness();
  await h.call('bash', { command: 'echo hello' });
  assert.equal(h.prompts.length, 0);
  h.setMode('ask');
  await h.call('bash', { command: 'echo hello' });
  assert.equal(h.prompts.length, 1);
});
test('ask mode requests approval for shell, edit, write and annotated mutating tools', async () => {
  const h = harness({ mode: 'ask' });
  for (const [name, input] of [
    ['bash', { command: 'echo hello' }], ['powershell', { command: 'Write-Output hello' }],
    ['edit', { path: './notes.md', oldText: 'old', newText: 'new' }],
    ['write', { path: './notes.md', content: 'hello' }], ['mutate_project', { value: 'demo' }],
  ]) assert.ok(!(await h.call(name, input))?.block);
  assert.equal(h.prompts.length, 5);
});
test('background starts use the same approval and headless policy as native shell commands', async () => {
  const denied = harness({ mode: 'ask', approve: false });
  assert.equal((await denied.call('background_job', {action:'start',command:'printf harmless'}))?.block, true);
  assert.equal(denied.prompts.length, 1);
  assert.match(denied.prompts[0].join(' '), /printf harmless/);
  const headless = harness({ mode:'ask', hasUI:false });
  assert.equal((await headless.call('background_job', {action:'start',command:'printf harmless'}))?.block, true);
});
test('automatic background starts classify dangerous commands and preserve safe inspection calls', async () => {
  const h = harness({ approve:false });
  // Classification only: no dangerous command is ever executed.
  for (const command of ['shutdown /r /t 0', 'rm -rf /', 'git push -f origin main']) {
    assert.equal((await h.call('background_job', {action:'start',command}))?.block, true);
  }
  assert.ok(!(await h.call('background_job', {action:'start',command:'printf harmless'}))?.block);
  h.setMode('ask');
  for (const action of ['list','status','read','wait','kill']) {
    assert.ok(!(await h.call('background_job', {action,id:'owned-job'}))?.block);
  }
  assert.equal(h.prompts.length, 3);
});
test('background classification uses its actual requested working directory', async () => {
  let observed;
  const h = harness({classify(command, context) { observed=context.cwd; return null; }});
  await h.call('background_job', {action:'start',command:'printf harmless',cwd:process.cwd()});
  assert.equal(observed, process.cwd());
});
test('read and search tools stay silent in ask mode including readOnlyHint extension', async () => {
  const h = harness({ mode: 'ask' });
  for (const [name, input] of [
    ['read', { path: 'C:/Windows/win.ini' }], ['grep', { pattern: 'kill', path: 'runtime' }],
    ['find', { pattern: '*.mjs' }], ['ls', { path: '.' }], ['inspect_project', {}],
  ]) assert.ok(!(await h.call(name, input))?.block);
  assert.equal(h.prompts.length, 0);
});
test('umeko_desktop preference operations remain exempt in ask mode', async () => {
  const h = harness({ mode: 'ask' });
  assert.ok(!(await h.call('umeko_desktop', { action: 'set_preferences', toolPermissionMode: 'auto' }))?.block);
  assert.equal(h.prompts.length, 0);
});
test('auto protects structured system writes and permits ordinary writes', async () => {
  const h = harness({ approve: false });
  assert.equal((await h.call('write', { path: 'C:/Windows/Temp/demo.txt', content: 'hello' }))?.block, true);
  assert.ok(!(await h.call('edit', { path: './notes.md', oldText: 'old', newText: 'new' }))?.block);
  assert.equal(h.prompts.length, 1);
});
test('classification error blocks visibly instead of silently continuing', async () => {
  const h = harness({ classify() { throw new Error('injected known-answer failure'); } });
  const result = await h.call('bash', { command: 'echo hello' });
  assert.equal(result?.block, true);
  assert.match(result.reason, /error|failed|错误|失败/i);
  assert.ok(h.notices.length > 0 || h.prompts.length > 0, 'failure must be visible to the user');
});
test('one bounded typical-command batch measures average classifier latency', t => {
  const commands = Object.values(allowFamilies).flat();
  const started = performance.now();
  for (const command of commands) classifyCommand(command, context);
  const averageMs = (performance.now() - started) / commands.length;
  t.diagnostic(`single batch: ${commands.length} typical inputs, average ${averageMs.toFixed(3)} ms/input; target <5 ms`);
  // Timing is secondary evidence, not an unstable wall-clock CI gate.
  assert.ok(Number.isFinite(averageMs));
});
