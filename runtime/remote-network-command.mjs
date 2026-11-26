import { remoteProxyUrl } from "./remote-network.mjs";

export function commandProxyEnvironment(port, windows, shell) {
  if (!port) return {};
  const proxy = remoteProxyUrl(port);
  const bypass = "localhost,127.0.0.1,::1";
  const env = {
    HTTP_PROXY: proxy, HTTPS_PROXY: proxy, ALL_PROXY: proxy, NO_PROXY: bypass,
    PIP_PROXY: proxy, npm_config_proxy: proxy, npm_config_https_proxy: proxy, npm_config_noproxy: bypass,
    UMEKO_REMOTE_HTTP_PROXY: proxy,
  };
  // Windows resolves environment names case-insensitively.
  if (!windows) Object.assign(env, { http_proxy: proxy, https_proxy: proxy, all_proxy: proxy, no_proxy: bypass });
  if (!windows && !bourneShell(shell)) {
    Object.assign(env, { GIT_CONFIG_COUNT: "1", GIT_CONFIG_KEY_0: "http.proxy", GIT_CONFIG_VALUE_0: proxy });
  }
  return env;
}

const shellName = path => String(path ?? "").split(/[\\/]/).at(-1).replace(/\.exe$/i, "").toLowerCase();
const bourneShell = path => /^(?:ba|da|k|m|za|z|a)?sh$/.test(shellName(path));

export function commandProxySetup(windows, shell) {
  if (windows) return `if ($env:UMEKO_REMOTE_HTTP_PROXY) {
  foreach ($program in @('curl', 'wget')) {
    if (Get-Command "$program.exe" -CommandType Application -ErrorAction SilentlyContinue) {
      Set-Alias -Name $program -Value "$program.exe" -Option AllScope -Force
    }
  }
  $umekoGitCount = 0
  if (![int]::TryParse($env:GIT_CONFIG_COUNT, [ref]$umekoGitCount) -or $umekoGitCount -lt 0 -or $umekoGitCount -gt 64) {
    $umekoGitCount = 0
  }
  [Environment]::SetEnvironmentVariable("GIT_CONFIG_KEY_$umekoGitCount", "http.proxy", "Process")
  [Environment]::SetEnvironmentVariable("GIT_CONFIG_VALUE_$umekoGitCount", $env:UMEKO_REMOTE_HTTP_PROXY, "Process")
  $env:GIT_CONFIG_COUNT = [string]($umekoGitCount + 1)
  Remove-Variable umekoGitCount
}
`;
  if (!bourneShell(shell)) return "";
  return `if [ -n "\${UMEKO_REMOTE_HTTP_PROXY:-}" ]; then
  export http_proxy="$UMEKO_REMOTE_HTTP_PROXY" https_proxy="$UMEKO_REMOTE_HTTP_PROXY" all_proxy="$UMEKO_REMOTE_HTTP_PROXY"
  export no_proxy=localhost,127.0.0.1,::1
  umeko_git_count=\${GIT_CONFIG_COUNT:-0}
  case "$umeko_git_count" in 0|[1-9]|[1-5][0-9]|6[0-4]) ;; *) umeko_git_count=0 ;; esac
  export "GIT_CONFIG_KEY_$umeko_git_count=http.proxy"
  export "GIT_CONFIG_VALUE_$umeko_git_count=$UMEKO_REMOTE_HTTP_PROXY"
  export GIT_CONFIG_COUNT=$((umeko_git_count + 1))
  unset umeko_git_count
  sudo() {
    # sudo can clear proxy variables. Pass apt's options after its arguments,
    # including when standard non-interactive sudo options precede apt.
    for umeko_sudo_arg do
      case "$umeko_sudo_arg" in
        -n|-E|-H|--non-interactive|--preserve-env|--set-home|--) continue ;;
        apt|apt-get|/usr/bin/apt|/usr/bin/apt-get)
          command sudo "$@" -o "Acquire::http::Proxy=$UMEKO_REMOTE_HTTP_PROXY" -o "Acquire::https::Proxy=$UMEKO_REMOTE_HTTP_PROXY"
          return $? ;;
        *) break ;;
      esac
    done
    command sudo "$@"
  }
  yum() { command yum --setopt="proxy=$UMEKO_REMOTE_HTTP_PROXY" "$@"; }
  dnf() { command dnf --setopt="proxy=$UMEKO_REMOTE_HTTP_PROXY" "$@"; }
  wget() {
    command wget -e "http_proxy=$UMEKO_REMOTE_HTTP_PROXY" -e "https_proxy=$UMEKO_REMOTE_HTTP_PROXY" -e "no_proxy=$no_proxy" "$@"
  }
fi
`;
}

