import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { builtins, extensionInfo, webLink, checkExtensionUpdate, manageResources } from "../runtime/resources.mjs";
import * as Pi from "../runtime/node_modules/@earendil-works/pi-coding-agent/dist/index.js";

test("discovery reads package metadata without executing disabled or untrusted extension code", async () => {
  const root=mkdtempSync(join(tmpdir(),"umeko-extension-info-"));
  try {
    const agent=join(root,"agent"),cwd=join(root,"project"),pkg=join(root,"fixture");
    for(const dir of [agent,cwd,join(pkg,"dist")]) mkdirSync(dir,{recursive:true});
    writeFileSync(join(pkg,"package.json"),JSON.stringify({name:"@fixture/web",version:"1.0.0",description:"Fixture functionality",homepage:"https://example.com/docs",repository:{url:"git+https://github.com/example/fixture.git"},pi:{extensions:["dist/index.js"]}}));
    writeFileSync(join(pkg,"dist/index.js"),"throw new Error('metadata discovery must never execute me')");
    writeFileSync(join(agent,"settings.json"),JSON.stringify({packages:[pkg]}));
    const {extensions}=await manageResources(Pi,{cwd,agentDir:agent,agent:{},action:"scan"});
    const row=extensions.find(row=>row.name==="@fixture/web");
    assert.equal(row.info.description,"Fixture functionality");
    assert.equal(row.info.version,"1.0.0");
    assert.equal(row.info.repository,"https://github.com/example/fixture");
    assert.equal(row.info.homepage,"https://example.com/docs");
    assert.equal(row.info.origin,"community");
    assert.equal(row.info.updateKind,"none","a local package is not assumed to be an npm installation");
    const core=extensions.find(row=>row.path==="builtin:mcp");
    assert.equal(core.info.origin,"pi"); assert.equal(core.info.version,"1.3.0");
    assert.equal(core.info.updateKind,"npm");
    assert.equal(extensions.find(row=>row.path==="builtin:chatbox").info.updateKind,"desktop");
    if(builtins.includes("subagents")) {
      const child=extensions.find(row=>row.path==="builtin:subagents");
      assert.equal(child.info.origin,"community"); assert.equal(child.info.bundled,true);
      assert.equal(child.info.package,"@gotgenes/pi-subagents"); assert.equal(child.info.version,"25.0.5");
      assert.match(child.info.repository,/github.com\/gotgenes\/pi-packages/);
    }
  } finally { rmSync(root,{recursive:true,force:true}); }
});

test("external metadata links accept web URLs and reject executable or credential-bearing URLs",()=>{
  for(const url of ["javascript:alert(1)","file:///etc/passwd","https://token@example.com/","data:text/html,test"]) assert.equal(webLink(url),"");
  assert.equal(webLink("git@github.com:example/repo.git"),"https://github.com/example/repo");
  assert.equal(webLink("git+https://github.com/example/repo.git"),"https://github.com/example/repo");
});

test("version checks compare semver, handle an older registry, and do not alter the installed package",async()=>{
  const row={id:"child",info:{package:"@fixture/web",version:"2.0.0",updateKind:"npm",bundled:true}};
  const original=JSON.stringify(row);
  assert.equal((await checkExtensionUpdate(row,{lookup:()=>"3.0.0"})).status,"available");
  assert.equal((await checkExtensionUpdate(row,{lookup:()=>"1.0.0"})).status,"current");
  assert.equal((await checkExtensionUpdate(row,{lookup:()=>"2.0.0"})).status,"current");
  await assert.rejects(checkExtensionUpdate(row,{lookup:()=>"not-version"}),/有效版本/);
  assert.equal(JSON.stringify(row),original);
});

test("real npm update probe uses the configured registry without installing the extension",{timeout:25000},async()=>{
  const root=mkdtempSync(join(tmpdir(),"umeko-extension-registry-"));
  const server=spawn(process.execPath,["--input-type=module","-e",`
    import http from 'node:http';
    const server=http.createServer((req,res)=>{
      if(!decodeURIComponent(req.url).includes('@fixture/web')) {res.writeHead(404);res.end();return;}
      res.setHeader('Content-Type','application/json');
      res.end(JSON.stringify({name:'@fixture/web','dist-tags':{latest:'3.1.0'},versions:{'3.1.0':{name:'@fixture/web',version:'3.1.0'}}}));
    });
    server.listen(0,'127.0.0.1',()=>console.log(server.address().port));
  `],{stdio:["ignore","pipe","pipe"]});
  const previous=process.env.npm_config_registry, cache=process.env.npm_config_cache;
  try {
    const [raw]=await once(server.stdout,"data");
    process.env.npm_config_registry="http://127.0.0.1:"+String(raw).trim();
    process.env.npm_config_cache=join(root,"npm-cache");
    const result=await checkExtensionUpdate({id:"package",info:{package:"@fixture/web",version:"1.0.0",updateKind:"npm"}},{cwd:root});
    assert.equal(result.latest,"3.1.0"); assert.equal(result.status,"available");
    assert.equal(extensionInfo({path:join(root,"not-installed.js"),metadata:{}}).package,"");
  } finally {
    server.kill(); await once(server,"exit");
    if(previous===undefined) delete process.env.npm_config_registry; else process.env.npm_config_registry=previous;
    if(cache===undefined) delete process.env.npm_config_cache; else process.env.npm_config_cache=cache;
    rmSync(root,{recursive:true,force:true});
  }
});

