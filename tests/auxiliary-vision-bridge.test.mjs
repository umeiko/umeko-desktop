import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync} from 'node:fs';
import {rm} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const png='iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAACXBIWXMAAA9hAAAPYQGoP6dpAAAAKElEQVRIie3NMQEAAAjDMMC/ZzDBvlRA01vZJvwHAAAAAAAAAAAAbx2jxAE/0VKtIwAAAABJRU5ErkJggg==';
test('real Pi uses automatic observations, calls the desktop tool and bypasses it for native vision', {timeout:60000},async t=>{
  const dir=mkdtempSync(join(tmpdir(),'umeko-vision-'));
  const agentDir=join(dir,'agent');mkdirSync(agentDir);
  writeFileSync(join(agentDir,'settings.json'),JSON.stringify({retry:{enabled:false},cacheWarming:'off'}));
  const path=join(dir,'image.png');writeFileSync(path,Buffer.from(png,'base64'));
  mkdirSync(join(agentDir,'extensions'));
  writeFileSync(join(agentDir,'extensions','images.mjs'),`export default pi => {
    pi.on('before_agent_start', event => {
      if(event.prompt === 'custom image') return {message:{customType:'fixture-image',display:false,
        content:[{type:'text',text:'Describe this custom image'},{type:'image',mimeType:'image/png',data:${JSON.stringify(png)}}]}};
    });
    pi.on('before_provider_request', event => {
      const payload=event.payload;
      if(!JSON.stringify(payload.messages).includes('late payload image')) return;
      return {...payload,fixture_marker:'extension preserved',messages:[...payload.messages,
        {role:'user',content:[{type:'text',text:'Late extension image'},
          {type:'image_url',image_url:{url:'data:image/png;base64,${png}'}}]}]};
    });
  };`);
  writeFileSync(join(agentDir,'settings.json'),JSON.stringify({retry:{enabled:false},cacheWarming:'off',
    extensions:[join(agentDir,'extensions','images.mjs')]}));
  const requests=[],errors=[];
  let calls=0;
  let enteredCancel,closedCancel;
  const cancelEntered=new Promise(resolve=>enteredCancel=resolve);
  const cancelClosed=new Promise(resolve=>closedCancel=resolve);
  const server=createServer(async(req,res)=>{
    let raw='';for await(const part of req)raw+=part;
    const body=JSON.parse(raw);requests.push(body);
    let delta={role:'assistant',content:'complete'},reason='stop';
    if(body.model==='eyes') {
      assert.equal(body._umeko_provider,'vision-provider');assert.equal(body.tools,undefined);
      if(JSON.stringify(body.messages).includes('cancel helper')) {
        res.on('close',closedCancel);res.writeHead(200,{'Content-Type':'text/event-stream'});
        res.write('data: '+JSON.stringify({choices:[{delta:{role:'assistant'}}]})+'\n\n');enteredCancel();return;
      }
      if(JSON.stringify(body.messages).includes('force failure')) {
        res.writeHead(400,{'Content-Type':'application/json'});res.end(JSON.stringify({error:{message:'Fixture vision rejected this image'}}));return;
      }
      delta.content='The image contains a blue square. '+(++calls);
    } else {
      const images=body.messages.flatMap(row=>Array.isArray(row.content)?row.content:[]).filter(block=>block.type==='image_url');
      const text=JSON.stringify(body.messages);
      if(body.model==='text') {
        if(images.length) {
          errors.push('Raw image reached the text-only model');
          res.writeHead(406,{'Content-Type':'application/json'});
          res.end(JSON.stringify({error:{message:'The multimodal content of text is incorrect'}}));return;
        }
        if(!text.includes('manual followup') && !text.includes('late payload image') &&
           !text.includes('read image through native tool') && !text.includes('blue square'))errors.push('Automatic observation missing');
        if(text.includes('late payload image'))assert.equal(body.fixture_marker,'extension preserved');
        if(body.messages.at(-1).role==='user' && text.includes('manual followup')) {
          delta={role:'assistant',tool_calls:[{index:0,id:'analyze-1',type:'function',function:{name:'analyze_image',arguments:JSON.stringify({paths:[path],question:'Read the image carefully'})}}]};
          reason='tool_calls';
        } else if(body.messages.at(-1).role==='user' && text.includes('read image through native tool')) {
          delta={role:'assistant',tool_calls:[{index:0,id:'read-image',type:'function',function:{name:'read',arguments:JSON.stringify({path})}}]};
          reason='tool_calls';
        }
      } else assert.equal(images.length,1,'Native model receives its original image');
    }
    res.writeHead(200,{'Content-Type':'text/event-stream'});
    res.end(`data: ${JSON.stringify({choices:[{index:0,delta,finish_reason:null}]})}\n\ndata: ${JSON.stringify({choices:[{index:0,delta:{},finish_reason:reason}]})}\n\ndata: [DONE]\n\n`);
  });
  server.listen(0,'127.0.0.1');await once(server,'listening');
  let child,lines,stderr='';
  function start() {
    child=spawn(process.execPath,[join(root,'runtime/releases/coding-1.3.0/bridge.mjs')],{cwd:dir,stdio:['pipe','pipe','pipe'],windowsHide:true});
    child.stderr.on('data',chunk=>stderr+=chunk);
    lines=createInterface({input:child.stdout})[Symbol.asyncIterator]();
  }
  async function stop() {if(child.exitCode===null){child.stdin.write(JSON.stringify({type:'shutdown'})+'\n');await once(child,'exit');}}
  start();
  t.after(async()=>{
    await stop();
    server.closeAllConnections();await new Promise(resolve=>server.close(resolve));await rm(dir,{recursive:true,force:true,maxRetries:5,retryDelay:100});
  });
  async function command(payload,allowError=false) {
    child.stdin.write(JSON.stringify(payload)+'\n');const events=[];
    for(;;){const row=await lines.next();assert.ok(!row.done,stderr);const event=JSON.parse(row.value);events.push(event);if(event.type==='done')break;}
    if(!allowError)assert.deepEqual(events.filter(event=>event.type==='error'),[],stderr);
    return events;
  }
  const initial={type:'inspect',gateway:`http://127.0.0.1:${server.address().port}/`,token:'fixture',workspace:dir,defaultCwd:dir,agentDir,sessionDir:join(dir,'sessions'),
    models:[{id:'text',input:['text'],contextWindow:128000},{id:'native',input:['text','image'],contextWindow:128000}],model:'text',agent:{safeMode:false,autoCompaction:false},
    auxiliaryVision:{providerId:'vision-provider',model:'eyes',modelName:'vision-upstream-model',providerName:'Fixture',label:'Fixture / eyes',autoAnalyze:true,toolEnabled:true}};
  const inspected=await command(initial);
  const loaded=inspected.findLast(event=>event.type==='state').resources.extensions.find(row=>row.path?.endsWith('images.mjs'));
  assert.ok(loaded,JSON.stringify(inspected.filter(event=>['notice','error'].includes(event.type))));
  const events=await command({type:'prompt',text:'Describe the square',images:[{type:'image',data:png,mimeType:'image/png'}]});
  assert.equal(calls,1);assert.deepEqual(errors,[]);
  const automatic=events.filter(event=>event.type==='tool' && event.args?.automatic);
  assert.deepEqual(automatic.map(event=>event.state),['running','done']);
  assert.equal(automatic[0].name,'analyze_image');assert.equal(automatic[0].args.model,'vision-upstream-model');assert.equal(automatic[0].args.provider,'Fixture');
  const state=events.findLast(event=>event.type==='state');
  const catalog=state.resources.toolCatalog.find(row=>row.name==='analyze_image');
  assert.equal(catalog.owner,'builtin:umeko-control');
  const file=state.session.file;
  const native=readFileSync(file,'utf8').trim().split('\n').map(line=>JSON.parse(line));
  const original=native.find(entry=>entry.type==='message' && entry.message.role==='user').message;
  assert.ok(original.content.some(block=>block.type==='image' && block.data===png),'Original image is saved in native history');
  assert.ok(!JSON.stringify(original).includes('blue square'),'Observations never replace the original user attachment');
  assert.equal(native.filter(entry=>entry.customType==='umeko-auto-vision').length,1);
  assert.ok(state.messages.some(row=>row.tools?.some(tool=>tool.arguments.automatic && tool.state==='done')),'History contains the host-initiated analysis operation');
  for(const text of ['follow up without images','a second unrelated question']) {
    const followup=await command({type:'prompt',text});
    assert.equal(calls,1,'A follow-up must not resend historical images');
    assert.ok(!followup.some(event=>event.type==='tool' && event.args?.automatic));
  }
  await stop();start();
  const reopened=await command({...initial,sessionFile:file});
  assert.ok(reopened.findLast(event=>event.type==='state').messages.some(row=>row.tools?.some(tool=>tool.arguments.automatic)));
  await command({type:'prompt',text:'After restarting the application'});
  assert.equal(calls,1,'Restarting Pi must recover observations without contacting the helper');
  const manual=await command({type:'prompt',text:'manual followup'});
  assert.equal(calls,2,'Only the explicit detailed query contacts the helper again');
  const manualTool=manual.findLast(event=>event.type==='state').messages.flatMap(row=>row.tools || []).find(tool=>tool.id==='analyze-1');
  assert.equal(manualTool.arguments.model,'vision-upstream-model','Native tool history retains the actual model name');
  assert.equal(manualTool.arguments.provider,'Fixture');
  await command({type:'new',model:'text'});
  const late=await command({type:'prompt',text:'late payload image'});
  assert.ok(!late.some(event=>event.type==='message' && event.error),'Late extension images must not cause a primary-model 406');
  assert.deepEqual(errors,[]);
  await command({type:'new',model:'text'});
  const custom=await command({type:'prompt',text:'custom image'});
  assert.deepEqual(errors,[]);
  assert.equal(calls,3,'Custom messages also need an auxiliary visual observation');
  assert.ok(!custom.some(event=>event.type==='message' && event.error),'Custom images must not cause a primary-model 406');
  await command({type:'new',model:'text'});
  await command({type:'prompt',text:'read image through native tool'});
  assert.equal(calls,4,'Images returned by native tools are interpreted before the primary continuation');
  assert.ok(requests.findLast(body=>body.model==='text').messages.some(row=>row.role==='tool' && row.content.includes('blue square')));
  const before=calls;
  await command({type:'new',model:'native'});
  await command({type:'prompt',text:'Use native vision',images:[{type:'image',data:png,mimeType:'image/png'}]});
  assert.equal(calls,before);assert.deepEqual(errors,[]);
  await command({type:'new',model:'text'});
  const primaryBefore=requests.filter(body=>body.model==='text').length;
  const cancelled=command({type:'prompt',text:'cancel helper',images:[{type:'image',data:png,mimeType:'image/png'}]});
  await cancelEntered;child.stdin.write(JSON.stringify({type:'abort'})+'\n');
  await cancelled;await cancelClosed;
  assert.equal(requests.filter(body=>body.model==='text').length,primaryBefore,'Cancellation must not send a partial observation to the main model');
  await command({type:'new',model:'text'});
  const failed=await command({type:'prompt',text:'force failure',images:[{type:'image',data:png,mimeType:'image/png'}]},true);
  assert.ok(failed.some(event=>event.type==='error' && event.message.includes('Fixture vision rejected')));
  assert.equal(requests.filter(body=>body.model==='text').length,primaryBefore,'A failed analysis must not silently continue without the image');
});