/** Prepare the exec-server shell form used by remote workspace bash and !.
 * Streaming, timeout and cancellation remain with the caller.
 */
export function prepareRemoteShellProcess(params, port, windows) {
  if (!port || params?.env?.UMEKO_REMOTE_HTTP_PROXY || !Array.isArray(params?.argv)) return params;
  const [shell] = params.argv;
  const powershell = ["powershell", "pwsh"].includes(shellName(shell));
  if (!powershell && !bourneShell(shell)) return params;
  const commandIndex = params.argv.findIndex((arg, index) => index > 0 &&
    (powershell ? /^-(?:EncodedCommand|Command)$/i.test(arg) : ["-c", "-lc"].includes(arg)));
  if (commandIndex < 0 || typeof params.argv[commandIndex + 1] !== "string") return params;
  const argv = [...params.argv];
  const encoded = powershell && /^-EncodedCommand$/i.test(argv[commandIndex]);
  const command = encoded ? Buffer.from(argv[commandIndex + 1], "base64").toString("utf16le") : argv[commandIndex + 1];
  const script = commandProxySetup(powershell, shell) + command;
  argv[commandIndex + 1] = encoded ? Buffer.from(script, "utf16le").toString("base64") : script;
  return { ...params, argv, env: { ...params.env, ...commandProxyEnvironment(port, windows, shell) } };
}

// POSIX sh requires function names to be shell identifiers, so apt-get needs
// an executable wrapper. Keep it in the same private directory as the command.
export const aptProxyLaunch = () => `if [ -n "\${UMEKO_REMOTE_HTTP_PROXY:-}" ]; then
  apt_bin="$PWD/apt-bin"
  mkdir "$apt_bin" || exit 1
  for apt_name in apt apt-get; do
    apt_real=$(command -v "$apt_name") || continue
    case "$apt_real" in /*) ;; *) continue ;; esac
    case "$apt_name" in
      apt) export UMEKO_APT_REAL="$apt_real" ;;
      apt-get) export UMEKO_APT_GET_REAL="$apt_real" ;;
    esac
    cat > "$apt_bin/$apt_name" <<'UMEKO_APT'
#!/bin/sh
case "$0" in */apt-get) real=$UMEKO_APT_GET_REAL ;; *) real=$UMEKO_APT_REAL ;; esac
exec "$real" "$@" -o "Acquire::http::Proxy=$UMEKO_REMOTE_HTTP_PROXY" -o "Acquire::https::Proxy=$UMEKO_REMOTE_HTTP_PROXY"
UMEKO_APT
    chmod 700 "$apt_bin/$apt_name"
  done
  export PATH="$apt_bin:$PATH"
fi`;

// The optional wrapper creates its config in this command's private directory.
// It is invoked only by an explicit remote_network request, never by replaying
// an arbitrary command that may already have changed the remote workspace.
export function proxychainsLaunch() {
  return `if command -v proxychains4 >/dev/null 2>&1; then
  chain=proxychains4
elif command -v proxychains >/dev/null 2>&1; then
  chain=proxychains
else
  echo 'proxychains-ng is not installed on the server' > output; echo 1 > exit; exit 1
fi
if [ -z "\${UMEKO_REMOTE_HTTP_PROXY:-}" ]; then
  echo 'Shared network is not active' > output; echo 1 > exit; exit 1
fi
cat > proxychains.conf <<EOF
strict_chain
proxy_dns
localnet 127.0.0.0/255.0.0.0
localnet ::1/128
[ProxyList]
http 127.0.0.1 \${UMEKO_REMOTE_HTTP_PROXY##*:}
EOF
set -- "$chain" -q -f "$PWD/proxychains.conf"`;
}
