import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.update_download import platform_target, select_asset, download_asset
from app.project_info import PROJECT_URL


class Response(io.BytesIO):
    def geturl(self): return 'https://release-assets.githubusercontent.com/fixture'


class UpdateDownloadTests(unittest.TestCase):
    def fixture(self, target='windows-x64'):
        payload = b'archive fixture'*50000
        name = 'Umeko-99.0.0-'+target+'-a1b2c3d'+('.tar.gz' if target.startswith('linux-') else '.zip')
        asset = {'name':name, 'size':len(payload), 'digest':'sha256:'+hashlib.sha256(payload).hexdigest(),
                 'browser_download_url':PROJECT_URL+'/releases/download/v99.0.0/'+name}
        release = {'tag_name':'v99.0.0', 'assets':[asset]}
        return payload, release, asset

    def test_platform_and_asset_selection(self):
        for system,cpu,expected in [('Windows','AMD64','windows-x64'),('Darwin','arm64','macos-arm64'),('Darwin','x86_64','macos-x64'),('Linux','x86_64','linux-x64'),('Linux','mips','')]:
            self.assertEqual(platform_target(system,cpu),expected)
            if not expected: continue
            _,release,asset=self.fixture(expected)
            selected=select_asset(release,PROJECT_URL,expected)
            self.assertEqual(selected['name'],asset['name'])
            self.assertEqual(select_asset(release,PROJECT_URL,'wrong-platform'),{})
            for bad in [{'browser_download_url':'https://example.invalid/archive.zip'}, {'digest':'bad'}, {'size':0}]:
                self.assertEqual(select_asset({**release,'assets':[{**asset,**bad}]},PROJECT_URL,expected),{})
            self.assertEqual(select_asset({**release,'assets':[asset,asset]},PROJECT_URL,expected),{})

    def test_verified_atomic_download_preserves_existing_files(self):
        payload,release,raw=self.fixture()
        asset=select_asset(release,PROJECT_URL,'windows-x64')
        with tempfile.TemporaryDirectory() as temp:
            existing=Path(temp)/raw['name']; existing.write_bytes(b'keep existing')
            progress=[]
            with patch('app.update_download.urllib.request.urlopen',return_value=Response(payload)):
                downloaded=Path(download_asset(asset,temp,progress.append,lambda:False))
            self.assertNotEqual(downloaded,existing)
            self.assertEqual(existing.read_bytes(),b'keep existing')
            self.assertEqual(downloaded.read_bytes(),payload)
            self.assertEqual(progress[-1],100)
            self.assertLessEqual(len(progress),101)
            self.assertFalse(list(Path(temp).glob('*.part')))

    def test_truncation_bad_digest_and_cancel_never_leave_an_update_archive(self):
        payload,release,_=self.fixture()
        asset=select_asset(release,PROJECT_URL,'windows-x64')
        for body,expected,cancel in [(payload[:-5],asset,False),(payload,{**asset,'sha256':'0'*64},False),(payload,asset,True)]:
            with tempfile.TemporaryDirectory() as temp, patch('app.update_download.urllib.request.urlopen',return_value=Response(body)):
                with self.assertRaises((ValueError,InterruptedError)):
                    download_asset(expected,temp,lambda _:None,lambda:cancel)
                self.assertEqual(list(Path(temp).iterdir()),[])
