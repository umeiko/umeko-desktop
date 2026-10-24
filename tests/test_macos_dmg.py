"""Finder layout and fail-closed disk image verification without a macOS host."""
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import macos_dmg


class DiskImageTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('ds_store'), 'Install the pinned DMG build tools')
    def test_finder_shows_two_icons_in_icon_view(self):
        from ds_store import DSStore
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'.DS_Store'
            macos_dmg.finder_layout(path, 'Umeko.app')
            with DSStore.open(str(path)) as store:
                self.assertEqual(store['Umeko.app']['Iloc'], (160, 160))
                self.assertEqual(store['Applications']['Iloc'], (440, 160))
                self.assertEqual(store['.']['icvl'], (b'type', b'icnv'))
                self.assertFalse(store['.']['bwsp']['ShowToolbar'])

    @unittest.skipIf(os.name == 'nt', 'macOS native image pipeline')
    def test_failed_mounted_bundle_check_detaches_and_publishes_no_image(self):
        for fail in (False, True):
            with self.subTest(failed_signature=fail), tempfile.TemporaryDirectory() as temp:
                app = Path(temp)/'Umeko.app'; (app/'Contents').mkdir(parents=True)
                (app/'Contents/Info.plist').write_text('fixture')
                output = Path(temp)/'release.dmg'; calls = []; staging = None
                def run(args, check):
                    nonlocal staging
                    calls.append(args)
                    if args[0].endswith('ditto'):
                        staging = Path(args[2]); shutil.copytree(args[1], staging)
                    elif 'create' in args: Path(args[-1]).write_bytes(b'disk image fixture')
                    elif 'attach' in args:
                        mount = Path(args[args.index('-mountpoint')+1])
                        shutil.copytree(staging.parent, mount, dirs_exist_ok=True, symlinks=True)
                    elif args[0].endswith('codesign') and fail:
                        raise subprocess.CalledProcessError(1, args)
                with patch.object(macos_dmg.sys, 'platform', 'darwin'), patch.object(macos_dmg.subprocess, 'run', side_effect=run), patch.object(macos_dmg, 'finder_layout', side_effect=lambda p, _: Path(p).touch()):
                    if fail:
                        with self.assertRaises(subprocess.CalledProcessError): macos_dmg.create_dmg(app, output, 'Umeko')
                        self.assertFalse(output.exists())
                        self.assertFalse(output.with_suffix('.dmg.sha256').exists())
                    else:
                        result = macos_dmg.create_dmg(app, output, 'Umeko')
                        self.assertEqual(result['sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
                        self.assertEqual(output.with_suffix('.dmg.sha256').read_text().split(), [result['sha256'], output.name])
                self.assertEqual(sum('detach' in args for args in calls), 1)
