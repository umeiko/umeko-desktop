"""Build the pinned Codex sandbox without the Codex CLI or provider client."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pi_runtime import RELEASE_NAME

TAG = "rust-v0.172.0"
BINARIES = ("umeko-sandbox", "codex-windows-sandbox-setup", "codex-command-runner")


def restrict_workspace(rust):
    # Cargo resolves the full workspace even for `build -p`. The JavaScript
    # runtime's V8 source has Chromium submodules the sandbox does not use.
    manifest = rust / "Cargo.toml"
    text = manifest.read_text(encoding="utf-8")
    inherited = tomllib.loads(text)["workspace"]["dependencies"]
    pending = [rust / "windows-sandbox-rs"]
    members = set()
    while pending:
        crate = pending.pop().resolve()
        member = crate.relative_to(rust).as_posix()
        if member in members:
            continue
        members.add(member)
        config = tomllib.loads((crate / "Cargo.toml").read_text(encoding="utf-8"))
        for table in (config, *config.get("target", {}).values()):
            for scope in ("dependencies", "build-dependencies", "dev-dependencies"):
                for name, dep in table.get(scope, {}).items():
                    if not isinstance(dep, dict):
                        continue
                    base = crate
                    if dep.get("workspace"):
                        base, dep = rust, inherited[name]
                    if isinstance(dep, dict) and "path" in dep:
                        pending.append(base / dep["path"])
    entries = "\n".join(f'    "{name}",' for name in sorted(members))
    text, member_edits = re.subn(r"(?ms)^members = \[\n.*?^\]", f"members = [\n{entries}\n]", text, count=1)
    text, patch_edits = re.subn(r'(?m)^v8 = \{ git = "https://github\.com/openai-oss-forks/rusty_v8\.git"[^\n]+\n', "", text)
    if member_edits != 1 or patch_edits != 1:
        raise RuntimeError("Pinned Codex workspace layout changed")
    manifest.write_text(text, encoding="utf-8")


def adopt_sandbox(sandbox):
    # Use a separate machine-wide namespace, including the uninstall paths.
    # Windows local account names have a 20-character limit.
    for path in (sandbox / "src").rglob("*.rs"):
        original = path.read_text(encoding="utf-8")
        code = original.replace("CodexSandbox", "UmekoSandbox").replace("codex_sandbox_offline_", "umeko_sandbox_offline_")
        code = code.replace("Codex Sandbox Offline", "Umeko Sandbox Offline")
        if path.name == "wfp.rs" or path.name == "filter_specs.rs":
            def substitute(match):
                original_guid = int(match.group(1).replace("_", ""), 16)
                own_guid = original_guid ^ 0x736E895FB74C000000002748DEE9B754
                return f"GUID::from_u128(0x{own_guid:032x})"

            code = re.sub(r"GUID::from_u128\(0x([a-f0-9_]+)\)", substitute, code)
            code = code.replace("Codex Windows Sandbox", "Umeko Windows Sandbox")
        if code != original:
            path.write_text(code, encoding="utf-8")

    # Provisioning is an explicit user action. Requiring WFP installation also
    # prevents reporting offline setup as ready after an incomplete install.
    edits = {
        "setup_provisioning.rs": (
            "    if repairing_disabled_accounts {\n        // Ordinary setup keeps its best-effort WFP behavior. Recovery must not reopen logons\n"
            "        // after cleanup removed protections unless restoring those protections succeeded.\n        wfp_result?;",
            "    wfp_result?;\n    if repairing_disabled_accounts {",
        ),
    }
    for name, (old, new) in edits.items():
        path = sandbox / "src" / name
        body = path.read_text(encoding="utf-8")
        if body.count(old) != 1:
            raise RuntimeError(f"Pinned Codex source drifted in {name}")
        path.write_text(body.replace(old, new), encoding="utf-8")
    path = sandbox / "src/identity.rs"
    body = path.read_text(encoding="utf-8")
    start = body.index("fn run_automatic_setup(")
    end = body.index("fn desired_offline_proxy_settings(", start)
    body = body[:start] + (
        "fn run_automatic_setup(_: SandboxSetupRequest<'_>, _: &OfflineProxySettings) -> Result<()> {\n"
        "    anyhow::bail!(\"elevated sandbox needs setup or repair in Agent settings\");\n}\n\n"
    ) + body[end:]
    path.write_text(body, encoding="utf-8")
    shutil.copyfile(ROOT / "scripts/umeko-sandbox.rs", sandbox / "src/bin/umeko-sandbox.rs")


def main():
    if sys.platform != "win32":
        raise RuntimeError("Build the Windows sandbox on Windows")
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="windows-sandbox-", dir=build) as staging:
        checkout = Path(staging) / "codex"
        subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "core.longpaths=true", "clone", "--depth", "1", "--branch", TAG,
                        "https://github.com/openai/codex.git", str(checkout)], check=True)
        subprocess.run(["git", "-c", "core.autocrlf=false", "-C", str(checkout), "apply", "--whitespace=error",
                        str(ROOT / "scripts/windows-sandbox-loopback.patch"),
                        str(ROOT / "scripts/windows-sandbox-cwd.patch"),
                        str(ROOT / "scripts/windows-sandbox-stdin.patch")], check=True)
        rust = (checkout / "codex-rs").resolve()
        restrict_workspace(rust)
        adopt_sandbox(rust / "windows-sandbox-rs")
        target = Path(staging) / "target"
        env = dict(os.environ, CARGO_PROFILE_RELEASE_DEBUG="0", CARGO_PROFILE_RELEASE_STRIP="symbols",
                   CARGO_PROFILE_RELEASE_LTO="false", CARGO_TARGET_DIR=str(target),
                   CARGO_NET_GIT_FETCH_WITH_CLI="true")
        # Cargo resolves Git patches elsewhere in the pinned workspace as well.
        # Pass long-path support to the Git processes Cargo starts.
        config_count = int(env.get("GIT_CONFIG_COUNT", "0"))
        env[f"GIT_CONFIG_KEY_{config_count}"] = "core.longpaths"
        env[f"GIT_CONFIG_VALUE_{config_count}"] = "true"
        env["GIT_CONFIG_COUNT"] = str(config_count + 1)
        bins = [arg for name in BINARIES for arg in ("--bin", name)]
        # Start from the upstream lockfile. Cargo prunes entries belonging to
        # removed workspace members in this temporary checkout.
        subprocess.run(["cargo", "build", "--release", "-p", "codex-windows-sandbox", *bins],
                       cwd=rust, env=env, check=True)
        output = ROOT / "runtime/releases" / RELEASE_NAME / "bin/windows-sandbox"
        output.mkdir(parents=True, exist_ok=True)
        for name in BINARIES:
            executable = output / (name + ".exe")
            shutil.copyfile(target / "release" / executable.name, executable)
            print(f"{executable.name}: {executable.stat().st_size:,} bytes", flush=True)
        shutil.copyfile(checkout / "LICENSE", output / "CODEX-LICENSE.txt")


if __name__ == "__main__":
    main()
