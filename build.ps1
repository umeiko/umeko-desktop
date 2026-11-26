param([string]$OutputDirectory = 'dist')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$buildDestination = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $OutputDirectory))
$buildWorkspacePrefix = $PSScriptRoot.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
if (-not $buildDestination.StartsWith($buildWorkspacePrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Build output must stay within this workspace' }
$buildBundlePrefix = (Join-Path $buildDestination 'Umeko').TrimEnd('\') + '\'
foreach ($buildProcess in @(Get-Process Umeko, Umeko-cli -ErrorAction SilentlyContinue)) {
    if (-not $buildProcess.Path -or $buildProcess.Path.StartsWith($buildBundlePrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Close the app running from the target bundle before building. No output was changed.' }
}
& '.venv/Scripts/python.exe' -m pip install pyinstaller==6.19.0 cmake==3.31.6 Pillow==13.0.0
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed' }
& '.venv/Scripts/python.exe' scripts/build-notifications.py
if ($LASTEXITCODE -ne 0) { throw 'Native notification adapter build failed' }
& '.venv/Scripts/python.exe' scripts/bundle_node.py
if ($LASTEXITCODE -ne 0) { throw 'Bundled Node.js preparation failed' }
& '.venv/Scripts/python.exe' prepare_runtime.py
if ($LASTEXITCODE -ne 0) { throw 'Pi compatibility validation failed' }
& '.venv/Scripts/python.exe' scripts/fetch-search-tools.py
if ($LASTEXITCODE -ne 0) { throw 'Pi search tool preparation failed' }
& '.venv/Scripts/python.exe' scripts/fetch-remote-exec.py --platform windows --arch x64 --output runtime/releases/coding-1.5.2/remote-exec-assets
if ($LASTEXITCODE -ne 0) { throw 'Remote exec-server preparation failed' }
& '.venv/Scripts/python.exe' scripts/build-windows-sandbox.py
if ($LASTEXITCODE -ne 0) { throw 'Windows sandbox build failed' }
$sandboxGit = 'build/sandbox-git'
if (Test-Path -LiteralPath $sandboxGit -PathType Container) {
    & '.venv/Scripts/python.exe' scripts/archive-sandbox-git-bash.py
    if ($LASTEXITCODE -ne 0) { throw 'Git Bash archive preparation failed' }
}
& '.venv/Scripts/python.exe' build_icons.py
& '.venv/Scripts/python.exe' scripts/write-build-info.py
if ($LASTEXITCODE -ne 0) { throw 'Build metadata generation failed' }
& '.venv/Scripts/python.exe' scripts/build-provider-resources.py
if ($LASTEXITCODE -ne 0) { throw 'Provider SDK packaging failed' }
& '.venv/Scripts/python.exe' scripts/build-desktop-plugin-resources.py
if ($LASTEXITCODE -ne 0) { throw 'Desktop plugin SDK packaging failed' }
$originalBuildPath = $env:PATH
try {
    # Exclude unrelated SDK DLLs in PATH. Qt uses Windows' unversioned ICU shim;
    # Poppler's incompatible icuuc.dll must not be selected by the dependency scan.
    $env:PATH = "$PSScriptRoot/.venv/Scripts;$env:SystemRoot/System32;$env:SystemRoot"
    & '.venv/Scripts/python.exe' scripts/webview_package.py --frontend build/webview-support
    if ($LASTEXITCODE -ne 0) { throw 'WebView frontend preparation failed' }
    & '.venv/Scripts/python.exe' -m PyInstaller --clean --noconfirm --distpath $buildDestination scripts/umeko-windows.spec
    if ($LASTEXITCODE -ne 0) { throw 'Application packaging failed' }
} finally {
    $env:PATH = $originalBuildPath
}
$releaseParent = Join-Path $buildDestination 'Umeko/_internal/runtime/releases'
New-Item -ItemType Directory -Path $releaseParent -Force | Out-Null
# Node loads its own runtime files; copy them byte-for-byte after Qt packaging.
Copy-Item -LiteralPath 'runtime/releases/coding-1.5.2' -Destination $releaseParent -Recurse -Force
$generatedRuntimeCache = Join-Path $releaseParent 'coding-1.5.2/node_modules/.cache'
if (Test-Path -LiteralPath $generatedRuntimeCache) { Remove-Item -LiteralPath $generatedRuntimeCache -Recurse -Force }
Copy-Item -LiteralPath 'runtime/node' -Destination (Join-Path $buildDestination 'Umeko/_internal/runtime') -Recurse -Force
Copy-Item -LiteralPath 'runtime/preview-network.mjs' -Destination (Join-Path $buildDestination 'Umeko/_internal/runtime') -Force
Copy-Item -LiteralPath 'runtime/package-install.mjs' -Destination (Join-Path $buildDestination 'Umeko/_internal/runtime') -Force
Copy-Item -LiteralPath 'runtime/dsh-acp-bridge.mjs' -Destination (Join-Path $buildDestination 'Umeko/_internal/runtime') -Force
Copy-Item -LiteralPath 'runtime/dsh-permissions.mjs' -Destination (Join-Path $buildDestination 'Umeko/_internal/runtime') -Force
Copy-Item -Path 'runtime/remote-*.mjs','runtime/remote-exec-assets.json' -Destination (Join-Path $buildDestination 'Umeko/_internal/runtime') -Force
Copy-Item -LiteralPath 'runtime/windows-sandbox.mjs' -Destination (Join-Path $buildDestination 'Umeko/_internal/runtime') -Force
Copy-Item -LiteralPath 'README.md' -Destination (Join-Path $buildDestination 'Umeko/README.md') -Force
& '.venv/Scripts/python.exe' scripts/package_payload.py --resources (Join-Path $buildDestination 'Umeko/_internal') --report build/payload-optimization.json
if ($LASTEXITCODE -ne 0) { throw 'Resource optimization failed' }
Write-Output ('Portable app: ' + (Join-Path $buildDestination 'Umeko/Umeko.exe'))
