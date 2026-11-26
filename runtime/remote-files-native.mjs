// Native filesystem helpers use only the target OS shell and standard OS tools.
// Input is always quoted as data; these commands never interpolate user shell text.
const sh = value => "'" + String(value).replaceAll("'", "'\\''") + "'";
const ps = value => "'" + String(value).replaceAll("'", "''") + "'";

export function remoteFileHelperCommand(task, platform) {
  if (platform === 'windows') {
    const hash = path => `$s=[IO.File]::OpenRead(${ps(path)});try{$h=[Security.Cryptography.SHA256]::Create();try{$digest=[BitConverter]::ToString($h.ComputeHash($s)).Replace('-','').ToLowerInvariant()}finally{$h.Dispose()}}finally{$s.Dispose()};`;
    if (task.kind === 'hash') return `$ErrorActionPreference='Stop';${hash(task.path)}[Console]::Out.WriteLine($digest)`;
    if (task.kind !== 'assemble') throw new Error('Unknown remote file helper');
    // File.Replace is atomic for an existing destination; Move is atomic for a new one.
    return `$ErrorActionPreference='Stop';$d=${ps(task.directory)};$part=${ps(task.part)};$target=${ps(task.target)};` +
      `$out=[IO.File]::Open($part,[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::None);try{` +
      `for($i=0;$i -lt ${task.chunks};$i++){$s=[IO.File]::OpenRead([IO.Path]::Combine($d,('{0:D10}' -f $i)));try{$s.CopyTo($out)}finally{$s.Dispose()}};$out.Flush($true)` +
      `}finally{$out.Dispose()};${hash(task.part)}` +
      `if($digest -ne ${ps(task.sha256)}){throw 'Transfer SHA-256 mismatch'};` +
      `if([IO.File]::Exists($target)){[IO.File]::Replace($part,$target,$null)}else{[IO.File]::Move($part,$target)};` +
      `for($i=0;$i -lt ${task.chunks};$i++){[IO.File]::Delete([IO.Path]::Combine($d,('{0:D10}' -f $i)))};[IO.Directory]::Delete($d);` +
      `[Console]::Out.WriteLine($digest)`;
  }
  if (task.kind === 'hash') return `set -eu\nsha256sum -- ${sh(task.path)} | cut -c 1-64`;
  if (task.kind !== 'assemble') throw new Error('Unknown remote file helper');
  // Enumerate exact numeric chunk names instead of globbing arbitrary files.
  return `set -eu\npart=${sh(task.part)}\n: > "$part"\ni=0\nwhile [ "$i" -lt ${task.chunks} ]; do\n` +
    `name=$(printf '%010d' "$i")\ncat -- ${sh(task.directory)}/"$name" >> "$part"\ni=$((i+1))\ndone\n` +
    `digest=$(sha256sum -- "$part" | cut -c 1-64)\n[ "$digest" = ${sh(task.sha256)} ] || { echo 'Transfer SHA-256 mismatch' >&2; exit 1; }\n` +
    // -T prevents moving a verified file inside a directory supplied as target.
    `mv -fT -- "$part" ${sh(task.target)}\ni=0\nwhile [ "$i" -lt ${task.chunks} ]; do\n` +
    `name=$(printf '%010d' "$i")\nrm -f -- ${sh(task.directory)}/"$name"\ni=$((i+1))\ndone\n` +
    `rmdir -- ${sh(task.directory)}\nprintf '%s\\n' "$digest"`;
}
