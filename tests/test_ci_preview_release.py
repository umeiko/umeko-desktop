"""Exercise rolling Preview publication with offline packages and a fake GitHub API."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts.ci_preview_release import publish, verify_ci_run
from scripts.preview_release import digest

COMMIT = 'a' * 40
REPO = 'umeiko/umeko-desktop'


class GitHubFixture:
    def __init__(self, package):
        self.package = package
        self.calls = []
        self.run = dict(head_repository=dict(full_name=REPO), path='.github/workflows/build.yml',
                        event='push', head_branch='main', head_sha=COMMIT,
                        status='in_progress', conclusion=None)
        self.jobs = [dict(name=name, conclusion='success') for name in ('checks', 'Windows x64')]
        self.releases = {
            1: dict(id=1, tag_name='v0.6.9', prerelease=False, draft=False, assets=[]),
            2: dict(id=2, tag_name='preview', target_commitish='b'*40,
                    prerelease=True, draft=False, assets=[dict(name='previous.zip')]),
        }
        self.reference = 'b' * 40
        self.main = COMMIT
        self.changed_files = ['app/controller.py']
        self.fail_upload = self.corrupt_upload = self.stale_upload = self.fail_cutover = False

    def pages(self, path, key=None):
        self.calls.append(('pages', path))
        return copy.deepcopy(self.jobs if key == 'jobs' else list(self.releases.values()))

    def api(self, path, method='GET', data=None, missing_ok=False):
        self.calls.append((method, path, copy.deepcopy(data)))
        if path.startswith('actions/runs/'):
            return copy.deepcopy(self.run)
        if path == 'branches/main':
            return dict(commit=dict(sha=self.main))
        if path.startswith('compare/'):
            return dict(status='ahead', files=[dict(filename=name) for name in self.changed_files])
        if path == 'releases' and method == 'POST':
            self.releases[3] = dict(data, id=3, assets=[],
                                   html_url=f'https://github.com/{REPO}/releases/tag/preview')
            return copy.deepcopy(self.releases[3])
        if path.startswith('releases/'):
            identifier = int(path.split('/')[1])
            if method == 'DELETE':
                del self.releases[identifier]
                return None
            if method == 'PATCH':
                if self.fail_cutover:
                    raise RuntimeError('Publication failed')
                self.releases[identifier].update(data)
            return copy.deepcopy(self.releases[identifier])
        if path == 'git/ref/tags/preview':
            return dict(object=dict(sha=self.reference)) if self.reference else None
        if path == 'git/refs/tags/preview' and method == 'DELETE':
            self.reference = None
            return None
        if path == 'git/refs' and method == 'POST':
            self.reference = data['sha']
            return None
        raise AssertionError((method, path, data))

    def gh(self, *args):
        self.calls.append(('gh', *args))
        if args[:2] == ('run', 'download'):
            assert args[5:7] == ('--name', 'Umeko-windows-x64')
            shutil.copytree(self.package, Path(args[-1]))
        elif args[:2] == ('release', 'upload'):
            if self.fail_upload:
                raise RuntimeError('Upload failed')
            path = Path(args[3])
            self.releases[3]['assets'].append(dict(
                name=path.name, state='uploaded', size=path.stat().st_size,
                digest='sha256:' + ('0'*64 if self.corrupt_upload else digest(path))))
            if self.stale_upload:
                self.main = 'c'*40
        else:
            raise AssertionError(args)
        return ''


class CiPreviewReleaseTests(unittest.TestCase):
    def setUp(self):
        sleep = patch('scripts.ci_preview_release.time.sleep')
        self.pause = sleep.start()
        self.addCleanup(sleep.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root/'package'
        self.package.mkdir()
        archive = self.package/f'Umeko-0.6.9-windows-x64-{COMMIT[:7]}.zip'
        archive.write_bytes(b'offline Windows package')
        archive.with_name(archive.name+'.sha256').write_text(digest(archive)+'  '+archive.name+'\n')
        self.report = dict(platform='windows-x64', archive=archive.name, sha256=digest(archive),
                           build=dict(commit=COMMIT, version='0.6.9'), gui='passed',
                           pi='passed', terminal='passed', https='passed')
        (self.package/'build.json').write_text(json.dumps(self.report))
        self.client = GitHubFixture(self.package)
        self.env = dict(GITHUB_REPOSITORY=REPO, GITHUB_RUN_ID='1234', GITHUB_RUN_ATTEMPT='1',
                        GITHUB_SHA=COMMIT, GITHUB_REF='refs/heads/main', GITHUB_EVENT_NAME='push',
                        GITHUB_STEP_SUMMARY=str(self.root/'summary.md'))

    def publish(self):
        return publish(self.env, self.client, self.root/'staging')

    def test_replaces_only_preview_after_all_uploaded_assets_are_verified(self):
        stable = copy.deepcopy(self.client.releases[1])
        result = self.publish()
        self.assertEqual(result['tag_name'], 'preview')
        self.assertEqual(self.client.reference, COMMIT)
        self.assertFalse(result['draft'])
        self.assertTrue(result['prerelease'])
        self.assertEqual(result['make_latest'], 'false')
        self.assertEqual(self.client.releases[1], stable)
        self.assertNotIn(2, self.client.releases)
        self.assertEqual(len(result['assets']), 4)
        self.assertTrue(all('windows-x64' in row['name'] or row['name'] == 'SHA256SUMS.txt'
                            for row in result['assets']))
        calls = self.client.calls
        deletion = calls.index(('DELETE', 'releases/2', None))
        uploads = [i for i,c in enumerate(calls) if c[:3] == ('gh','release','upload')]
        verified = max(i for i,c in enumerate(calls[:deletion]) if c == ('GET','releases/3',None))
        self.assertLess(max(uploads), verified)
        self.assertLess(verified, deletion)
        self.assertIn('rolling Windows', (self.root/'summary.md').read_text())

    def test_first_release_can_be_created_without_existing_preview(self):
        del self.client.releases[2]
        self.client.reference = None
        self.assertEqual(self.publish()['tag_name'], 'preview')

    def test_rest_replica_can_lag_behind_successful_dependencies(self):
        original = self.client.pages
        reads = []
        def pages(path, key=None):
            if key == 'jobs':
                reads.append(path)
                if len(reads) < 3:
                    return [dict(name='checks', conclusion=None)]
            return original(path, key)
        self.client.pages = pages
        self.assertEqual(self.publish()['tag_name'], 'preview')
        self.assertEqual(len(reads), 3)
        self.assertEqual(self.pause.call_count, 2)

    def test_fork_pr_other_branch_and_wrong_head_cannot_publish(self):
        for field,value in [('head_repository',dict(full_name='fork/umeko-desktop')),
                            ('path','.github/workflows/preview.yml'),('event','pull_request'),
                            ('head_branch','feature'),('head_sha','c'*40),
                            ('conclusion','failure')]:
            with self.subTest(field=field):
                client = GitHubFixture(self.package)
                client.run[field] = value
                with self.assertRaises(ValueError):
                    verify_ci_run(client,'1234',COMMIT)
        for field,value in [('GITHUB_REPOSITORY','fork/umeko-desktop'),
                            ('GITHUB_REF','refs/pull/91/merge'),('GITHUB_EVENT_NAME','pull_request')]:
            with self.subTest(environment=field):
                env = dict(self.env, **{field:value})
                with self.assertRaises(ValueError):
                    publish(env,self.client,self.root/'unused')
        self.assertFalse(self.client.calls)

    def test_failed_missing_or_pending_required_jobs_block_publication(self):
        for jobs in ([dict(name='Windows x64',conclusion='success')],
                     [dict(name='checks',conclusion='success'),dict(name='Windows x64',conclusion='failure')],
                     self.client.jobs+[dict(name='macOS Intel',conclusion=None)]):
            self.client.jobs = jobs
            with self.assertRaises(ValueError):
                self.publish()
            self.assertFalse(any(call[0] in ('POST','DELETE','PATCH','gh') for call in self.client.calls))

    def test_corrupt_package_does_not_touch_published_preview(self):
        self.report['sha256'] = '0'*64
        (self.package/'build.json').write_text(json.dumps(self.report))
        with self.assertRaises(ValueError):
            self.publish()
        self.assertIn(2,self.client.releases)
        self.assertFalse(any(call[0] in ('POST','DELETE','PATCH') for call in self.client.calls))

    def test_upload_failure_or_server_digest_mismatch_preserves_previous_preview(self):
        for failure in ('fail_upload','corrupt_upload'):
            with self.subTest(failure=failure):
                client = GitHubFixture(self.package)
                setattr(client,failure,True)
                with self.assertRaises((RuntimeError,ValueError)):
                    publish(self.env,client,self.root/failure)
                self.assertIn(2,client.releases)
                self.assertNotIn(3,client.releases)
                self.assertEqual(client.reference,'b'*40)

    def test_outdated_run_never_replaces_newer_preview(self):
        self.client.main = 'c'*40
        self.assertIsNone(self.publish())
        self.assertFalse(any(call[0] in ('POST','DELETE','PATCH','gh') for call in self.client.calls))

    def test_readme_download_updates_do_not_discard_verified_desktop_builds(self):
        self.client.main = 'c'*40
        self.client.changed_files = ['README.md', 'README.zh-CN.md']
        self.assertEqual(self.publish()['target_commitish'], COMMIT)
        self.assertEqual(self.client.reference, COMMIT)

    def test_documentation_update_with_source_change_is_still_stale(self):
        self.client.main = 'c'*40
        self.client.changed_files = ['README.md', 'app/qml/Main.qml']
        self.assertIsNone(self.publish())
        self.assertFalse(any(call[0] in ('POST','DELETE','PATCH','gh') for call in self.client.calls))

    def test_newer_main_during_upload_discards_only_staging_draft(self):
        self.client.stale_upload = True
        self.assertIsNone(self.publish())
        self.assertIn(2,self.client.releases)
        self.assertNotIn(3,self.client.releases)
        self.assertEqual(self.client.reference,'b'*40)

    def test_cutover_failure_retains_verified_draft_for_recovery(self):
        self.client.fail_cutover = True
        with self.assertRaisesRegex(RuntimeError,'Publication failed'):
            self.publish()
        self.assertTrue(self.client.releases[3]['draft'])
        self.assertEqual(len(self.client.releases[3]['assets']),4)
        self.assertIn(1,self.client.releases)

    def test_immutable_or_stable_release_is_not_deleted(self):
        for field,value in [('immutable',True),('prerelease',False)]:
            with self.subTest(field=field):
                client = GitHubFixture(self.package)
                client.releases[2][field] = value
                with self.assertRaises(ValueError):
                    publish(self.env,client,self.root/field)
                self.assertIn(2,client.releases)


if __name__ == '__main__':
    unittest.main()
