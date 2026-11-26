// Serialize shared-target install/listener publication, not executor lifetimes.
const sh = value => `'${String(value).replaceAll("'", "'\\''")}'`;
const ps = value => `'${String(value).replaceAll("'", "''")}'`;

/** root already exists. Return the body's output/status while holding one OS lock. */
export function withBootstrapLock(platform, root, script) {
  if (platform === 'windows') return `
$umekoBootstrapRoot=[IO.Path]::GetFullPath(${ps(root)}).TrimEnd('\\','/').ToLowerInvariant()
# The root-derived name needs no digest. Collisions only serialize unrelated roots.
$umekoBootstrapKey=($umekoBootstrapRoot -replace '[^a-z0-9_.-]','_')
if($umekoBootstrapKey.Length -gt 200){$umekoBootstrapKey=$umekoBootstrapKey.Substring($umekoBootstrapKey.Length-200)}
$umekoBootstrapMutex=[Threading.Mutex]::new($false,('Global\\UmekoRemoteBootstrap-'+$umekoBootstrapKey))
$umekoBootstrapHeld=$false
try {
 try {$umekoBootstrapHeld=$umekoBootstrapMutex.WaitOne(60000)}
 catch [Threading.AbandonedMutexException] {$umekoBootstrapHeld=$true}
 if(!$umekoBootstrapHeld){throw 'Timed out waiting for remote bootstrap lock'}
 & {
${script}
  $umekoBootstrapBodyOK=$?
  if(!$umekoBootstrapBodyOK){if($LASTEXITCODE){exit $LASTEXITCODE};exit 1}
 }
} finally {
 if($umekoBootstrapHeld){$umekoBootstrapMutex.ReleaseMutex()}
 $umekoBootstrapMutex.Dispose()
}
exit 0
`;
  if (platform !== 'linux') throw new Error('Unsupported remote bootstrap platform');
  return `umask 077
exec 9>${sh(`${root}/bootstrap.lock`)}
flock -x -w 60 9 || { echo 'Timed out waiting for remote bootstrap lock' >&2; exit 1; }
# Only this parent owns descriptor 9; detached descendants must not retain it.
sh -c ${sh(script)} 9>&-
umekoBootstrapStatus=$?
exec 9>&-
exit "$umekoBootstrapStatus"
`;
}
