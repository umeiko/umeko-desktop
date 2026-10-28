[CmdletBinding(SupportsShouldProcess)]
param()
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$taskBuildRoot = Join-Path $taskRoot 'build'
$taskProcesses = @(Get-Process Umeko -ErrorAction SilentlyContinue)
$taskActivePaths = @()
foreach ($taskProcess in $taskProcesses) {
    if (-not $taskProcess.Path) { throw 'Cannot identify a running app safely; close it before cleanup.' }
    $taskActivePaths += $taskProcess.Path
}
$taskCandidates = @()
$taskBundles = @()
if (Test-Path -LiteralPath $taskBuildRoot) {
    if (((Get-Item -LiteralPath $taskBuildRoot -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'The build root must not be a linked directory.' }
    foreach ($taskDirectory in Get-ChildItem -LiteralPath $taskBuildRoot -Directory -Force) {
        if (($taskDirectory.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
        $taskNestedBundle = (Test-Path -LiteralPath (Join-Path $taskDirectory.FullName 'Umeko/Umeko.exe')) -and (Test-Path -LiteralPath (Join-Path $taskDirectory.FullName 'Umeko/_internal'))
        $taskDirectBundle = (Test-Path -LiteralPath (Join-Path $taskDirectory.FullName 'Umeko.exe')) -and (Test-Path -LiteralPath (Join-Path $taskDirectory.FullName '_internal'))
        if ($taskNestedBundle -or $taskDirectBundle) { $taskBundles += $taskDirectory; continue }
        $taskCache = $taskDirectory.Name -eq 'Umeko' -and (Test-Path -LiteralPath (Join-Path $taskDirectory.FullName 'Analysis-00.toc'))
        $taskEmpty = -not @(Get-ChildItem -LiteralPath $taskDirectory.FullName -Force | Select-Object -First 1).Count
        if ($taskCache -or $taskEmpty) { $taskCandidates += $taskDirectory.FullName }
    }
}
$taskCanonicalReady = (Test-Path -LiteralPath (Join-Path $taskRoot 'dist/Umeko/Umeko.exe')) -and (Test-Path -LiteralPath (Join-Path $taskRoot 'dist/Umeko/_internal'))
$taskFallback = if (-not $taskCanonicalReady) { $taskBundles | Sort-Object LastWriteTime -Descending | Select-Object -First 1 } else { $null }
foreach ($taskBundle in $taskBundles) {
    if ($taskFallback -and $taskBundle.FullName -eq $taskFallback.FullName) { Write-Output ('Keeping latest fallback: ' + $taskBundle.FullName); continue }
    $taskCandidates += $taskBundle.FullName
}
foreach ($taskCandidate in $taskCandidates) {
    $taskResolved = (Resolve-Path -LiteralPath $taskCandidate).Path.TrimEnd('\')
    if (-not $taskResolved.StartsWith($taskBuildRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw ('Target outside generated output: ' + $taskResolved) }
    if (((Get-Item -LiteralPath $taskResolved -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
    if (@($taskActivePaths | Where-Object { $_.StartsWith($taskResolved + '\', [StringComparison]::OrdinalIgnoreCase) }).Count) { Write-Output ('Keeping running app: ' + $taskResolved); continue }
    if ($PSCmdlet.ShouldProcess($taskResolved, 'Remove obsolete generated build')) { Remove-Item -LiteralPath $taskResolved -Recurse -Force }
}
