"""Prepare the workspace-local Quick OCR engine after receiving an image."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit


SKILL = Path(__file__).resolve().parents[1]
REQUIREMENTS = SKILL / "requirements.txt"
RECOGNIZE = SKILL / "scripts" / "recognize.py"
PINS = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9][A-Za-z0-9.!+_-]*)")
HASHED_LINE = re.compile(PINS.pattern + r"(?:[ \t]+--hash=sha256:[0-9a-fA-F]{64})+")
INSTALL_SCOPE = re.compile(r"^(?:global|install|:env:)\.(?:target|prefix|root|user)\s*=", re.I | re.M)
INSECURE_PIP = re.compile(r"^(?:global|install|:env:)\.trusted-host\s*=", re.I | re.M)
OFFLINE_LIMIT = 256 * 1024


class SetupError(Exception):
    def __init__(self, stage, code):
        self.stage = stage
        self.code = code


def command(argv, stage, *, env=None, timeout=60):
    try:
        return subprocess.run(
            argv, env=env, capture_output=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SetupError(stage, "timeout") from exc
    except OSError as exc:
        raise SetupError(stage, "local_access") from exc


def check_engine(python):
    result = command([str(python), "-I", "-B", str(RECOGNIZE), "--check"], "check")
    try:
        status = json.loads(result.stdout)
        if isinstance(status, dict):
            if result.returncode == 0 and status.get("ok") is True:
                return "ready"
            if status.get("error") == "weights":
                return "weights"
    except ValueError:
        pass
    return "engine"


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def read_lock(lock):
    path = Path(lock)
    try:
        if not path.is_absolute() or not path.is_file():
            raise SetupError("source", "invalid_offline_path")
        with path.open("rb") as file:
            data = file.read(OFFLINE_LIMIT + 1)
        if len(data) > OFFLINE_LIMIT:
            raise SetupError("source", "invalid_offline_lock")
        lines = []
        pins = {}
        for entry in data.decode("utf-8").splitlines():
            entry = entry.strip()
            if not entry or entry.startswith("#"):
                continue
            parsed = HASHED_LINE.fullmatch(entry)
            if not parsed:
                raise SetupError("source", "invalid_offline_lock")
            name, version = normalize(parsed[1]), parsed[2]
            if name in pins:
                raise SetupError("source", "invalid_offline_lock")
            pins[name] = version
            lines.append(entry)
        for entry in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
            parsed = PINS.fullmatch(entry.strip())
            if not parsed or pins.get(normalize(parsed[1])) != parsed[2]:
                raise SetupError("source", "offline_lock_missing_required_pins")
        return "\n".join(lines) + "\n"
    except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
        raise SetupError("source", "invalid_offline_lock") from exc


def offline_inputs(wheelhouse, lock):
    if not wheelhouse or not lock:
        raise SetupError("source", "offline_pair_required")
    directory = Path(wheelhouse)
    if not directory.is_absolute() or not directory.is_dir():
        raise SetupError("source", "invalid_offline_path")
    return directory.resolve(strict=True), read_lock(lock)


def parse_url(value, schemes):
    if not isinstance(value, str) or not value.isascii() or any(ch.isspace() for ch in value):
        raise ValueError
    parsed = urlsplit(value)
    if (parsed.scheme not in schemes or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or parsed.port == 0 or any(ch in value for ch in "\\%?#{[]}")):
        raise ValueError
    return parsed


def read_profile(profile):
    try:
        path = Path(profile)
        if not path.is_absolute() or not path.is_file():
            raise ValueError
        with path.open("rb") as file:
            data = file.read(OFFLINE_LIMIT + 1)
        if len(data) > OFFLINE_LIMIT:
            raise ValueError
        config = json.loads(data)
        if not isinstance(config, dict) or set(config) - {"proxy", "auth", "lock", "wheels", "ca"}:
            raise ValueError
        proxy = config["proxy"]
        if parse_url(proxy, {"http", "https"}).path not in {"", "/"}:
            raise ValueError
        auth = config["auth"]
        if auth not in ("negotiate", "ntlm"):
            raise ValueError
        lock = read_lock(config["lock"])
        ca = config.get("ca")
        if ca is not None and (not Path(ca).is_absolute() or not Path(ca).is_file()):
            raise ValueError
        wheels = config["wheels"]
        if not isinstance(wheels, list) or not 1 <= len(wheels) <= 150:
            raise ValueError
        names = set()
        hashes = set()
        files = []
        for wheel in wheels:
            if not isinstance(wheel, dict) or set(wheel) != {"url", "sha256"}:
                raise ValueError
            url = wheel["url"]
            name = parse_url(url, {"https"}).path.rsplit("/", 1)[-1]
            digest = wheel["sha256"].lower()
            if (not re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", name, re.I)
                    or not re.fullmatch(r"[0-9a-f]{64}", digest) or name.lower() in names):
                raise ValueError
            names.add(name.lower())
            hashes.add(digest)
            files.append((name, url, digest))
        hash_sets = [set(re.findall(r"sha256:([0-9a-fA-F]{64})", line.lower()))
                     for line in lock.splitlines()]
        if any(not hashes.intersection(group) for group in hash_sets) or hashes - set().union(*hash_sets):
            raise ValueError
        return proxy, auth, lock, ca, files
    except (OSError, ValueError, AttributeError, KeyError, TypeError) as exc:
        raise SetupError("source", "invalid_enterprise_profile") from exc


def system_curl():
    if os.name != "nt":
        raise SetupError("source", "enterprise_windows_required")
    root = Path(os.environ.get("SystemRoot", ""))
    executable = root / "System32" / "curl.exe"
    if not root.is_absolute() or not executable.is_file():
        raise SetupError("source", "enterprise_curl_missing")
    return executable


def fetch_wheels(profile, directory):
    curl = system_curl()
    proxy, auth, lock, ca, wheels = profile
    info = command([str(curl), "--disable", "--version"], "download")
    features = set(info.stdout.upper().split())
    if info.returncode or "SSPI" not in features or (auth == "ntlm" and "NTLM" not in features):
        raise SetupError("download", "enterprise_auth_unsupported")
    for name, url, digest in wheels:
        wheel = directory / name
        args = [
            str(curl), "--disable", "--globoff", "--silent", "--show-error", "--fail",
            "--proto", "=https", "--max-redirs", "0", "--noproxy", "",
            "--proxy", proxy, "--proxy-" + auth, "--proxy-user", ":",
            "--connect-timeout", "15", "--max-time", "180", "--max-filesize", str(256 * 1024 * 1024),
            "--output", str(wheel), "--write-out", "%{http_code}:%{http_connect}",
        ]
        if ca:
            args.extend(("--cacert", ca, "--proxy-cacert", ca))
        # Do not accept transport defaults from a global curl config or other proxies.
        env = {key: value for key, value in os.environ.items()
               if key.upper() not in {"CURL_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR", "SSLKEYLOGFILE"}}
        result = command(args + ["--url", url], "download", env=env, timeout=185)
        status, _, connect = result.stdout.strip().partition(":")
        if connect == "407" or status == "407":
            raise SetupError("download", "proxy")
        if result.returncode in (35, 51, 58, 60, 77, 83, 90, 91):
            raise SetupError("download", "certificate")
        if connect in ("401", "403") or status in ("401", "403"):
            raise SetupError("download", "source_access")
        if result.returncode == 2:
            raise SetupError("download", "enterprise_auth_unsupported")
        if result.returncode or status != "200" or not wheel.is_file():
            raise SetupError("download", "enterprise_fetch_failed")
        with wheel.open("rb") as file:
            actual = hashlib.file_digest(file, "sha256").hexdigest()
        if actual != digest:
            raise SetupError("download", "wheel_hash_mismatch")
    return directory, lock


def installation_error(result):
    output = ((result.stderr or "") + "\n" + (result.stdout or "")).lower()
    if "407" in output or "proxyerror" in output or "proxy authentication" in output:
        return "proxy"
    if "certificate_verify_failed" in output or "certificate verify failed" in output or "sslerror" in output:
        return "certificate"
    if "401" in output or "403" in output:
        return "source_access"
    if "connection" in output or "timed out" in output or "name resolution" in output:
        return "network"
    if "no matching distribution" in output or "could not find a version" in output:
        return "wheels_unavailable"
    if "hashes" in output:
        return "wheel_hash_mismatch"
    return "pip_failed"


def is_link(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


@contextmanager
def workspace_lock(base):
    path = base / "quick-ocr.setup.lock"
    if is_link(path) or (path.exists() and not path.is_file()):
        raise SetupError("prepare", "invalid_workspace_environment")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    # Do not unlink an advisory lock: processes must always lock the same file.
    with os.fdopen(fd, "r+b") as handle:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SetupError("prepare", "setup_busy") from exc
        yield


def prepare(wheelhouse, lock, enterprise_profile=None):
    base = Path.cwd() / ".umeko"
    if is_link(base) or (base.exists() and not base.is_dir()):
        raise SetupError("prepare", "invalid_workspace_environment")
    base.mkdir(exist_ok=True)
    with workspace_lock(base):
        return prepare_locked(base, wheelhouse, lock, enterprise_profile)


def workspace_environment(base):
    target = base / "quick-ocr"
    python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    for directory in (base, target, python.parent):
        if is_link(directory) or (directory.exists() and not directory.is_dir()):
            raise SetupError("prepare", "invalid_workspace_environment")
    if os.name == "nt" and is_link(python):
        raise SetupError("prepare", "invalid_workspace_environment")
    cfg = target / "pyvenv.cfg"
    incomplete = target / ".install-incomplete"
    if is_link(incomplete) or (incomplete.exists() and not incomplete.is_file()):
        raise SetupError("prepare", "invalid_workspace_environment")
    # pip must never run against a base interpreter at this path.
    if python.is_file() and (not cfg.is_file() or is_link(cfg)):
        raise SetupError("prepare", "invalid_workspace_environment")
    return target, python, incomplete


def probe():
    base = Path.cwd() / ".umeko"
    _, python, incomplete = workspace_environment(base)
    if (python.is_file() and not incomplete.exists()
            and check_engine(python) == "ready" and not incomplete.exists()):
        return {"ok": True, "stage": "ready", "python": str(python), "reused": True}
    return {"ok": True, "stage": "needs_setup"}


def prepare_locked(base, wheelhouse, lock, enterprise_profile):
    target, python, incomplete = workspace_environment(base)
    status = check_engine(python) if python.is_file() else "engine"
    if status == "ready" and not incomplete.exists():
        return python, True

    offline = wheelhouse is not None or lock is not None
    if enterprise_profile is not None and offline:
        raise SetupError("source", "conflicting_sources")
    profile = read_profile(enterprise_profile) if enterprise_profile is not None else None
    if profile:
        system_curl()
    source = offline_inputs(wheelhouse, lock) if offline else None
    if not python.is_file():
        if sys.version_info[:2] != (3, 12):
            raise SetupError("prepare", "python_3_12_required")
        result = command([sys.executable, "-I", "-m", "venv", str(target)], "prepare")
        if result.returncode or not python.is_file():
            raise SetupError("prepare", "venv_failed")
        status = check_engine(python)
        if status == "ready" and not incomplete.exists():
            return python, True

    pip = [str(python), "-I", "-m", "pip", "--require-virtualenv",
           "--disable-pip-version-check", "--no-input"]
    args = ["install", "--only-binary=:all:"]
    if status == "weights" or source or profile:
        args.extend(("--force-reinstall", "--no-cache-dir"))
    if source or profile:
        # No inherited pip sources, no remote metadata/dependencies, no cache.
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PIP_")}
        env["PIP_CONFIG_FILE"] = os.devnull
        with tempfile.TemporaryDirectory(prefix="install-", dir=target) as temp:
            scratch = Path(temp)
            if profile:
                wheel_directory = scratch / "wheels"
                wheel_directory.mkdir()
                source = fetch_wheels(profile, wheel_directory)
            directory, data = source
            snapshot = scratch / "offline-lock.txt"
            snapshot.write_text(data, encoding="utf-8")
            incomplete.touch()
            result = command(
                pip + args + ["--no-index", "--no-deps",
                              "--require-hashes", "--find-links", directory.as_uri(),
                              "-r", str(snapshot)],
                "install", env=env, timeout=600,
            )
        if result.returncode:
            raise SetupError("install", installation_error(result))
        if command(pip + ["check"], "verify", env=env).returncode:
            raise SetupError("verify", "offline_dependencies")
    else:
        config = command(pip + ["config", "list"], "source")
        if config.returncode:
            raise SetupError("source", "pip_config_failed")
        if INSTALL_SCOPE.search(config.stdout):
            raise SetupError("source", "pip_install_scope_override")
        if INSECURE_PIP.search(config.stdout):
            raise SetupError("source", "certificate")
        incomplete.touch()
        result = command(pip + args + ["-r", str(REQUIREMENTS)], "install", timeout=600)
        if result.returncode:
            raise SetupError("install", installation_error(result))

    status = check_engine(python)
    if status != "ready":
        raise SetupError("verify", status)
    incomplete.unlink(missing_ok=True)
    return python, False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="Check readiness without installing or writing")
    parser.add_argument("--wheelhouse", default=os.getenv("UMEKO_QUICK_OCR_WHEELHOUSE"))
    parser.add_argument("--lock", default=os.getenv("UMEKO_QUICK_OCR_LOCK"))
    parser.add_argument("--enterprise-profile", default=os.getenv("UMEKO_QUICK_OCR_ENTERPRISE_PROFILE"))
    options = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        if options.check_only:
            result = probe()
        else:
            python, reused = prepare(options.wheelhouse, options.lock, options.enterprise_profile)
            result = {"ok": True, "stage": "ready", "python": str(python), "reused": reused}
    except SetupError as error:
        result = {"ok": False, "stage": error.stage, "code": error.code}
    except OSError:
        result = {"ok": False, "stage": "prepare", "code": "local_access"}
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
