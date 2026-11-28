"""Offline Quick OCR setup regressions. Run with Python 3.12, no network."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from subprocess import CompletedProcess, run
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from zipfile import ZipFile


SETUP = (Path(__file__).resolve().parents[1] / "cowork-skills" /
         "local-image-ocr" / "scripts" / "setup_ocr.py")
SPEC = importlib.util.spec_from_file_location("setup_ocr", SETUP)
ocr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ocr)


class TestSetup(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="quick ocr 测试 ")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        old = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, old)
        self.folder = self.root / "wheels"
        self.folder.mkdir()
        self.lock = self.root / "lock.txt"
        self.pins = [tuple(line.split("==")) for line in ocr.REQUIREMENTS.read_text().splitlines()]

    def wheel(self, name, version, requires=None):
        name = name.replace("-", "_")
        stem = f"{name}-{version}"
        filename = self.folder / (stem + "-py3-none-any.whl")
        info = stem + ".dist-info/"
        with ZipFile(filename, "w") as archive:
            metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
            if requires:
                metadata += f"Requires-Dist: {requires}\n"
            archive.writestr(info + "METADATA", metadata + "\n")
            archive.writestr(info + "WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
            archive.writestr(info + "RECORD", "")
        return filename

    def make_source(self, dependency=None):
        entries = []
        lines = []
        for i, (name, version) in enumerate(self.pins):
            wheel = self.wheel(name, version, dependency if i == 0 else None)
            digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
            lines.append(f"{name}=={version} --hash=sha256:{digest}")
            entries.append({"url": f"https://wheels.example.invalid/{wheel.name}", "sha256": digest})
        self.lock.write_text("\n".join(lines), encoding="utf-8")
        return entries

    def check_stub(self):
        helper = self.root / "verify.py"
        helper.write_text(
            "from importlib.metadata import distributions\n"
            "import json\n"
            f"pins={dict(self.pins)!r}\n"
            "current={p.metadata['Name'].lower().replace('_','-'):p.version for p in distributions()}\n"
            "ok=all(current.get(k.lower())==v for k,v in pins.items())\n"
            "print(json.dumps({'ok':ok,'error':'engine' if not ok else None}))\n"
            "raise SystemExit(0 if ok else 1)\n", encoding="utf-8",
        )
        return mock.patch.object(ocr, "RECOGNIZE", helper)

    def test_lock_rejects_direct_urls_options_and_missing_pins(self):
        self.make_source()
        original = self.lock.read_text()
        for line in ("--index-url https://example.invalid", "-r more.txt",
                     "dependency @ https://example.invalid/d.whl",
                     "dependency==2.0; sys_platform == 'win32'", "dependency==2.0 \\"):
            with self.subTest(line=line):
                self.lock.write_text(original + "\n" + line)
                with self.assertRaises(ocr.SetupError) as caught:
                    ocr.offline_inputs(str(self.folder), str(self.lock))
                self.assertEqual(caught.exception.code, "invalid_offline_lock")
        self.lock.write_text("\n".join(original.splitlines()[1:]))
        with self.assertRaises(ocr.SetupError) as caught:
            ocr.offline_inputs(str(self.folder), str(self.lock))
        self.assertEqual(caught.exception.code, "offline_lock_missing_required_pins")

    def test_check_only_contract_does_not_prepare_empty_workspace(self):
        result = run([sys.executable, "-B", str(SETUP), "--check-only"],
                     capture_output=True, encoding="utf-8", check=True)
        self.assertEqual(json.loads(result.stdout), {"ok": True, "stage": "needs_setup"})
        self.assertFalse((self.root / ".umeko").exists())

    @unittest.skipUnless(os.name == "posix" and sys.version_info[:2] == (3, 12),
                         "POSIX workspace interpreter needs Python 3.12")
    def test_skill_probes_ready_workspace_without_python_on_path(self):
        shell = Path("/bin/sh")
        if not shell.is_file():
            self.skipTest("requires POSIX shell")
        self.make_source()
        with self.check_stub():
            python, _ = ocr.prepare(str(self.folder), str(self.lock))
            probe_scripts = self.root / "skill" / "scripts"
            probe_scripts.mkdir(parents=True)
            shutil.copyfile(SETUP, probe_scripts / "setup_ocr.py")
            shutil.copyfile(ocr.RECOGNIZE, probe_scripts / "recognize.py")
        skill = SETUP.parents[1] / "SKILL.md"
        first_posix_block = skill.read_text(encoding="utf-8").split("```sh\n", 1)[1].split("```", 1)[0]
        empty_path = self.root / "no system python"
        empty_path.mkdir()
        result = run([str(shell), "-c", first_posix_block], capture_output=True,
                     encoding="utf-8", check=True,
                     env={**os.environ, "PATH": str(empty_path),
                          "setup_script": str(probe_scripts / "setup_ocr.py")})
        self.assertEqual(json.loads(result.stdout),
                         {"ok": True, "stage": "ready", "python": str(python), "reused": True})

    @unittest.skipUnless(sys.version_info[:2] == (3, 12), "setup requires Python 3.12")
    def test_real_pip_offline_and_reuse_before_invalid_profile(self):
        self.make_source()
        with self.check_stub(), mock.patch.dict(os.environ, {
            "PIP_REQUIREMENT": str(self.root / "must-not-be-read.txt"),
            "PIP_INDEX_URL": "https://unused.example.invalid",
        }):
            python, reused = ocr.prepare(str(self.folder), str(self.lock))
            self.assertTrue(python.is_file())
            self.assertFalse(reused)
            self.assertEqual(ocr.prepare("invalid", None, "invalid.json"), (python, True))
            workspace = self.root / ".umeko"
            lock = workspace / "quick-ocr.setup.lock"
            lock.unlink()
            paths = set(workspace.rglob("*"))
            self.assertEqual(ocr.probe(), {"ok": True, "stage": "ready", "python": str(python), "reused": True})
            self.assertEqual(set(workspace.rglob("*")), paths)
            self.assertFalse(lock.exists())

    @unittest.skipUnless(sys.version_info[:2] == (3, 12), "setup requires Python 3.12")
    def test_real_pip_offline_missing_direct_dependency_does_not_fetch_and_reuse(self):
        self.make_source("missing @ https://must-not-be-contacted.example.invalid/missing.whl")
        with self.check_stub():
            for _ in range(2):
                with self.assertRaises(ocr.SetupError) as caught:
                    ocr.prepare(str(self.folder), str(self.lock))
                self.assertEqual((caught.exception.stage, caught.exception.code),
                                 ("verify", "offline_dependencies"))
                self.assertEqual(ocr.probe(), {"ok": True, "stage": "needs_setup"})

    def test_busy_workspace_does_not_start_second_installer(self):
        base = self.root / ".umeko"
        base.mkdir()
        with ocr.workspace_lock(base), mock.patch.object(ocr, "command") as command:
            with self.assertRaises(ocr.SetupError) as caught:
                ocr.prepare(None, None)
            self.assertEqual(caught.exception.code, "setup_busy")
            command.assert_not_called()
        with ocr.workspace_lock(base):
            pass

    def test_enterprise_only_uses_explicit_proxy_with_no_redirect_and_checks_sha(self):
        entries = self.make_source()
        config = self.root / "profile.json"
        config.write_text(json.dumps({"proxy": "http://proxy.example.invalid:8080", "auth": "ntlm",
                                      "lock": str(self.lock), "wheels": entries}))
        profile = ocr.read_profile(str(config))
        dest = self.root / "dest"
        dest.mkdir()

        def curl(args, stage, **kwargs):
            self.assertEqual(stage, "download")
            self.assertEqual(args[1], "--disable")
            if "--version" in args:
                return CompletedProcess(args, 0, "Features: SSPI NTLM", "")
            self.assertEqual(args[args.index("--proxy") + 1], "http://proxy.example.invalid:8080")
            self.assertEqual(args[args.index("--proxy-user") + 1], ":")
            self.assertIn("--proxy-ntlm", args)
            self.assertNotIn("--location", args)
            self.assertNotIn("--insecure", args)
            self.assertNotIn("--proxy-insecure", args)
            name = args[-1].rsplit("/", 1)[-1]
            Path(args[args.index("--output") + 1]).write_bytes((self.folder / name).read_bytes())
            return CompletedProcess(args, 0, "200:200", "")

        with mock.patch.object(ocr, "system_curl", return_value=Path("curl.exe")), \
                mock.patch.object(ocr, "command", side_effect=curl):
            ocr.fetch_wheels(profile, dest)
            self.assertEqual(len(list(dest.iterdir())), len(self.pins))
            (self.folder / profile[-1][0][0]).write_bytes(b"not an approved wheel")
            with self.assertRaises(ocr.SetupError) as caught:
                ocr.fetch_wheels(profile, dest)
            self.assertEqual(caught.exception.code, "wheel_hash_mismatch")


    def test_enterprise_407_redirect_and_unsupported_auth_stop_without_fallback(self):
        entries = self.make_source()
        config = self.root / "profile.json"
        config.write_text(json.dumps({"proxy": "http://proxy.example.invalid:8080", "auth": "ntlm",
                                      "lock": str(self.lock), "wheels": entries}))
        profile = ocr.read_profile(str(config))
        for features, response, expected, requests in (
                ("SSPI NTLM", (22, "000:407"), "proxy", 2),
                ("SSPI NTLM", (0, "302:200"), "enterprise_fetch_failed", 2),
                ("SSPI NTLM", (2, ""), "enterprise_auth_unsupported", 2),
                ("SSPI", None, "enterprise_auth_unsupported", 1)):
            with self.subTest(expected=expected):
                def curl(args, stage, **kwargs):
                    self.assertEqual(stage, "download")
                    if "--version" in args:
                        return CompletedProcess(args, 0, f"Features: {features}", "")
                    self.assertNotIn("--location", args)
                    self.assertEqual(args[args.index("--max-redirs") + 1], "0")
                    return CompletedProcess(args, *response, "private credential")
                with mock.patch.object(ocr, "system_curl", return_value=Path("curl.exe")), \
                        mock.patch.object(ocr, "command", side_effect=curl) as command:
                    with self.assertRaises(ocr.SetupError) as caught:
                        ocr.fetch_wheels(profile, self.folder)
                    self.assertEqual((caught.exception.stage, caught.exception.code), ("download", expected))
                    self.assertEqual(command.call_count, requests)

    @unittest.skipUnless(sys.version_info[:2] == (3, 12), "setup requires Python 3.12")
    def test_online_rejects_pip_scope_override(self):
        external = self.root / "external-site"
        with self.check_stub(), mock.patch.dict(os.environ, {"PIP_TARGET": str(external)}):
            with self.assertRaises(ocr.SetupError) as caught:
                ocr.prepare(None, None)
        self.assertEqual((caught.exception.stage, caught.exception.code),
                         ("source", "pip_install_scope_override"))
        self.assertFalse(external.exists())

    @unittest.skipUnless(sys.version_info[:2] == (3, 12), "setup requires Python 3.12")
    def test_online_requires_tls_verification(self):
        with self.check_stub(), mock.patch.dict(os.environ, {"PIP_TRUSTED_HOST": "pkgs.example.invalid"}):
            with self.assertRaises(ocr.SetupError) as caught:
                ocr.prepare(None, None)
        self.assertEqual((caught.exception.stage, caught.exception.code),
                         ("source", "certificate"))


if __name__ == "__main__":
    unittest.main()
