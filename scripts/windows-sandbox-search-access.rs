//! Search read grants reuse the ACL preparation in openai/codex rust-v0.172.0,
//! codex-rs/windows-sandbox-rs/src/setup_provisioning.rs and src/acl.rs.
//! Licensed under Apache-2.0. See licenses/codex-windows-sandbox-NOTICE.txt.

use crate::acl::grant_read_execute_aces;
use crate::token::{
    create_workspace_write_token_with_caps_from, get_current_token_for_restriction,
    get_logon_sid_bytes, world_sid,
};
use anyhow::{Context, Result, ensure};
use std::fs::{self, OpenOptions};
use std::io::{self, ErrorKind};
use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle};
use std::path::Path;
use windows_sys::Win32::Security::{
    CONTAINER_INHERIT_ACE, ImpersonateLoggedOnUser, OBJECT_INHERIT_ACE, RevertToSelf,
};

fn can_list_directory(token: &OwnedHandle, directory: &Path) -> Result<bool> {
    if unsafe { ImpersonateLoggedOnUser(token.as_raw_handle()) } == 0 {
        return Err(io::Error::last_os_error()).context("check the restricted search identity");
    }
    let result = fs::read_dir(directory).and_then(|mut entries| entries.next().transpose());
    if unsafe { RevertToSelf() } == 0 {
        return Err(io::Error::last_os_error()).context("restore the launcher identity");
    }
    match result {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == ErrorKind::PermissionDenied => Ok(false),
        Err(error) => Err(error).with_context(|| format!("open search directory {}", directory.display())),
    }
}

/// Restore read access within the chosen workspace for this sign-in only.
pub fn prepare_legacy_search_read_access(home: &Path, workspace: &Path, cwd: &Path) -> Result<()> {
    ensure!(cwd.starts_with(workspace), "search directory is outside the current workspace");
    let base = unsafe { OwnedHandle::from_raw_handle(get_current_token_for_restriction()?) };

    // WRITE_RESTRICTED consults capability SIDs for writes alone. This token
    // only probes directory reads and is never used to launch a process.
    let mut probe_capability = unsafe { world_sid()? };
    let token = unsafe {
        OwnedHandle::from_raw_handle(create_workspace_write_token_with_caps_from(
            base.as_raw_handle(),
            &[probe_capability.as_mut_ptr().cast()],
        )?)
    };
    let directories = [workspace, cwd];
    if can_list_directory(&token, workspace)? && (cwd == workspace || can_list_directory(&token, cwd)?) {
        return Ok(());
    }

    ensure!(workspace.parent().is_some(), "the search workspace must be a project directory");
    fs::create_dir_all(home)?;
    let serial = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(home.join("search-read-access.lock"))?;
    serial.lock()?;
    let mut logon = unsafe { get_logon_sid_bytes(base.as_raw_handle())? };
    for directory in directories {
        // Another search or the inherited workspace rule may already have
        // made this path readable. Preserve every existing deny ACE.
        if can_list_directory(&token, directory)? {
            continue;
        }
        fs::read_dir(directory).with_context(|| format!("read the selected project at {}", directory.display()))?;
        unsafe {
            grant_read_execute_aces(
                directory,
                &[logon.as_mut_ptr().cast()],
                CONTAINER_INHERIT_ACE | OBJECT_INHERIT_ACE,
            )?;
        }
        ensure!(can_list_directory(&token, directory)?,
            "the selected project's Windows permissions prevent sandboxed search in {}", directory.display());
    }
    Ok(())
}
