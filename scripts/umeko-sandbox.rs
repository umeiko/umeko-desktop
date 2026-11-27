//! Windows command launcher, adapted from openai/codex rust-v0.172.0,
//! codex-rs/cli/src/debug_sandbox.rs and core/src/windows_sandbox.rs.
//! Licensed under Apache-2.0. See licenses/codex-windows-sandbox-NOTICE.txt.

use anyhow::{Context, Result, bail, ensure};
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_protocol::models::PermissionProfile;
use codex_protocol::permissions::NetworkSandboxPolicy;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_windows_sandbox::{
    ResolvedWindowsSandboxPermissions, SandboxSetupRequest, WindowsSandboxProvisioningSettings,
    WindowsSandboxProxySettingsMode, WindowsSandboxSessionRequest, clean_up_legacy_windows_sandbox,
    forward_sandbox_session_stdio, run_elevated_setup, sandbox_setup_is_complete_with_settings,
    spawn_windows_sandbox_session_for_level,
};
use std::collections::HashMap;
use std::io::ErrorKind;
use std::os::windows::fs::MetadataExt;
use std::path::{Path, PathBuf};

fn ready(home: &Path) -> bool {
    sandbox_setup_is_complete_with_settings(home, &WindowsSandboxProvisioningSettings::default())
}

fn remove_git_cache(home: &Path) -> Result<()> {
    ensure!(home.is_absolute() && home.file_name().is_some_and(|name| name == "windows-sandbox"),
        "expected an absolute Windows sandbox data directory");
    match std::fs::symlink_metadata(home) {
        Ok(metadata) => ensure!(metadata.is_dir() && metadata.file_attributes() & 0x400 == 0,
            "Windows sandbox data directory must be an ordinary directory"),
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error.into()),
    }
    let cache = home.join("git");
    match std::fs::remove_dir_all(&cache) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error).context("remove the Git Bash cache"),
    }
}

fn default_home() -> Option<PathBuf> {
    let profile = std::env::var_os("UMEKO_DATA_DIR").filter(|value| !value.is_empty()).map(PathBuf::from)
        .or_else(|| std::env::var_os("USERPROFILE").map(|value| PathBuf::from(value).join(".umeko").join("desktop")))?;
    Some(profile.join("windows-sandbox"))
}

fn environment() -> HashMap<String, String> {
    std::env::vars_os().filter_map(|(key, value)| {
        let key = key.into_string().ok()?;
        let value = value.into_string().ok()?;
        Some((key.to_ascii_uppercase(), value))
    }).collect()
}

async fn run(home: &Path, temp: &Path, workspace: &Path, cwd: &Path, level: &str, network: &str, command: &[String]) -> Result<i32> {
    // rust-v0.172.0 codex-rs/core/src/unified_exec/process_manager.rs:
    // keep standard input open only when the caller requests interaction.
    let stdin_open = command.first().is_some_and(|arg| arg == "--stdin-open");
    let command = if stdin_open { &command[1..] } else { command };
    ensure!(!command.is_empty(), "no command was supplied");
    let workspace = dunce::canonicalize(workspace).context("open current workspace")?;
    let cwd = dunce::canonicalize(cwd).context("open command working directory")?;
    let temp = dunce::canonicalize(temp).context("open sandbox temp directory")?;
    ensure!(cwd.starts_with(&workspace) && !temp.starts_with(&workspace), "command working directory must be inside the current workspace");
    let level = match level {
        "elevated" if ready(home) => WindowsSandboxLevel::Elevated,
        "elevated" => bail!("elevated setup is unavailable. Run setup from Agent settings"),
        "non-elevated" => WindowsSandboxLevel::RestrictedToken,
        _ => bail!("invalid Windows sandbox level"),
    };
    let network = match network {
        "allow" => NetworkSandboxPolicy::Enabled,
        "block" if level == WindowsSandboxLevel::Elevated => NetworkSandboxPolicy::Restricted,
        "block" => bail!("blocking network access requires elevated setup"),
        _ => bail!("invalid Windows sandbox network policy"),
    };
    let roots = [AbsolutePathBuf::try_from(workspace)?];
    let writable = [AbsolutePathBuf::try_from(temp.clone())?];
    let profile = PermissionProfile::workspace_write_with(&writable, network, true, true);
    let mut env = environment();
    for key in ["TEMP", "TMP", "TMPDIR"] {
        env.insert(key.into(), temp.to_string_lossy().into_owned());
    }
    let session = spawn_windows_sandbox_session_for_level(WindowsSandboxSessionRequest {
        permission_profile: &profile,
        workspace_roots: &roots,
        codex_home: home,
        command: command.to_vec(),
        cwd: &cwd,
        env_map: env,
        windows_sandbox_level: level,
        proxy_enforced: false,
        network_proxy_restricting_sid: None,
        proxy_settings_mode: WindowsSandboxProxySettingsMode::Preserve,
        timeout_ms: None,
        read_roots_override: None,
        read_roots_include_platform_defaults: false,
        write_roots_override: None,
        deny_read_paths_override: &[],
        deny_write_paths_override: &[],
        tty: false,
        stdin_open,
    }).await?;
    Ok(forward_sandbox_session_stdio(session).await)
}

async fn execute(args: &[String]) -> Result<i32> {
    match args {
        [operation, home] if operation == "status" => Ok(if ready(Path::new(home)) { 0 } else { 1 }),
        [operation, home] if operation == "setup" => {
            let home = PathBuf::from(home);
            std::fs::create_dir_all(&home)?;
            let roots = [AbsolutePathBuf::try_from(home.clone())?];
            let profile = PermissionProfile::workspace_write();
            let permissions = ResolvedWindowsSandboxPermissions::try_from_permission_profile_for_workspace_roots(&profile, &roots)?;
            // Use the original launcher for UAC. It captures the requesting
            // identity before elevation, including credential-prompt setup.
            run_elevated_setup(SandboxSetupRequest {
                permissions: &permissions,
                command_cwd: &home,
                env_map: &HashMap::new(),
                codex_home: &home,
                proxy_enforced: false,
            })?;
            ensure!(ready(&home), "setup did not install the offline policy");
            Ok(0)
        }
        [operation] if operation == "uninstall" => {
            clean_up_legacy_windows_sandbox()?;
            if let Some(home) = default_home() {
                remove_git_cache(&home)?;
            }
            Ok(0)
        }
        [operation, home] if operation == "uninstall" => {
            clean_up_legacy_windows_sandbox()?;
            remove_git_cache(Path::new(home))?;
            Ok(0)
        }
        [operation, home] if operation == "uninstall-cache" => {
            remove_git_cache(Path::new(home))?;
            Ok(0)
        }
        [operation, home, temp, workspace, cwd, level, network, command @ ..] if operation == "run" => {
            run(Path::new(home), Path::new(temp), Path::new(workspace), Path::new(cwd), level, network, command).await
        }
        _ => bail!("expected status, setup, run, uninstall or uninstall-cache"),
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let code = match execute(&args).await {
        Ok(code) => code,
        Err(err) => {
            eprintln!("Windows sandbox could not start: {err:#}");
            1
        }
    };
    std::process::exit(code);
}
