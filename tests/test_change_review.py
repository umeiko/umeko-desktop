"""Real Git snapshots: loop baselines, read-only repository and bounded previews."""
import importlib.util, json, os, shutil, subprocess, sys, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugin-runtime'))
from umeko_plugin_sdk import Context
from umeko_plugin_sdk.packages import validate
SPEC=importlib.util.spec_from_file_location('review_snapshots',ROOT/'umeko-plugins/change-review/scripts/snapshots.py')
engine=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(engine)

@unittest.skipUnless(shutil.which('git'),'Git required')
class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.work=self.root/'中文 workspace';self.work.mkdir();self.state=self.root/'state';self.state.mkdir();self.snap=None
    def tearDown(self):
        if self.snap:self.snap.close()
        self.temp.cleanup()
    def git(self,*args):return subprocess.check_output(['git','-C',str(self.work),*args],stderr=subprocess.DEVNULL)
    def begin(self):
        self.snap=engine.Snapshot(self.work,self.state);self.snap.begin()
    def test_loop_delta_preserves_head_index_staged_and_dirty_content(self):
        self.git('init','-q');self.git('config','user.name','test');self.git('config','user.email','test@example.invalid')
        p=self.work/'原有 dirty.txt';p.write_text('committed\n');(self.work/'unchanged').write_text('one\n');(self.work/'already-deleted').write_text('old\n')
        self.git('add','.');self.git('commit','-qm','baseline');p.write_text('staged\n');self.git('add','.');p.write_text('before loop\n')
        (self.work/'already-deleted').unlink()
        before=(self.work/'.git/index').read_bytes();head=self.git('rev-parse','HEAD');self.begin()
        p.write_text('after loop\n');(self.work/'new space.txt').write_text('hello\n');(self.work/'unchanged').unlink()
        result=self.snap.finish();self.assertFalse(result['limited']);rows={r['path']:r for r in result['entries']}
        self.assertEqual({p:r['status'] for p,r in rows.items()},{'new space.txt':'A','unchanged':'D','原有 dirty.txt':'M'})
        self.assertEqual(rows['原有 dirty.txt']['added'],1);self.assertEqual(rows['原有 dirty.txt']['removed'],1)
        diff=self.snap.diff('原有 dirty.txt')['text'];self.assertIn('-before loop',diff);self.assertIn('+after loop',diff);self.assertNotIn('-committed',diff)
        self.assertEqual((self.work/'.git/index').read_bytes(),before);self.assertEqual(self.git('rev-parse','HEAD'),head)
        self.assertEqual(self.git('diff','--cached','--numstat').decode().strip(),'1\t1\t"\\345\\216\\237\\346\\234\\211 dirty.txt"')
    def test_non_git_ignored_binary_large_and_refresh(self):
        (self.work/'.gitignore').write_text('ignored/\n');(self.work/'ignored').mkdir();(self.work/'ignored/x').write_text('ignore')
        (self.work/'normal').write_text('before\n');(self.work/'binary').write_bytes(b'a\0b');(self.work/'large').write_bytes(b'a'*(engine.MAX_FILE+1))
        self.begin();(self.work/'normal').write_text('after\n');(self.work/'binary').write_bytes(b'a\0c');(self.work/'large').write_bytes(b'b'*(engine.MAX_FILE+1));(self.work/'ignored/x').write_text('changed')
        result=self.snap.finish();rows={r['path']:r for r in result['entries']}
        self.assertFalse(result['repository']);self.assertTrue(result['limited']);self.assertNotIn('ignored/x',rows)
        self.assertTrue(rows['large']['omitted']);self.assertTrue(rows['binary']['binary'])
        self.assertIn('二进制',self.snap.diff('binary')['text']);self.assertTrue(self.snap.diff('large')['truncated'])
        (self.work/'normal').write_text('refreshed\n');self.snap.finish();self.assertIn('+refreshed',self.snap.diff('normal')['text'])
        self.assertFalse((self.work/'.git').exists())
    def test_empty_unchanged_long_lines_literal_names_and_symlinks(self):
        odd=':(glob)你好 [a]\tline\n.txt';(self.work/odd).write_text('old\n');self.begin();self.assertEqual(self.snap.finish()['entries'],[])
        (self.work/odd).write_text('new\n'+'x'*60000);result=self.snap.finish();self.assertEqual(result['entries'][0]['path'],odd)
        diff=self.snap.diff(odd);self.assertTrue(diff['truncated']);self.assertLessEqual(len(diff['text']),48000);self.assertIn('+new',diff['text'])
        if os.name!='nt':
            outside=self.root/'secret';outside.write_text('secret');(self.work/'link').symlink_to(outside)
            self.snap.finish();self.assertNotIn('link',[r['path'] for r in self.snap.finish()['entries']])
    def test_file_count_budget_never_fabricates_deletions(self):
        for n in range(6):(self.work/f'{n}.txt').write_text('old')
        with patch.object(engine,'MAX_FILES',3):
            self.begin();(self.work/'-new').write_text('new');result=self.snap.finish()
        self.assertTrue(result['limited']);self.assertFalse(any(r['status']=='D' for r in result['entries']))
        self.assertEqual(result['entries'][0]['status'],'?')
    def test_refresh_prunes_previous_versions_in_private_git(self):
        file=self.work/'file';file.write_text('baseline\n');self.begin()
        for number in range(5):
            file.write_text(f'version {number}\n');self.snap.finish()
            objects=self.snap.run(['cat-file','--batch-all-objects','--batch-check=%(objectname)'],private=True).splitlines()
            self.assertLessEqual(len(objects),4,'Only base/end blobs and trees may survive refresh')
        self.assertIn('+version 4',self.snap.diff('file')['text'])
        self.assertIn('-baseline',self.snap.diff('file')['text'])

    def test_no_git_and_cancellation_leave_no_snapshots(self):
        with patch.object(engine.shutil,'which',return_value=None):
            with self.assertRaisesRegex(engine.SnapshotError,'Git'):engine.Snapshot(self.work,self.state)
        self.snap=engine.Snapshot(self.work,self.state,threading.Event());self.snap.cancelled.set()
        with self.assertRaises(engine.SnapshotError):self.snap.begin()
        self.snap.close();self.assertEqual(list(self.state.iterdir()),[])
    def test_project_attributes_do_not_transform_snapshot_or_run_filters(self):
        self.git('init','-q');(self.work/'.gitattributes').write_text('*.txt filter=danger text eol=crlf\n')
        marker=self.root/'executed';self.git('config','filter.danger.clean',f'touch {marker}')
        (self.work/'file.txt').write_bytes(b'one\r\n');self.begin();(self.work/'file.txt').write_bytes(b'two\r\n');self.snap.finish()
        self.assertIn('+two',self.snap.diff('file.txt')['text']);self.assertFalse(marker.exists())
    def test_worker_loop_cancellation_status_and_open_target(self):
        m,defaults,_=validate(ROOT/'umeko-plugins/change-review')
        self.assertEqual(m['lifecycle'],'application');self.assertNotIn('git.write',m['permissions'])
        proc=subprocess.Popen([sys.executable,'-B',str(ROOT/'plugin-runtime/worker.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        target={'token':'one','id':'one','workspace':str(self.work)};events=[]
        def call(identifier,operation,args):
            proc.stdin.write(json.dumps({'id':identifier,'operation':operation,'arguments':args})+'\n');proc.stdin.flush()
            while True:
                value=json.loads(proc.stdout.readline())
                if value.get('type')=='event':events.append(value);continue
                self.assertTrue(value['ok'],value);return value['result']
        try:
            call('init','initialize',{'path':str(ROOT/'umeko-plugins/change-review'),'stateDir':str(self.state),'config':defaults,'session':target})
            (self.work/'file').write_text('old\n');call('begin','call',{'method':'begin','arguments':{'loopId':'loop-one'},'session':target})
            (self.work/'file').write_text('new\n');call('finish','call',{'method':'finish','arguments':{'loopId':'loop-one','reason':'cancelled'},'session':target})
            status=call('status','call',{'method':'status','arguments':{},'session':target});self.assertEqual(status['reason'],'cancelled');self.assertEqual(status['total'],1)
            opens=[e for e in events if e.get('event')=='page.open'];self.assertEqual(opens[0]['arguments']['session'],target)
            other={**target,'token':'other'};self.assertTrue(call('other','call',{'method':'status','arguments':{},'session':other})['empty'])
            again=call('again','call',{'method':'finish','arguments':{'loopId':'loop-one'},'session':target});self.assertFalse(again['reviewed'])
            original=next(self.state.glob('review-*'))
            # A new loop in another chat drops the sole completed review.
            call('second-begin','call',{'method':'begin','arguments':{'loopId':'loop-two'},'session':other})
            self.assertFalse(original.exists())
            self.assertTrue(call('old-status','call',{'method':'status','arguments':{},'session':target})['empty'])
            (self.work/'src').mkdir();(self.work/'src'/'中文 file.py').write_text('print(1)\n')
            (self.work/'src'/'nested').mkdir();(self.work/'src'/'nested'/'data.txt').write_text('text\n')
            call('second-finish','call',{'method':'finish','arguments':{'loopId':'loop-two'},'session':other})
            tree=call('tree-root','call',{'method':'tree','arguments':{},'session':other})
            self.assertEqual(tree['entries'][0]['path'],'src');self.assertTrue(tree['entries'][0]['directory'])
            self.assertEqual(tree['entries'][0]['count'],2)
            children=call('tree-src','call',{'method':'tree','arguments':{'path':'src'},'session':other})
            self.assertEqual([row['name'] for row in children['entries']],['nested','中文 file.py'])
            self.assertTrue(call('old-after-finish','call',{'method':'status','arguments':{},'session':target})['empty'])
            self.assertEqual(len(list(self.state.glob('review-*'))),1)

        finally:
            proc.stdin.close();proc.wait(timeout=10);proc.stdout.close();proc.stderr.close()
        self.assertEqual(list(self.state.iterdir()),[])

if __name__=='__main__':unittest.main()
