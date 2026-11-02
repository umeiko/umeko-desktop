import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';

test('Widget catalogs reuse the streaming Pi without reloading history or ending the turn', {timeout:30000}, async()=>{
  const root=mkdtempSync(join(tmpdir(),'umeko-widget-catalog-')),work=join(root,'work'),agent=join(root,'agent');
  mkdirSync(work);
  for(let i=0;i<30;i++){const name='guide-'+String(i).padStart(2,'0'),folder=join(agent,'skills',name);mkdirSync(folder,{recursive:true});writeFileSync(join(folder,'SKILL.md'),`---\nname: ${name}\ndescription: Local benchmark fixture.\n---\nInstructions.`);}
  let release;
  const gate=new Promise(resolve=>{release=resolve});
  let requests=0;
  const server=createServer(async(req,res)=>{
    for await(const _ of req){} requests++;await gate;
    res.writeHead(200,{'Content-Type':'text/event-stream'});
    res.end('data: '+JSON.stringify({id:'fixture',object:'chat.completion.chunk',created:1,model:'fixture',choices:[{index:0,delta:{role:'assistant',content:'done'},finish_reason:'stop'}]})+'\n\ndata: [DONE]\n\n');
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const child=spawn(process.execPath,[fileURLToPath(new URL('../runtime/releases/coding-1.3.0/bridge.mjs',import.meta.url))],{stdio:['pipe','pipe','pipe']});
  const events=[];let buffer='',stderr='';child.stderr.on('data',data=>{stderr+=data});
  child.stdout.on('data',data=>{buffer+=data;let at;while((at=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,at);buffer=buffer.slice(at+1);try{events.push(JSON.parse(line))}catch{}}});
  const send=value=>child.stdin.write(JSON.stringify(value)+'\n');
  const wait=async check=>{for(let i=0;i<2000;i++){if(check())return;if(child.exitCode!==null)throw new Error(stderr);await new Promise(resolve=>setTimeout(resolve,5));}throw new Error('Timed out: '+JSON.stringify(events.slice(-4)));};
  const times={extensions:[],skills:[]};let sequence=0;
  async function catalog(kind){
    const id=String(++sequence),start=performance.now();send({type:'widget_catalog',id,kind});
    await wait(()=>events.some(e=>e.type==='widget_catalog'&&e.id===id));
    const reply=events.find(e=>e.type==='widget_catalog'&&e.id===id);assert.equal(reply.ok,true,reply.error);
    times[kind].push(performance.now()-start);return reply.value;
  }
  try{
    send({type:'load',workspace:work,defaultCwd:work,agentDir:agent,agent:{},sessionDir:join(root,'sessions'),gateway:`http://127.0.0.1:${server.address().port}/`,token:'fixture',model:'fixture',models:[{id:'fixture',api:'openai-completions',baseUrl:`http://127.0.0.1:${server.address().port}/v1`,contextWindow:32000,maxTokens:1000}],piCapabilities:{preset:'minimal'}});
    await wait(()=>events.some(e=>e.type==='done'));
    const states=events.filter(e=>e.type==='state').length,done=events.filter(e=>e.type==='done').length;
    assert.equal((await catalog('skills')).skills.length,30);
    assert.ok((await catalog('extensions')).some(e=>e.path==='builtin:codemode'));
    assert.equal(events.filter(e=>e.type==='state').length,states);
    assert.equal(events.filter(e=>e.type==='done').length,done);
    assert.equal(requests,0,'Browsing a Widget sent an LLM request');
    send({type:'prompt',text:'Local streaming fixture'});await wait(()=>requests>0);
    for(let i=0;i<3;i++){await catalog('skills');await catalog('extensions');}
    assert.equal(events.filter(e=>e.type==='done').length,done,'A directory read ended the active turn');
    assert.equal(events.filter(e=>e.type==='state').length,states,'A directory read re-projected history');
    release();await wait(()=>events.filter(e=>e.type==='done').length>done);
    assert.equal(requests,1);console.log('WIDGET_CATALOG_MS',JSON.stringify(times));
  }finally{
    release();send({type:'shutdown'});if(child.exitCode===null)await new Promise(resolve=>child.once('exit',resolve));
    await new Promise(resolve=>server.close(resolve));rmSync(root,{recursive:true,force:true,maxRetries:5,retryDelay:30});
  }
});
