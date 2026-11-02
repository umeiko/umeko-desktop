import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,existsSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
const bridge=fileURLToPath(new URL('../runtime/releases/coding-1.3.0/bridge.mjs',import.meta.url));
const core=['bash','edit','find','grep','ls','powershell','read','write'];
test('real Pi presets control imports, tool registration, nested calls and restored chat loadouts',{timeout:120000},async()=>{
  const root=mkdtempSync(join(tmpdir(),'umeko-capabilities-')),cwd=join(root,'work'),agentDir=join(root,'agent'),sessions=join(root,'sessions');
  for(const path of [cwd,agentDir,join(agentDir,'extensions'),sessions])mkdirSync(path,{recursive:true});
  const marker=join(root,'imported'),executed=join(root,'executed');
  writeFileSync(join(agentDir,'extensions','fixture.mjs'),`import {writeFileSync} from 'node:fs';export default pi=>{
    writeFileSync(${JSON.stringify(marker)},'loaded');
    pi.registerTool({name:'fixture_secret',label:'Secret',description:'Filtered deferred tool',exposure:'codemode',parameters:{type:'object',properties:{}},execute:async()=>{writeFileSync(${JSON.stringify(executed)},'executed');return {content:[{type:'text',text:'should not execute'}]}}});
    pi.registerTool({name:'fixture_probe',label:'Probe',description:'Probe nested execution',parameters:{type:'object',properties:{}},execute:async(_id,_args,_signal,_update,ctx)=>ctx.executeTool('fixture_secret',{})});
  };`);
  const settings=JSON.stringify({extensions:[join(agentDir,'extensions','fixture.mjs'),'+builtin:umeko-control','+builtin:mcp'],compaction:{enabled:false}});
  writeFileSync(join(agentDir,'settings.json'),settings);
  let probe=true;const requests=[];
  const server=createServer(async(req,res)=>{
    let raw='';for await(const part of req)raw+=part;const body=JSON.parse(raw);requests.push(body);
    const delta=probe ? {role:'assistant',content:null,tool_calls:[{index:0,id:'probe',type:'function',function:{name:'fixture_probe',arguments:'{}'}}]} : {role:'assistant',content:'done'};probe=false;
    const chunk={id:'fixture',object:'chat.completion.chunk',created:1,model:'fixture'};
    res.writeHead(200,{'Content-Type':'text/event-stream'});res.end(`data: ${JSON.stringify({...chunk,choices:[{index:0,delta,finish_reason:null}]})}\n\ndata: ${JSON.stringify({...chunk,choices:[{index:0,delta:{},finish_reason:delta.tool_calls?'tool_calls':'stop'}]})}\n\ndata: [DONE]\n\n`);
  });
  await new Promise(done=>server.listen(0,'127.0.0.1',done));
  const children=[];
  async function start(profile,targetFile){
    const process=spawn(globalThis.process.execPath,[bridge],{cwd,stdio:['pipe','pipe','pipe']});children.push(process);
    const events=[];let buffer='',stderr='';process.stderr.on('data',v=>stderr+=v);process.stdout.on('data',v=>{buffer+=v;let n;while((n=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,n);buffer=buffer.slice(n+1);if(line)events.push(JSON.parse(line));}});
    const send=value=>process.stdin.write(JSON.stringify(value)+'\n');
    const wait=async predicate=>{const until=Date.now()+30000;while(Date.now()<until){if(predicate())return;if(process.exitCode!==null)throw Error('Pi exited before completing the request: '+process.exitCode+' '+stderr);await new Promise(done=>setTimeout(done,20));}throw Error('Timed out: '+JSON.stringify(events.slice(-3))+' '+stderr);};
    send({type:'inspect',workspace:cwd,defaultCwd:cwd,agentDir,sessionDir:sessions,targetFile,model:'fixture',models:[{id:'fixture',contextWindow:128000}],gateway:`http://127.0.0.1:${server.address().port}/`,token:'fixture',agent:{},piCapabilities:profile});
    await wait(()=>events.some(e=>e.type==='state') && events.some(e=>e.type==='done'));
    return {events,send,wait,process,state:()=>events.filter(e=>e.type==='state').at(-1),close:async()=>{send({type:'shutdown'});await new Promise(resolve=>process.once('exit',resolve));}};
  }
  try{
    for(const [preset,expected] of [['minimal',['bash','edit','read','write']],['standard',core]]){
      const child=await start({preset});assert.deepEqual([...child.state().resources.tools].sort(),expected);
      assert.equal(existsSync(marker),false,'Disabled extension module was imported');await child.close();
    }
    const custom={preset:'custom',custom:{base:'full',tools:{fixture_secret:false,umeko_desktop:false,tool_search:false},plugins:{'builtin:chatbox':false}}};
    const child=await start(custom);assert.equal(existsSync(marker),true);
    const resources=child.state().resources;
    for(const name of ['fixture_secret','umeko_desktop','tool_search','submit_to_chatbox'])assert.ok(!resources.allTools.some(t=>t.name===name&&t.visible),name+' remained visible');
    assert.ok(resources.toolCatalog.some(t=>t.name==='fixture_secret'),'Filtered tool disappeared from management catalog');
    const completed=child.events.filter(e=>e.type==='done').length;
    child.send({type:'prompt',text:'Probe disabled tool'});await child.wait(()=>child.events.filter(e=>e.type==='done').length>completed);
    assert.equal(existsSync(executed),false,'Nested execution bypassed the exclusion');
    const blocked=child.events.find(e=>e.type==='tool'&&e.name==='fixture_secret'&&e.state==='error');assert.ok(blocked,JSON.stringify(child.events.filter(e=>['error','notice','tool','done'].includes(e.type))).slice(-8000));
    assert.match(blocked.result,/not found|unknown|not available|not registered/i);
    assert.ok(!JSON.stringify(requests[0].tools).includes('fixture_secret'));
    const file=child.state().session.file;assert.ok(file);await child.close();
    const reopened=await start({preset:'minimal'},file);assert.deepEqual([...reopened.state().resources.tools].sort(),['bash','edit','read','write']);await reopened.close();
    assert.equal(readFileSync(join(agentDir,'settings.json'),'utf8'),settings,'A session preset modified global Pi settings');
  }finally{
    for(const child of children)if(child.exitCode===null)child.kill();
    await new Promise(done=>server.close(done));rmSync(root,{recursive:true,force:true,maxRetries:5,retryDelay:30});
  }
});
