import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('release_downloads', Path(__file__).resolve().parents[1]/'scripts/release_downloads.py')
downloads = importlib.util.module_from_spec(spec)
spec.loader.exec_module(downloads)


def assets(prefix):
    return [prefix + '-' + platform + suffix for platform, suffix, *_ in downloads.PLATFORMS]


class ReleaseDownloadsTests(unittest.TestCase):
    def test_python_uses_actual_commit_named_packages_and_dmg(self):
        names = [name.replace('.zip', '-abcdef0.zip').replace('.dmg', '-abcdef0.dmg').replace('.tar.gz', '-abcdef0.tar.gz') for name in assets('Umeko-0.5.0')]
        block = downloads.download_buttons('umeiko/umeko-desktop', 'v0.5.0', names)
        self.assertEqual(block.count('/releases/download/v0.5.0/'), 4)
        self.assertIn('macos-arm64-abcdef0.dmg)', block)
        self.assertIn('windows-x64-abcdef0.zip)', block)

    def test_minimal_links_never_resolve_to_standard_edition(self):
        names = assets('UmekoCpp-v0.5.0-minimal') + assets('UmekoCpp-v0.5.0')
        block = downloads.download_buttons('umeiko/umeko-desktop-cpp', 'v0.5.0-minimal', names)
        self.assertEqual(block.count('/releases/download/v0.5.0-minimal/'), 4)
        self.assertIn('Minimal / 精简版', block)

    def test_missing_or_ambiguous_package_stops_link_generation(self):
        names = assets('UmekoCpp-v0.5.0')
        for invalid in (names[:-1], names + [names[0]]):
            with self.assertRaises(ValueError):
                downloads.download_buttons('umeiko/umeko-desktop-cpp', 'v0.5.0', invalid)

    def test_release_notes_keep_prose_and_are_idempotent(self):
        original = '# Release\n\nChanges and validation.\n'
        args = ('umeiko/umeko-desktop-cpp', 'v0.5.0', assets('UmekoCpp-v0.5.0'))
        result = downloads.release_notes(original, *args)
        self.assertTrue(result.startswith('# Release\n\n<!--'))
        self.assertTrue(result.endswith('Changes and validation.\n'))
        self.assertEqual(downloads.release_notes(result, *args), result)

    def test_readme_replacement_preserves_other_content_and_requires_marker(self):
        original = 'Intro\n<!-- umeko-downloads:standard:start -->old<!-- umeko-downloads:standard:end -->\nUser edits'
        self.assertEqual(downloads.replace_block(original, 'new', 'standard'), 'Intro\nnew\nUser edits')
        with self.assertRaises(ValueError): downloads.replace_block('No marker', 'new', 'standard')

    def test_unchanged_remote_readme_needs_no_commit(self):
        block = downloads.download_buttons('umeiko/umeko-desktop-cpp', 'v0.5.0', assets('UmekoCpp-v0.5.0'), 'standard')
        calls = []
        downloads.refresh_readmes('umeiko/umeko-desktop-cpp', 'v0.5.0', assets('UmekoCpp-v0.5.0'),
                                  lambda _: {'content': base64.b64encode(block.encode()).decode()}, lambda *args: calls.append(args))
        self.assertFalse(calls)

    def test_refresh_uses_current_sha_and_preserves_remote_edits(self):
        old = 'Current introduction\n<!-- umeko-downloads:standard:start -->old<!-- umeko-downloads:standard:end -->\nCustom footer'
        calls = []
        with tempfile.TemporaryDirectory() as folder, patch.object(downloads, 'Path', lambda _: Path(folder)/'payload.json'):
            def commit(*args): calls.append(json.loads(Path(args[-1]).read_text(encoding='utf-8')))
            downloads.refresh_readmes('umeiko/umeko-desktop-cpp', 'v0.5.0', assets('UmekoCpp-v0.5.0'),
                                      lambda _: {'sha': 'current-blob', 'content': base64.b64encode(old.encode()).decode()}, commit)
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0]['branch'], calls[0]['sha']), ('main', 'current-blob'))
        new = base64.b64decode(calls[0]['content']).decode()
        self.assertTrue(new.startswith('Current introduction\n'))
        self.assertTrue(new.endswith('\nCustom footer'))
        self.assertIn('[skip ci]', calls[0]['message'])
