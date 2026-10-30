"""CodeArts plugin account using the official China CLI and SDK protected secrets.

The official installer is executed in full, windowlessly, as in the local
followup1 installer experiment. Only newly downloaded credentials CSVs are read;
CodeArts' own stored-login files are never accessed. No Qt dependency is needed.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading

from .i18n import tr
from .legacy_vault import WindowsLegacyVault


INSTALLER_URL = "https://cnnorth4-cloudide-marketplace.obs.cn-north-4.myhuaweicloud.com/codearts/cli_tui/install_script/install.ps1"
SERVICE = "umeko-desktop-codearts"
_MODEL_ROW = re.compile(r"^[\s│|]*([A-Za-z0-9_.-]+/[A-Za-z0-9_.:-]+)(?:\s|[│|]|$)")
_SECRET_NAMES = {"CODEARTS_CLI_AK", "CODEARTS_CLI_SK", "HW_ACCESS_KEY", "HW_SECRET_KEY", "HW_SECURITY_TOKEN"}


def parse_credentials(text: str, *, csv_only: bool = False, language="zh") -> tuple[str, str]:
    """Accept a Huawei CSV (header order independent) or AK followed by SK.

    Errors deliberately contain no input text. Pasted labels use either the
    official environment names or Access Key Id / Secret Access Key. Automatic
    download detection requires CSV headers; the two-value fallback is private
    paste input only.
    """
    text = text.lstrip("\ufeff").strip()
    if not text:
        raise ValueError(tr(language, "empty"))
    aliases = {
        "accesskeyid": "ak", "accesskey": "ak", "ak": "ak", "codeartscliak": "ak",
        "secretaccesskey": "sk", "secretkey": "sk", "sk": "sk", "codeartsclisk": "sk",
    }

    def field(value):
        return aliases.get(re.sub(r"[^a-z0-9]", "", value.lower().lstrip("\ufeff")))

    rows = list(csv.reader(io.StringIO(text)))
    if rows:
        header = [field(value) for value in rows[0]]
        if "ak" in header and "sk" in header:
            data = [row for row in rows[1:] if any(value.strip() for value in row)]
            if len(data) != 1 or len(data[0]) != len(header):
                raise ValueError(tr(language, "one_row"))
            ak, sk = (data[0][header.index(name)].strip() for name in ("ak", "sk"))
            if ak and sk:
                return ak, sk
            raise ValueError(tr(language, "missing"))
    if csv_only:
        raise ValueError(tr(language, "headers"))
    labeled = {}
    for line in text.splitlines():
        pair = re.split(r"\s*[:=]\s*", line, maxsplit=1)
        if len(pair) == 2 and field(pair[0]):
            labeled[field(pair[0])] = pair[1].strip().strip('"\'')
    if set(labeled) == {"ak", "sk"} and all(labeled.values()):
        return labeled["ak"], labeled["sk"]
    values = re.split(r"[\s,;]+", text)
    if len(values) == 2 and all(values) and not any(field(value) for value in values):
        return values[0].strip('"\''), values[1].strip('"\'')
    raise ValueError(tr(language, "invalid"))


class CodeartsAccount:
    """Synchronous operations intended to run in the UI's existing worker thread.

    runner, when supplied, accepts args, env, cwd and timeout. The SDK
    context owns protected secrets. Status dictionaries never include keys.
    """

    def __init__(self, context, downloads_dir=None, legacy_store=None, runner=None, progress=None):
        self.context = context
        self.profile_dir = Path(context.state_dir).resolve()
        self.downloads_dir = Path(downloads_dir or getattr(context, "downloads_dir", None) or Path.home() / "Downloads")
        self._store = context.secrets
        self._legacy_store = legacy_store
        self._runner = runner
        self._progress = progress or getattr(context, "progress", None) or (lambda message: None)
        self._cli = None
        self._baseline = None
        self._baseline_ids = set()
        self._attempted = set()
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._processes = set()
        self.migration_status = "not_checked"

    def _text(self, key):
        return tr(getattr(self.context, "language", "zh"), key)

    def _status(self, ready=False, models=(), message=""):
        return {"ready": bool(ready), "models": list(models), "message": message}

    @staticmethod
    def _pair(saved):
        if isinstance(saved, dict):
            ak, sk = saved.get("ak"), saved.get("sk")
            if isinstance(ak, str) and isinstance(sk, str) and ak and sk:
                return ak, sk
        return None

    def _legacy(self):
        if self._legacy_store is None:
            self._legacy_store = WindowsLegacyVault()
        return self._legacy_store

    def _finish_migration(self, saved):
        username = saved.get("legacy_profile")
        if not username or username != str(getattr(self.context, "profile_dir", None)):
            return
        try:
            self._legacy().delete_password(SERVICE, username)
        except Exception:
            # Protected credentials already exist. Keep the cleanup marker so a
            # later product attempt can retry; never re-read or overwrite them.
            self.migration_status = "cleanup_pending"
            return
        self.migration_status = "migrated"
        try:
            self._store.set("account", {"ak": saved["ak"], "sk": saved["sk"]})
        except Exception:
            # The old entry is already gone. Leaving the marker is safe and
            # allows the product to remove it on its next credential lookup.
            pass

    def _credentials(self):
        saved = self._store.get("account")
        credentials = self._pair(saved)
        if credentials:
            if self.migration_status != "migrated":
                self.migration_status = "existing"
            self._finish_migration(saved)
            return credentials
        original = getattr(self.context, "profile_dir", None)
        # A present SDK entry is authoritative, even when malformed. Never
        # replace it with an old account or search other profile paths.
        if saved is None and original is not None:
            if not self._store.get("legacy_checked", False):
                username = str(original)
                raw = self._legacy().get_password(SERVICE, username)
                if raw:
                    old = json.loads(raw)
                    credentials = self._pair(old)
                    if credentials:
                        saved = {"ak": credentials[0], "sk": credentials[1], "legacy_profile": username}
                        # The old entry remains intact when protected storage fails.
                        self._store.set("account", saved)
                        self._finish_migration(saved)
                        return credentials
                self._store.set("legacy_checked", True)
            self.migration_status = "not_found"
        ak, sk = os.environ.get("CODEARTS_CLI_AK"), os.environ.get("CODEARTS_CLI_SK")
        return (ak, sk) if ak and sk else None

    def _find_cli(self):
        configured = (getattr(self.context, "config", None) or {}).get("cliPath")
        if configured:
            launcher = Path(configured).expanduser()
            if launcher.is_file():
                return launcher.resolve()
        # The official China installer uses this tree; do not inspect login data.
        names = ("codearts.cmd", "codearts.exe", "codearts") if os.name == "nt" else ("codearts",)
        for name in names:
            launcher = Path.home() / ".codeartsdoer" / "installers" / name
            if launcher.is_file():
                return launcher
        found = shutil.which("codearts.cmd") if os.name == "nt" else None
        found = found or shutil.which("codearts")
        return Path(found) if found else None

    def _base_env(self):
        return {key: value for key, value in os.environ.items() if key.upper() not in _SECRET_NAMES}

    def _child_env(self, credentials):
        env = self._base_env()
        env["CODEARTS_CLI_AK"], env["CODEARTS_CLI_SK"] = credentials
        env["BROWSER"] = "false"
        return env

    def _command(self, args):
        if not self._cli:
            raise RuntimeError(self._text("cli_unavailable"))
        if os.name != "nt":
            return [str(self._cli), *args]
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(self._cli), *args]

    def _spawn(self, command, *, env, cwd, **kwargs):
        with self._lock:
            if self._cancelled.is_set():
                raise RuntimeError(self._text("cancelled"))
            process = subprocess.Popen(command, env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **kwargs)
            self._processes.add(process)
        return process

    def _run(self, command, *, env, cwd, timeout):
        if self._cancelled.is_set():
            raise RuntimeError(self._text("cancelled"))
        if self._runner:
            return self._runner(command, env=env, cwd=cwd, timeout=timeout)
        process = self._spawn(command, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            self._terminate_owned(process)
            process.communicate()
            raise
        finally:
            with self._lock:
                self._processes.discard(process)

    def _ensure_cli(self):
        if self._cli:
            return True
        self._cli = self._find_cli()
        if self._cli:
            return True
        self._progress(self._text("installing"))
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        # Full official script: its existing-file guards preserve the user's
        # permission/sandbox configs. Private TEMP confines installer cleanup.
        with tempfile.TemporaryDirectory(prefix="codearts-install-", dir=self.profile_dir) as temp:
            script = (
                "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; "
                f"$url='{INSTALLER_URL}'; "
                "$file=Join-Path $env:TEMP 'install.ps1'; "
                "Invoke-WebRequest -Uri $url -OutFile $file -UseBasicParsing; "
                "& ([scriptblock]::Create((Get-Content -LiteralPath $file -Raw -Encoding UTF8)))"
            )
            encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
            env = self._base_env()
            env["TEMP"] = env["TMP"] = temp
            result = self._run(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                                "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
                               env=env, cwd=temp, timeout=600)
            if result.returncode or self._cancelled.is_set():
                return False
        self._cli = self._find_cli()
        if self._cli:
            self._progress(self._text("installed"))
        return bool(self._cli)

    def _verify(self, credentials):
        if not self._ensure_cli():
            return self._status(message=self._text("install_failed"))
        self._progress(self._text("verifying"))
        # The official .cmd rewrites KERNEL paths to the user's global profile.
        # Reuse the service's private config and enabled folder-trust setup,
        # then invoke the installed executable directly for this verification.
        from .server import CodeartsServer
        private = CodeartsServer(self, self.profile_dir / "account-verification")
        work = private.prepare_directory()
        cli = Path(self._cli)
        executable = cli if cli.suffix.lower() == ".exe" or os.name != "nt" else cli.parent / "bin" / "codearts.exe"
        result = self._run([str(executable), "models"], env=private._environment(credentials, "", ""),
                           cwd=str(work), timeout=90)
        output = result.stdout.decode("utf-8", errors="replace") if isinstance(result.stdout, bytes) else result.stdout or ""
        output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output)
        # Exit 0 alone is insufficient: this CLI also exits 0 for missing auth.
        # Never propagate stdout/stderr, exception text, or credential values.
        models = set()
        for line in output.splitlines():
            # Official output may contain a display-name column after the ID.
            # Read only the anchored first field, never propagate other columns.
            match = _MODEL_ROW.match(line)
            if match and not any(secret in match[1] for secret in credentials):
                models.add(match[1])
        models = sorted(models)
        if result.returncode or not models or self._cancelled.is_set():
            return self._status(message=self._text("verify_failed"))
        return self._status(True, models, self._text("connected"))

    def begin(self):
        self._cancelled.clear()
        if self._baseline is None:
            self.start_import()
        try:
            credentials = self._credentials()
            if not self._ensure_cli():
                return self._status(message=self._text("install_failed"))
            if not credentials:
                return self._status(message=self._text("guide"))
            return self._verify(credentials)
        except Exception:
            return self._status(message=self._text("connect_failed"))

    def start_import(self):
        self._cancelled.clear()
        files = list(self.downloads_dir.iterdir()) if self.downloads_dir.is_dir() else []
        self._baseline = {path.resolve() for path in files}
        self._baseline_ids = set()
        for path in files:
            try:
                info = path.stat()
                if info.st_ino:
                    self._baseline_ids.add((info.st_dev, info.st_ino))
            except OSError:
                pass
        self._attempted.clear()
        return self._status(message=self._text("guide"))

    def _download_candidates(self):
        if not self.downloads_dir.is_dir():
            return []
        return sorted(path for path in self.downloads_dir.iterdir()
                      if path.suffix.lower() == ".csv" and path.is_file() and not path.is_symlink())

    def poll_downloads(self):
        if self._baseline is None or self._cancelled.is_set():
            return None
        try:
            for path in self._download_candidates():
                identity = path.resolve()
                info = path.stat()
                if identity in self._baseline or identity in self._attempted or (info.st_dev, info.st_ino) in self._baseline_ids:
                    continue
                # A browser may create an empty target before finishing download.
                if not info.st_size or path.with_name(path.name + ".crdownload").exists():
                    continue
                self._attempted.add(identity)
                text = path.read_text(encoding="utf-8-sig")
                try:
                    credentials = parse_credentials(text, csv_only=True, language=getattr(self.context, "language", "zh"))
                except ValueError:
                    # Unrelated CSVs must never reach the lenient paste parser
                    # or be removed. Keep looking for an actual key download.
                    continue
                result = self._import_credentials(credentials)
                if result["ready"]:
                    try:
                        path.unlink()
                        result["message"] = self._text("deleted_csv")
                    except OSError:
                        result["message"] = self._text("delete_csv")
                return result
        except Exception:
            return self._status(message=self._text("read_failed"))
        return None

    def import_text(self, text):
        try:
            credentials = parse_credentials(text, language=getattr(self.context, "language", "zh"))
        except Exception:
            return self._status(message=self._text("invalid"))
        return self._import_credentials(credentials)

    def _import_credentials(self, credentials):
        try:
            result = self._verify(credentials)
            if self._cancelled.is_set():
                return self._status(message=self._text("cancelled_file"))
            if result["ready"]:
                self._store.set("account", dict(zip(("ak", "sk"), credentials)))
                result["message"] = self._text("saved")
            return result
        except Exception:
            return self._status(message=self._text("save_failed"))

    def launch(self, args, **kwargs):
        """Launch an owned CodeArts child; credentials stay inside its env.

        Caller may provide stdout/stderr for the runtime protocol, but cannot
        replace env, stdin or creationflags. Call close() to stop owned children.
        """
        credentials = self._credentials()
        if not credentials or not self._ensure_cli():
            raise RuntimeError(self._text("connect_first"))
        cwd = kwargs.pop("cwd", str(self.profile_dir))
        return self._spawn(self._command(list(args)), env=self._child_env(credentials), cwd=cwd, **kwargs)

    def _terminate_owned(self, process):
        with self._lock:
            if process not in self._processes:
                return
        if process.poll() is None:
            if os.name == "nt":
                # This PID belongs to us; /T also stops the official .cmd
                # launcher's executable, never an unrelated CodeArts process.
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def cancel(self):
        self._cancelled.set()
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            self._terminate_owned(process)
            with self._lock:
                self._processes.discard(process)

    close = cancel
