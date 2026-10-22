param([string]$OutputDirectory = 'dist')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$buildDestination = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $OutputDirectory))
$buildWorkspacePrefix = $PSScriptRoot.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
if (-not $buildDestination.StartsWith($buildWorkspacePrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Build output must stay within this workspace' }
$buildBundlePrefix = (Join-Path $buildDestination 'Umeko').TrimEnd('\') + '\'
foreach ($buildProcess in @(Get-Process Umeko -ErrorAction SilentlyContinue)) {
    if (-not $buildProcess.Path -or $buildProcess.Path.StartsWith($buildBundlePrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Close the app running from the target bundle before building. No output was changed.' }
}
& '.venv/Scripts/python.exe' -m pip install pyinstaller==6.19.0
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed' }
& '.venv/Scripts/python.exe' scripts/bundle_node.py
if ($LASTEXITCODE -ne 0) { throw 'Bundled Node.js preparation failed' }
& '.venv/Scripts/python.exe' prepare_runtime.py
if ($LASTEXITCODE -ne 0) { throw 'Pi compatibility validation failed' }
& '.venv/Scripts/python.exe' scripts/fetch-search-tools.py
if ($LASTEXITCODE -ne 0) { throw 'Pi search tool preparation failed' }
& '.venv/Scripts/python.exe' build_icons.py
& '.venv/Scripts/python.exe' scripts/write-build-info.py
if ($LASTEXITCODE -ne 0) { throw 'Build metadata generation failed' }
& '.venv/Scripts/python.exe' scripts/build-provider-resources.py
if ($LASTEXITCODE -ne 0) { throw 'Provider SDK packaging failed' }
$originalBuildPath = $env:PATH
try {
    # Exclude unrelated SDK DLLs in PATH. Qt uses Windows' unversioned ICU shim;
    # Poppler's incompatible icuuc.dll must not be selected by the dependency scan.
    $env:PATH = "$PSScriptRoot/.venv/Scripts;$env:SystemRoot/System32;$env:SystemRoot"
    & '.venv/Scripts/python.exe' -m PyInstaller --clean --noconfirm --windowed --onedir --name Umeko --distpath $buildDestination --icon app/icons/app.ico --add-data 'app/qml;app/qml' --add-data 'app/theme-prompt.txt;app' --add-data 'app/icons;app/icons' --add-data 'runtime/bridge.mjs;runtime' --add-data 'runtime/provider-policy.mjs;runtime' --add-data 'runtime/resources.mjs;runtime' --add-data 'runtime/chatbox.mjs;runtime' --add-data 'runtime/network-retry.mjs;runtime' --add-data 'build/build-info.json;.' --add-data 'build/provider-resources;provider-resources' --add-data 'THIRD_PARTY_NOTICES.md;.' main.py
    if ($LASTEXITCODE -ne 0) { throw 'Application packaging failed' }
} finally {
    $env:PATH = $originalBuildPath
}
$releaseParent = Join-Path $buildDestination 'Umeko/_internal/runtime/releases'
New-Item -ItemType Directory -Path $releaseParent -Force | Out-Null
# Node loads its own runtime files; copy them byte-for-byte after Qt packaging.
Copy-Item -LiteralPath 'runtime/releases/coding-1.3.0' -Destination $releaseParent -Recurse -Force
Copy-Item -LiteralPath 'runtime/node' -Destination (Join-Path $buildDestination 'Umeko/_internal/runtime') -Recurse -Force
Copy-Item -LiteralPath 'README.md' -Destination (Join-Path $buildDestination 'Umeko/README.md') -Force
Write-Output ('Portable app: ' + (Join-Path $buildDestination 'Umeko/Umeko.exe'))
