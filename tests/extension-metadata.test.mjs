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
