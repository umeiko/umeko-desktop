import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {chatboxExtension, chatboxItems} from '../runtime/releases/coding-1.3.0/chatbox.mjs';
import {componentSpec} from '../runtime/releases/coding-1.3.0/webview-component.mjs';

test('URL submissions reuse the delivery protocol and guidance appears only when the component is missing', async () => {
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'umeko-webview-'));
  try {
    const entries=[];let tool;let available=true;
    chatboxExtension({registerTool(value){tool=value;},appendEntry(...value){entries.push(value);}},()=>({available,directory}));
    assert.ok(!JSON.stringify([tool.description,tool.promptSnippet,tool.promptGuidelines]).includes('optional Qt WebEngine component'));
    const submit=()=>tool.execute('delivery',{items:[{path:'http://127.0.0.1:8791/review.html',title:'Preview'}]},new AbortController().signal,null,{cwd:directory});
    let result=await submit();let payload=JSON.parse(result.content[0].text);
    assert.deepEqual(payload.webview,{status:'ready'});
    assert.equal(chatboxItems(tool.name,result)[0].presentation,'webview');
    assert.equal(entries.length,1);
    available=false;result=await submit();payload=JSON.parse(result.content[0].text);
    const optionalEngine = process.platform==='linux' && process.arch==='x64';
    assert.equal(payload.webview.status,optionalEngine ? 'component_required' : 'unavailable');
    if (optionalEngine) {
      assert.match(payload.webview.instructions,/SHA-256/);
      assert.equal(payload.webview.downloadUrl,componentSpec.url);
      assert.equal(payload.webview.sha256,componentSpec.sha256);
    } else assert.ok(!payload.webview.instructions);
    assert.equal(chatboxItems(tool.name,result)[0].presentation,'external');
    assert.ok(!payload.webview.downloadCommand && !payload.webview.installCommand);
    const file=path.join(directory,'report.txt');await fs.writeFile(file,'report');
    result=await tool.execute('file',{items:[{path:file}]},null,null,{cwd:directory});
    assert.ok(!JSON.parse(result.content[0].text).webview);
    await assert.rejects(tool.execute('bad',{items:[{path:'https://name:secret@example.com/'}]},null,null,{cwd:directory}));
    await assert.rejects(tool.execute('bad',{items:[{path:'javascript:alert(1)'}]},null,null,{cwd:directory}));
    if (optionalEngine) {
    for (const file of ['manifest.json','lib/libQt6WebEngineCore.so.6','libexec/QtWebEngineProcess','plugins/webview/libqtwebview_webengine.so']) {
      const full=path.join(directory,'fixture',file); await fs.mkdir(path.dirname(full),{recursive:true}); await fs.writeFile(full,file==='manifest.json' ? JSON.stringify({id:componentSpec.id,qt:componentSpec.qt}) : 'fixture');
    }
    await fs.writeFile(path.join(directory,'active.json'),JSON.stringify({id:componentSpec.id,sha256:componentSpec.sha256,directory:'fixture'}));
    payload=JSON.parse((await submit()).content[0].text);
    assert.equal(payload.webview.status,'restart_required');
    assert.ok(!payload.webview.instructions);
    }
  } finally {await fs.rm(directory,{recursive:true,force:true});}
});

test('documents are delivered by reference with automatic kinds and artifact guidance', async () => {
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'umeko-artifacts-'));
  try {
    let tool;const entries=[];
    chatboxExtension({registerTool(value){tool=value;},appendEntry(...value){entries.push(value);}});
    const cases=[['report.md','markdown'],['main.py','code'],['notes.txt','text'],['index.html','code'],['report.pdf','file'],['CMakeLists.txt','code']];
    for (const [file] of cases) await fs.writeFile(path.join(directory,file),'Artifact content must stay out of the model context');
    const result=await tool.execute('artifacts',{items:cases.map(([file])=>({path:file}))},null,null,{cwd:directory});
    const payload=JSON.parse(result.content[0].text);
    assert.deepEqual(payload.submitted.map(item=>item.kind),cases.map(([,kind])=>kind));
    assert.ok(!payload.webview);
    assert.ok(!JSON.stringify(result).includes('Artifact content must'));
    assert.equal(entries.length,1);
    assert.match(tool.promptGuidelines[0],/after creating or updating.*artifact/);
    const forced=await tool.execute('text',{items:[{path:'report.pdf',kind:'text'}]},null,null,{cwd:directory});
    assert.equal(JSON.parse(forced.content[0].text).submitted[0].kind,'text');
  } finally {await fs.rm(directory,{recursive:true,force:true});}
});