test("chat filters survive reload without changing native settings or another chat",async()=>{
  const {prepareNativeSettings,sessionResourceSettings}=await import("../runtime/resources.mjs");
  const root=mkdtempSync(join(tmpdir(),"umeko-chat-filters-"));
  try {
    const agent=join(root,"agent"),cwd=join(root,"project"),pkg=join(root,"package");
    for(const dir of [agent,join(cwd,".pi"),pkg])mkdirSync(dir,{recursive:true});
    writeFileSync(join(pkg,"package.json"),JSON.stringify({name:"fixture",type:"module",pi:{extensions:["index.js"]}}));
    const extension=join(pkg,"index.js"),marker=join(root,"executed");
    writeFileSync(extension,`import {writeFileSync} from 'node:fs'; writeFileSync(${JSON.stringify(marker)},'loaded'); export default ()=>{};`);
    const global={packages:[pkg],extensions:["-builtin:mcp"]},project={extensions:["-builtin:codemode"]};
    writeFileSync(join(agent,"settings.json"),JSON.stringify(global));writeFileSync(join(cwd,".pi/settings.json"),JSON.stringify(project));
    const input={cwd,agentDir:agent,agent:{}};
    const native=await prepareNativeSettings(Pi,input);
    const disabled=await sessionResourceSettings(Pi,{...input,sessionExtensions:{[extension]:false,"builtin:mcp":true,"builtin:codemode":true}},native);
    const enabledRows=async settings=>(await new Pi.DefaultPackageManager({cwd,agentDir:agent,settingsManager:settings,builtinExtensions:builtins}).resolve(async()=>"skip")).extensions;
    for(let pass=0;pass<2;pass++) {
      const rows=await enabledRows(disabled);
      assert.equal(rows.find(r=>r.path===extension).enabled,false);
      assert.equal(rows.find(r=>r.path==='builtin:mcp').enabled,true);
      assert.equal(rows.find(r=>r.path==='builtin:codemode').enabled,true);
      await disabled.reload();
    }
    global.theme="new-external-theme";
    writeFileSync(join(agent,"settings.json"),JSON.stringify(global));
    await disabled.reload();
    assert.equal(disabled.getGlobalSettings().theme,"new-external-theme");
    assert.equal((await enabledRows(disabled)).find(r=>r.path===extension).enabled,false);
    const loader=new Pi.DefaultResourceLoader({cwd,agentDir:agent,settingsManager:disabled});
    await loader.reload();
    assert.equal((await import('node:fs')).existsSync(marker),false,"disabled modules must not even be imported");
    const other=await enabledRows(await prepareNativeSettings(Pi,input));
    assert.equal(other.find(r=>r.path===extension).enabled,true);
    assert.equal(other.find(r=>r.path==='builtin:mcp').enabled,false);
    assert.deepEqual(JSON.parse((await import('node:fs')).readFileSync(join(agent,"settings.json"),'utf8')),global);
    assert.deepEqual(JSON.parse((await import('node:fs')).readFileSync(join(cwd,".pi/settings.json"),'utf8')),project);
  } finally {rmSync(root,{recursive:true,force:true});}
});

test("global enable promotes a project-only package and keeps relative sources correct",async()=>{
  const root=mkdtempSync(join(tmpdir(),"umeko-global-filter-"));
  try {
    const agent=join(root,"agent"),cwd=join(root,"project"),pkg=join(cwd,".pi/package");
    for(const dir of [agent,pkg])mkdirSync(dir,{recursive:true});
    writeFileSync(join(pkg,"package.json"),JSON.stringify({name:"fixture",pi:{extensions:["index.js"]}}));writeFileSync(join(pkg,"index.js"),"throw Error('no metadata imports')");
    writeFileSync(join(cwd,".pi/settings.json"),JSON.stringify({packages:[{source:"./package",extensions:["-index.js"]}]}));
    const input={cwd,agentDir:agent,agent:{}};
    const row=(await manageResources(Pi,input)).extensions.find(r=>r.name==='fixture');assert.equal(row.enabled,false);
    await manageResources(Pi,{...input,action:'enable-global',id:row.id});
    const other=join(root,"other");mkdirSync(other);
    assert.equal((await manageResources(Pi,{...input,cwd:other})).extensions.find(r=>r.name==='fixture').enabled,true);
    assert.equal((await manageResources(Pi,input)).extensions.find(r=>r.name==='fixture').enabled,true);
  } finally {rmSync(root,{recursive:true,force:true});}
});

