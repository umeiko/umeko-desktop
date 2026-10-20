$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python venv creation failed' }
}
& '.venv/Scripts/python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Qt dependency installation failed' }
npm.cmd ci --prefix runtime --ignore-scripts --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'Pi dependency installation failed' }
& '.venv/Scripts/python.exe' prepare_runtime.py
if ($LASTEXITCODE -ne 0) { throw 'Pi compatibility validation failed' }
Write-Output 'Ready. Double-click Start-Umeko.cmd.'
