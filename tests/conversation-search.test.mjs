import test from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
import {spawn} from 'node:child_process';
import {projectSession,search} from '../runtime/conversation-search.mjs';

const rg=resolve('runtime/releases/coding-1.3.0/bin/rg'+(process.platform==='win32'?'.exe':''));
const message=(id,parent,role,text,timestamp=1700000000000)=>({type:'message',id,parentId:parent,message:{role,content:[{type:'text',text}],timestamp}});
async function fixture(t,entries){
  const directory=await fs.mkdtemp(join(tmpdir(),'umeko-search-'));t.after(()=>fs.rm(directory,{recursive:true,force:true}));
  const file=join(directory,'session.jsonl');await fs.writeFile(file,entries.map(e=>JSON.stringify(e)+'\n').join(''));
  return {directory,file,session:{id:'conversation-one',title:'Search fixture',file},cache:join(directory,'cache')};
}
async function run(f,query,options={},extra={}){
  const events=[];await search({query,options,cache:f.cache,workspace:'fixture',sessions:[f.session],rg,...extra},new AbortController().signal,event=>events.push(event));
  return {events,hits:events.filter(e=>e.type==='matches').flatMap(e=>e.items),done:events.at(-1)};
}
test('literal CJK, quoted code, one/two characters and emoji use original visible text',async t=>{
  const f=await fixture(t,[message('u',null,'user','模型 a"b %_ fn 💠'),message('a','u','assistant','fn widget() {}\n模型 ready')]);
  for(const query of ['模型','a"b','%_','fn','💠']){
    const {hits}=await run(f,query);assert.ok(hits.length,query);assert.ok(hits.every(h=>['u','a'].includes(h.entryId)));assert.ok(hits.every(h=>h.hit===query));
  }
  assert.equal((await run(f,'content')).hits.length,0,'JSON field names are excluded');
});
test('case, whole-word, regex, role and time filters combine correctly',async t=>{
  const f=await fixture(t,[message('u',null,'user','Widget widgets WIDGET',1000),message('a','u','assistant','Widget foobar',3000)]);
  assert.equal((await run(f,'Widget',{caseSensitive:true,wholeWord:true,role:'user'})).hits.length,1);
  assert.equal((await run(f,'widget',{wholeWord:true})).hits.length,3);
  assert.equal((await run(f,'Widget|foobar',{regex:true,role:'assistant',since:2000,until:4000})).hits.length,2);
  assert.equal((await run(f,'Widget',{role:'assistant',until:2000})).hits.length,0);
  await assert.rejects(run(f,'[',{regex:true}),/regex|parse|PCRE|pattern/i);
});
test('UTF-8 match positions become original UTF-16 offsets and correct line numbers',async t=>{
  const f=await fixture(t,[message('u',null,'user','第一行\n💠模型 %_')]);
  const {hits}=await run(f,'模型');assert.equal(hits[0].offset,6);assert.equal(hits[0].line,2);
});
test('projection resumes complete append lines and rebuilds selected branches without changing source',async t=>{
  const f=await fixture(t,[message('u',null,'user','root'),message('a','u','assistant','old branch')]);
  const directory=join(f.directory,'projection');let p=await projectSession(f.session,directory);
  const time=(await fs.stat(p.file)).mtimeMs;await projectSession(f.session,directory);assert.equal((await fs.stat(p.file)).mtimeMs,time);
  const next=JSON.stringify(message('b','u','assistant','new branch'))+'\n';await fs.appendFile(f.file,next.slice(0,15));
  p=await projectSession(f.session,directory);assert.equal(p.messages.length,2);
  await fs.appendFile(f.file,next.slice(15));p=await projectSession(f.session,directory);assert.deepEqual(p.messages.map(m=>m.entryId),['u','b']);
  f.session.leaf='a';p=await projectSession(f.session,directory);assert.deepEqual(p.messages.map(m=>m.entryId),['u','a']);
  f.session.leaf='b';const before=createHash('sha256').update(await fs.readFile(f.file)).digest('hex');
  assert.equal((await run(f,'old branch')).hits.length,0);assert.equal((await run(f,'new branch')).hits.length,1);
  assert.equal(createHash('sha256').update(await fs.readFile(f.file)).digest('hex'),before);
});
test('multiline results cannot cross distinct messages',async t=>{
  const f=await fixture(t,[message('u',null,'user','alpha\nbeta'),message('a','u','assistant','gamma')]);
  assert.equal((await run(f,'alpha\nbeta')).hits.length,1);assert.equal((await run(f,'beta\ngamma')).hits.length,0);
});
test('source deletion is a visible skipped source; result cap is explicit',async t=>{
  const f=await fixture(t,[message('u',null,'user','hit hit hit hit')]);
  const value=await run(f,'hit',{}, {maxResults:2});assert.equal(value.hits.length,2);assert.equal(value.done.limitHit,true);
  await fs.unlink(f.file);const deleted=await run(f,'hit');assert.equal(deleted.hits.length,0);assert.equal(deleted.done.skipped,1);
});
test('a streaming tail is a separate projection and keeps the durable cache unchanged',async t=>{
  const f=await fixture(t,[message('u',null,'user','durable question')]);
  await run(f,'durable');
  const directory=join(f.cache,createHash('sha256').update('fixture').digest('hex').slice(0,32));
  const files=await fs.readdir(directory);const native=join(directory,files.find(name=>name.endsWith('.txt')));
  const before=(await fs.stat(native)).mtimeMs;
  f.session.live=[{entryId:'live:tail',role:'assistant',text:'still streaming 💠',sourceIndex:1}];
  const {hits}=await run(f,'streaming');assert.equal(hits.length,1);assert.equal(hits[0].entryId,'live:tail');assert.equal(hits[0].sessionId,f.session.id);
  assert.equal((await fs.stat(native)).mtimeMs,before);
  f.session.live=[];assert.equal((await run(f,'streaming')).hits.length,0);
});
test('worker cancels stale queries and streams only the final generation after replacement',async t=>{
  const entries=Array.from({length:3000},(_,i)=>message('id-'+i,i?'id-'+(i-1):null,'user','searchable old text '+i));
  const f=await fixture(t,entries);const worker=spawn(process.execPath,[resolve('runtime/conversation-search.mjs')],{stdio:['pipe','pipe','pipe']});
  t.after(()=>worker.kill());let output='';worker.stdout.on('data',b=>{output+=b.toString();});
  const job={type:'search',cache:f.cache,workspace:'fixture',sessions:[f.session],rg};
  worker.stdin.write(JSON.stringify({...job,id:1,query:'old'})+'\n');
  worker.stdin.write(JSON.stringify({...job,id:2,query:'does-not-exist'})+'\n');
  await new Promise((resolve,reject)=>{const until=Date.now()+10000;const timer=setInterval(()=>{if(output.includes('"id":2,"type":"done"')){clearInterval(timer);resolve();}else if(Date.now()>until){clearInterval(timer);reject(new Error(output));}},20);});
  const events=output.trim().split('\n').map(JSON.parse);assert.ok(events.some(e=>e.id===2 && e.type==='done'));assert.ok(!events.some(e=>e.id===1 && e.type==='matches'));
});
