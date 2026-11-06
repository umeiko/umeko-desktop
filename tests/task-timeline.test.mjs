import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
const context=vm.createContext({});
vm.runInContext(readFileSync(new URL('../umeko-plugins/task-records/qml/Timeline.js',import.meta.url),'utf8').replace('.pragma library',''),context);
const nodes=data=>JSON.parse(JSON.stringify(context.nodes(data)));
test('observed events interleave with files and keep user confirmation separate',()=>{
 const rows=nodes({started:'2026-01-01T01:00Z',ended:'2026-01-01T01:03Z',accepted:'2026-01-01T01:04Z',state:'finished',cwd:'/project',
  steps:[{kind:'tool',key:'tool1',detail:'read · done',observed:'2026-01-01T01:01Z'}],
  files:[{id:1,source:'submitted',path:'/project/report.md',observed:'2026-01-01T01:02Z',state:'changed'}]});
 assert.deepEqual(rows.map(row=>row.kind),['start','tool','file','end','accepted']);
 assert.equal(rows[2].code,'changed'); assert.equal(rows[4].code,'accepted');
});
test('legacy events remain undated and keep stable storage order',()=>{
 const rows=nodes({started:'2026-01-01',steps:[{kind:'message',key:'m1',detail:'user'},{kind:'tool',key:'t1',detail:'read'}],files:[]});
 assert.deepEqual(rows.slice(1).map(row=>row.time),['','']);
 assert.deepEqual(rows.slice(1).map(row=>row.kind),['message','tool']);
});
test('identical timestamps retain input order and unique navigation keys',()=>{
 const rows=nodes({started:'2026-01-01',steps:[{kind:'message',key:'same',observed:'2026-01-01'},{kind:'tool',key:'same',observed:'2026-01-01'}],files:[]});
 assert.equal(new Set(rows.map(row=>row.key)).size,3);
 assert.deepEqual(rows.map(row=>row.kind),['start','message','tool']);
});
test('file check counts stay explicit rather than implying acceptance',()=>{
 assert.deepEqual(JSON.parse(JSON.stringify(context.checkSummary({counts:{available:2,changed:1}}))),[{code:'available',count:2},{code:'changed',count:1}]);
 assert.deepEqual(nodes(null),[]);
});

test('bounded host pages retain their shared order and include each milestone only on its page',()=>{
 const common={started:'2026-01-01T00:00Z',ended:'2026-01-01T00:12Z',state:'finished',cwd:'/project'};
 const first=nodes({...common,timelineKeys:['start','tool-1'],steps:[{kind:'tool',key:'1',detail:'read',observed:'2026-01-01T00:01Z'}]});
 const last=nodes({...common,timelineKeys:['tool-2','file-1','end'],steps:[{kind:'tool',key:'2',detail:'write',observed:'2026-01-01T00:09Z'}],
  files:[{id:1,source:'submitted',path:'/project/report',observed:'2026-01-01T00:11Z',state:'available'}]});
 const all=[...first,...last];
 assert.deepEqual(all.map(row=>row.key),['start','tool-1','tool-2','file-1','end']);
 assert.deepEqual(all.map(row=>row.time),all.map(row=>row.time).sort());
 assert.deepEqual(nodes({...common,timelineKeys:[]}),[]);
});
