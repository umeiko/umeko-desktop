"""Same-version publishing must verify staged bytes before changing live assets."""
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from replace_release_assets import replace_published_release


class ReplacementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.sha='a'*40
        self.data={'id':42,'target_commitish':self.sha,'draft':False,'immutable':False,'assets':[]}
        self.calls=[];self.uploads=0;self.fail_after=None;self.corrupt=False
        for name,body in [('app.zip',b'old'),('sdk.zip',b'sdk'),('obsolete.zip',b'old')]:self.asset(name,body)
        self.files=[]
        for name,body in [('app.zip',b'new'),('info.json',b'new info'),('sdk.zip',b'sdk')]:
            path=self.root/name;path.write_bytes(body);self.files.append(path)

    def tearDown(self):self.temp.cleanup()

    def asset(self,name,body):
        value={'id':max([a['id'] for a in self.data['assets']],default=0)+1,'name':name,'state':'uploaded',
               'size':len(body),'digest':'sha256:'+hashlib.sha256(body).hexdigest()}
        self.data['assets'].append(value)
        return value

    def api(self,path):
        if path.startswith('git/ref/'):return {'object':{'type':'commit','sha':self.sha}}
        return copy.deepcopy(self.data)

    def gh(self,*args):
        self.calls.append(args)
        if args[:2]==('release','upload'):
            if self.fail_after is not None and self.uploads>=self.fail_after:raise subprocess.CalledProcessError(1,args)
            path=Path(args[3]);value=self.asset(path.name,path.read_bytes());self.uploads+=1
            if self.corrupt:value['digest']='sha256:'+'0'*64
        elif args[:3]==('api','--method','DELETE'):
            self.data['assets']=[a for a in self.data['assets'] if a['id']!=int(args[3].rsplit('/',1)[1])]
        elif '/releases/assets/' in args[3]:
            value=next(a for a in self.data['assets'] if a['id']==int(args[3].rsplit('/',1)[1]))
            value['name']=next(a[5:] for a in args if isinstance(a,str) and a.startswith('name='))
        elif '/git/refs/' in args[3]:
            self.sha=next(a[4:] for a in args if isinstance(a,str) and a.startswith('sha='));self.assertIn('force=true',args)
        else:self.data.update(json.loads(Path(args[-1]).read_text()))
        return '{}'

    def replace(self,authorized=True):
        return replace_published_release('umeiko/umeko-desktop','v0.5.0','b'*40,self.files,'same-version fix',self.gh,self.api,authorized=authorized)

    def test_complete_replacement_retains_id_identical_sdk_and_can_resume(self):
        sdk=next(a['id'] for a in self.data['assets'] if a['name']=='sdk.zip')
        result=self.replace()
        self.assertEqual(result['id'],42);self.assertEqual(self.sha,'b'*40)
        self.assertEqual(result['target_commitish'],'b'*40)
        self.assertEqual({a['name'] for a in result['assets']},{p.name for p in self.files})
        self.assertEqual(next(a['id'] for a in result['assets'] if a['name']=='sdk.zip'),sdk)
        uploads=self.uploads;self.replace();self.assertEqual(self.uploads,uploads)

    def test_upload_failure_preserves_old_files_and_tag(self):
        old=copy.deepcopy(self.data['assets']);self.fail_after=1
        with self.assertRaisesRegex(RuntimeError,'Staged upload failed'):self.replace()
        self.assertEqual(self.data['assets'][:len(old)],old);self.assertEqual(self.sha,'a'*40)
        self.assertFalse([c for c in self.calls if c[:3]==('api','--method','DELETE')])

    def test_bad_digest_is_rejected_before_replacing_old_files(self):
        old=copy.deepcopy(self.data['assets']);self.corrupt=True
        with self.assertRaises(AssertionError):self.replace()
        self.assertEqual(self.data['assets'][:len(old)],old);self.assertEqual(self.sha,'a'*40)

    def test_explicit_opt_in_and_mutable_release_are_required(self):
        with self.assertRaisesRegex(ValueError,'explicit authorization'):self.replace(False)
        self.data['immutable']=True
        with self.assertRaisesRegex(RuntimeError,'immutable'):self.replace()
        self.assertEqual(self.calls,[])
