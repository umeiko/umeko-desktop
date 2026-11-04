import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.preview_release import collect_assets, digest, publish, select_matrix, verify_uploaded, verify_build_run


COMMIT = 'a' * 40


class PreviewReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.incoming = self.root / 'input'
        self.output = self.root / 'output'

    def fixture(self, platform='windows-x64'):
        folder = self.incoming / ('Preview-' + platform)
        folder.mkdir(parents=True)
        suffix = '.tar.gz' if platform == 'linux-x64' else '.zip'
        archive = folder / f'Umeko-0.6.9-{platform}-{COMMIT[:7]}{suffix}'
        archive.write_bytes(b'fixture package')
        checksum = digest(archive)
        archive.with_name(archive.name + '.sha256').write_text(checksum + '  ' + archive.name + '\n')
        report = dict(platform=platform, archive=archive.name, sha256=checksum,
                      gui='passed', pi='passed', terminal='passed', https='passed',
                      build=dict(commit=COMMIT, version='0.6.9', dirty=False))
        if platform.startswith('macos-'):
            disk = archive.with_suffix('.dmg')
            disk.write_bytes(b'fixture disk image')
            disk.with_name(disk.name + '.sha256').write_text(digest(disk) + '  ' + disk.name + '\n')
            report['diskImage'] = dict(name=disk.name, sha256=digest(disk), bytes=disk.stat().st_size)
        metadata = folder / 'build.json'
        metadata.write_text(json.dumps(report), encoding='utf-8')
        return metadata, report

    def test_only_selected_native_platforms_are_built(self):
        rows = select_matrix(dict(windows_x64=True, linux_x64=False, macos_arm64=True))['include']
        self.assertEqual([r['platform'] for r in rows], ['windows-x64', 'macos-arm64'])
        for inputs in ({}, dict(windows_x64=False), dict(windows_x64='false')):
            with self.assertRaisesRegex(ValueError, 'at least one'):
                select_matrix(inputs)

    def test_windows_only_release_does_not_require_other_platforms(self):
        self.fixture()
        self.assertEqual(collect_assets(self.incoming, self.output, ['windows-x64'], COMMIT), '0.6.9')
        self.assertEqual(len(list(self.output.iterdir())), 4)
        self.assertEqual(len((self.output / 'SHA256SUMS.txt').read_text().splitlines()), 3)

    def test_multiple_platforms_include_both_macos_archives(self):
        platforms = ['linux-x64', 'macos-arm64', 'macos-x64']
        for platform in platforms:
            self.fixture(platform)
        collect_assets(self.incoming, self.output, platforms, COMMIT)
        self.assertEqual(len(list(self.output.iterdir())), 14)
        self.assertEqual(len(list(self.output.glob('*.dmg'))), 2)

    def test_rejects_unverified_mismatched_or_corrupt_package(self):
        metadata, report = self.fixture()
        for field, value in [('gui', 'failed'), ('pi', 'failed'), ('terminal', 'failed'),
                             ('https', 'failed'), ('platform', 'linux-x64'),
                             ('archive', '../escape.zip'), ('sha256', '0' * 64)]:
            with self.subTest(field=field):
                broken = copy.deepcopy(report)
                broken[field] = value
                metadata.write_text(json.dumps(broken))
                with self.assertRaises(ValueError):
                    collect_assets(self.incoming, self.output, ['windows-x64'], COMMIT)
        for field, value in [('commit', 'b' * 40)]:
            broken = copy.deepcopy(report)
            broken['build'][field] = value
            metadata.write_text(json.dumps(broken))
            with self.assertRaises(ValueError):
                collect_assets(self.incoming, self.output, ['windows-x64'], COMMIT)

    def test_generated_icons_can_mark_verified_build_dirty(self):
        metadata, report = self.fixture()
        report['build']['dirty'] = True
        metadata.write_text(json.dumps(report))
        collect_assets(self.incoming, self.output, ['windows-x64'], COMMIT)
        copied = json.loads((self.output / 'Umeko-preview-windows-x64.json').read_text())
        self.assertTrue(copied['build']['dirty'])

    def test_reuse_requires_successful_selected_native_jobs(self):
        repo = 'umeiko/umeko-desktop'
        run = dict(head_repository=dict(full_name=repo), path='.github/workflows/preview.yml',
                   event='workflow_dispatch')
        for conclusion in ['success', 'failure', 'cancelled']:
            jobs = dict(jobs=[dict(name='Preview Windows x64', conclusion=conclusion)])
            with patch('scripts.preview_release.gh', side_effect=[json.dumps(run), json.dumps(jobs)]):
                if conclusion == 'success':
                    verify_build_run(repo, '1234', ['windows-x64'])
                else:
                    with self.assertRaisesRegex(ValueError, 'No successful'):
                        verify_build_run(repo, '1234', ['windows-x64'])
        run['path'] = '.github/workflows/other.yml'
        with patch('scripts.preview_release.gh', return_value=json.dumps(run)):
            with self.assertRaisesRegex(ValueError, 'Not a trusted'):
                verify_build_run(repo, '1234', ['windows-x64'])

    def test_missing_selected_platform_blocks_release(self):
        with self.assertRaises(FileNotFoundError):
            collect_assets(self.incoming, self.output, ['linux-x64'], COMMIT)

    def test_server_digest_and_asset_set_are_checked(self):
        self.fixture()
        collect_assets(self.incoming, self.output, ['windows-x64'], COMMIT)
        files = list(self.output.iterdir())
        rows = [dict(name=p.name, state='uploaded', size=p.stat().st_size,
                     digest='sha256:' + digest(p)) for p in files]
        verify_uploaded(dict(assets=rows), files)
        with self.assertRaises(ValueError):
            verify_uploaded(dict(assets=rows[:-1]), files)
        rows[0]['digest'] = 'sha256:' + '0' * 64
        with self.assertRaises(ValueError):
            verify_uploaded(dict(assets=rows), files)

    def test_publish_verifies_draft_before_publishing_and_never_marks_latest(self):
        calls, uploaded = [], []
        tag = 'preview-v0.6.9-1234-1'
        state = dict(draft=True, prerelease=True, target_commitish=COMMIT,
                     html_url='https://github.com/umeiko/umeko-desktop/releases/tag/' + tag,
                     assets=uploaded)

        def fake_gh(*args):
            calls.append(args)
            if args[:2] == ('release', 'upload'):
                path = Path(args[3])
                uploaded.append(dict(name=path.name, state='uploaded', size=path.stat().st_size,
                                     digest='sha256:' + digest(path)))
            if args[:2] == ('release', 'edit'):
                self.assertEqual(len(uploaded), 4)
                self.assertTrue(any(c[0] == 'api' and c[1].endswith('/releases/42') for c in calls))
                state['draft'] = False
            if args[:2] == ('release', 'view'):
                return json.dumps(dict(databaseId=42))
            if args[0] == 'api':
                self.assertNotIn('/releases/tags/', args[1], 'Draft tags are not published yet')
                return json.dumps(dict(object=dict(sha=COMMIT)) if '/git/ref/' in args[1] else state)
            return ''

        self.incoming = self.root / '.preview-release/input'
        self.fixture()
        environment = dict(GITHUB_REPOSITORY='umeiko/umeko-desktop', GITHUB_RUN_ID='1234',
                           GITHUB_RUN_ATTEMPT='1', PREVIEW_COMMIT=COMMIT,
                           PREVIEW_BUILD_RUN='1234',
                           PREVIEW_PLATFORMS='["windows-x64"]', PREVIEW_NOTES='Test preview',
                           GITHUB_STEP_SUMMARY=str(self.root / 'summary.md'))
        import os
        before = Path.cwd()
        try:
            os.chdir(self.root)
            with patch.dict(os.environ, environment), patch('scripts.preview_release.gh', fake_gh):
                publish()
        finally:
            os.chdir(before)
        for command in [('release', 'create'), ('release', 'edit')]:
            call = next(c for c in calls if c[:2] == command)
            self.assertIn('--prerelease', call)
            self.assertIn('--latest=false', call)
        self.assertTrue(all('latest' not in str(c) or '--latest=false' in c for c in calls))


if __name__ == '__main__':
    unittest.main()