test("detail documents are on-demand, bounded and do not request remote images",async()=>{
  const root=mkdtempSync(join(tmpdir(),"umeko-readme-"));
  try {
    const agent=join(root,"agent"),cwd=join(root,"project"),pkg=join(root,"package");
    for(const dir of [agent,cwd,pkg])mkdirSync(dir,{recursive:true});
    writeFileSync(join(pkg,"package.json"),JSON.stringify({name:"readme-fixture",pi:{extensions:["index.js"]}}));writeFileSync(join(pkg,"index.js"),"throw Error('README must not import code')");
    writeFileSync(join(pkg,"README.md"),'# Local README\n\n![tracking](https://example.com/track)\n\n'+"details\n".repeat(200000));
    writeFileSync(join(agent,"settings.json"),JSON.stringify({packages:[pkg]}));
    const input={cwd,agentDir:agent,agent:{}};
    const rows=(await manageResources(Pi,input)).extensions;
    assert.equal(rows.some(r=>'markdown' in r || 'markdown' in r.info),false);
    const details=(await manageResources(Pi,{...input,action:'details',id:rows.find(r=>r.name==='readme-fixture').id})).details;
    assert.equal(details.truncated,true);assert.ok(details.markdown.length<=48*1024);assert.match(details.markdown,/# Local README/);assert.doesNotMatch(details.markdown,/https:\/\/example.com\/track/);
    assert.ok(rows.every(r=>/^[a-z-]+$/.test(r.info.icon)));
  } finally {rmSync(root,{recursive:true,force:true});}
});


test("required desktop abilities ignore old disable filters and reject configuration changes",async()=>{
  const {prepareNativeSettings,sessionResourceSettings,requiredBuiltins}=await import("../runtime/resources.mjs");
  const {readFileSync}=await import("node:fs");
  const root=mkdtempSync(join(tmpdir(),"umeko-required-"));
  try {
    const agent=join(root,"agent"),cwd=join(root,"project");
    mkdirSync(agent,{recursive:true});mkdirSync(join(cwd,".pi"),{recursive:true});
    const original={extensions:["!builtin:*","-builtin:chatbox"],theme:"dark"};
    writeFileSync(join(agent,"settings.json"),JSON.stringify(original));
    writeFileSync(join(cwd,".pi/settings.json"),JSON.stringify({extensions:["!builtin:*","-builtin:chatbox"]}));
    const input={cwd,agentDir:agent,agent:{}};
    const native=await prepareNativeSettings(Pi,input);
    const settings=await sessionResourceSettings(Pi,{...input,sessionExtensions:Object.fromEntries([...requiredBuiltins].map(path=>[path,false]))},native);
    const rows=async()=>(await new Pi.DefaultPackageManager({cwd,agentDir:agent,settingsManager:settings,builtinExtensions:builtins}).resolve(async()=>"skip")).extensions;
    for(let pass=0;pass<2;pass++) {
      const result=await rows();
      for(const path of requiredBuiltins) assert.equal(result.find(row=>row.path===path).enabled,true,path);
      assert.equal(result.find(row=>row.path==='builtin:mcp').enabled,false);
      assert.equal(result.find(row=>row.path==='builtin:subagents').enabled,false);
      await settings.reload();
    }
    // Ordinary native setters retain persistence through the policy view.
    settings.setTheme('light');await settings.flush();
    assert.equal(JSON.parse(readFileSync(join(agent,'settings.json'),'utf8')).theme,'light');
    assert.deepEqual(JSON.parse(readFileSync(join(agent,'settings.json'),'utf8')).extensions,original.extensions);
    const scan=(await manageResources(Pi,input)).extensions;
    for(const path of requiredBuiltins) {
      const row=scan.find(row=>row.path===path);assert.equal(row.info.required,true);assert.equal(row.enabled,true);
      await assert.rejects(manageResources(Pi,{...input,action:'toggle',id:row.id,enabled:false}),/基础能力固定启用/);
      await assert.rejects(manageResources(Pi,{...input,action:'enable-global',id:row.id}),/基础能力固定启用/);
    }
    assert.equal(scan.find(row=>row.path==='builtin:mcp').info.required,false);
    assert.equal(scan.find(row=>row.path==='builtin:subagents').info.required,false);
  } finally {rmSync(root,{recursive:true,force:true});}
});
