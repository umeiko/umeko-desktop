"""Windows-first publication keeps provenance and server digest verification."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import release_downloads, release_platforms, release_retention

ROOT = Path(__file__).resolve().parents[1]
COMMIT = 'a' * 40


class ReleasePlatformsTests(unittest.TestCase):
    def test_shared_checks_and_selected_native_builds_cannot_be_skipped(self):
        jobs = [dict(name=name, conclusion='success') for name in ('checks', 'Windows x64')]
        release_platforms.require_verified_jobs(jobs, {'windows-x64'})
        with self.assertRaises(ValueError):
            release_platforms.require_verified_jobs(jobs, release_platforms.ALL_PLATFORMS)
        for name in ('checks', 'Windows x64'):
            for conclusion in (None, 'failure', 'cancelled', 'skipped'):
                with self.subTest(name=name, conclusion=conclusion), self.assertRaises(ValueError):
                    release_platforms.require_verified_jobs([
                        dict(j, conclusion=conclusion) if j['name']==name else j for j in jobs], {'windows-x64'})
    def test_modes_keep_full_releases_default_and_windows_explicit(self):
        self.assertEqual(release_platforms.asset_count(release_platforms.select_platforms('all')), 19)
        self.assertEqual(release_platforms.select_platforms('windows'), {'windows-x64'})
        self.assertEqual(release_platforms.asset_count({'windows-x64'}), 6)
        for invalid in ('', 'macos', 'automatic'):
            with self.assertRaises(ValueError):
                release_platforms.select_platforms(invalid)

    def test_download_buttons_only_include_explicitly_selected_verified_platforms(self):
        names = ['Umeko-0.7.0-windows-x64-aaaaaaa.zip']
        block = release_downloads.download_buttons('umeiko/umeko-desktop', 'v0.7.0', names,
                                                   platforms={'windows-x64'})
        self.assertEqual(block.count('/releases/download/'), 1)
        self.assertNotIn('macos', block)
        with self.assertRaises(ValueError):
            release_downloads.download_buttons('umeiko/umeko-desktop', 'v0.7.0', names)


class WindowsPublishTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.fixture = self.root / 'fixture'
        native = self.fixture / 'Umeko-windows-x64'
        native.mkdir(parents=True)
        archive = native / 'Umeko-0.7.0-windows-x64-aaaaaaa.zip'
        archive.write_bytes(b'verified Windows fixture')
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        archive.with_name(archive.name + '.sha256').write_text(digest + '  ' + archive.name + '\n')
        self.report = dict(platform='windows-x64', archive=archive.name, sha256=digest,
                           build=dict(commit=COMMIT, version='0.7.0', node=dict(version='22.23.3')),
                           gui='passed', pi='passed', terminal='passed')
        self.metadata = native / 'build.json'
        self.metadata.write_text(json.dumps(self.report))
        sdk = self.fixture / 'Umeko-provider-development'
        sdk.mkdir()
        for name in ('umeko-provider-sdk-0.2.1.zip', 'develop-umeko-provider.zip'):
            (sdk / name).write_bytes(b'SDK fixture')
        self.release = None
        self.created = False
        self.run_conclusion = 'success'
        self.checks_conclusion = 'success'

    def check_output(self, command, **kwargs):
        self.assertEqual(command[0], 'gh')
        args = command[1:]
        if args[:2] == ['run', 'download']:
            shutil.copytree(self.fixture, Path(args[-1]))
            return ''
        if args[:2] == ['release', 'edit']:
            self.release['draft'] = False
            return ''
        self.assertEqual(args[0], 'api')
        if '--method' in args:
            self.assertEqual(args[args.index('--method') + 1], 'POST')
            self.release = json.loads(Path(args[-1]).read_text())
            self.release.update(id=1, assets=[], html_url='https://github.com/umeiko/umeko-desktop/releases/tag/v0.7.0')
            self.created = True
            return json.dumps(self.release)
        path = args[1].split('umeiko/umeko-desktop/')[1].split('?')[0]
        if path == 'actions/runs/777/jobs':
            return json.dumps(dict(jobs=[dict(name='checks',conclusion=self.checks_conclusion),
                                         dict(name='Windows x64',conclusion='success')]))
        if path == 'actions/runs/777':
            return json.dumps(dict(conclusion=self.run_conclusion, head_branch='main',
                                   head_repository=dict(full_name='umeiko/umeko-desktop'),
                                   event='push', path='.github/workflows/build.yml', head_sha=COMMIT))
        if path == 'releases':
            return json.dumps([] if self.release is None else [self.release])
        if path in ('releases/1', 'releases/latest'):
            return json.dumps(self.release)
        if path == 'git/ref/tags/v0.7.0':
            return json.dumps(dict(object=dict(sha=COMMIT)))
        raise AssertionError(path)

    def upload(self, command, **kwargs):
        self.assertEqual(command[:3], ['gh', 'release', 'upload'])
        path = Path(command[4])
        self.release['assets'].append(dict(name=path.name, state='uploaded', size=path.stat().st_size,
                                          digest='sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()))
        return subprocess.CompletedProcess(command, 0)

    def publish(self):
        work = self.root / 'work'
        work.mkdir()
        with contextlib.chdir(work), contextlib.redirect_stdout(io.StringIO()), \
             patch.dict(os.environ, GITHUB_REPOSITORY='umeiko/umeko-desktop', RELEASE_BUILD_RUN='777',
                        RELEASE_TAG='v0.7.0', RELEASE_PLATFORM_MODE='windows',
                        GITHUB_STEP_SUMMARY=str(self.root / 'summary.md')), \
             patch.dict(sys.modules, release_downloads=release_downloads,
                        release_platforms=release_platforms, release_retention=release_retention), \
             patch.object(subprocess, 'check_output', self.check_output), \
             patch.object(subprocess, 'run', self.upload), \
             patch.object(release_downloads, 'refresh_readmes') as refresh, \
             patch.object(release_retention, 'prune_releases') as prune:
            runpy.run_path(str(ROOT / 'scripts/publish-release.py'), run_name='__main__')
        return refresh, prune

    def test_verified_windows_main_run_publishes_six_assets_and_keeps_old_platform_releases(self):
        refresh, prune = self.publish()
        self.assertFalse(self.release['draft'])
        self.assertFalse(self.release['prerelease'])
        self.assertEqual(self.release['target_commitish'], COMMIT)
        self.assertEqual(len(self.release['assets']), 6)
        self.assertEqual(refresh.call_args.kwargs['platforms'], {'windows-x64'})
        prune.assert_not_called()
        self.assertIn('All 6 server-side asset digests verified', (self.root / 'summary.md').read_text())

    def test_failed_build_or_wrong_version_or_failed_gui_cannot_create_a_release(self):
        for field, value in (('version', '0.6.9'), ('gui', 'failed'), ('checks', 'failure')):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as work:
                self.root = Path(work)
                report = dict(self.report, build=dict(self.report['build']))
                if field == 'version': report['build']['version'] = value
                elif field == 'gui': report['gui'] = value
                self.checks_conclusion = value if field == 'checks' else 'success'
                self.metadata.write_text(json.dumps(report))
                with self.assertRaises((AssertionError,ValueError)):
                    self.publish()
                self.assertFalse(self.created)

    def test_independent_preview_upload_failure_does_not_invalidate_passed_builds(self):
        self.run_conclusion = 'failure'
        self.publish()
        self.assertEqual(len(self.release['assets']), 6)


if __name__ == '__main__':
    unittest.main()
