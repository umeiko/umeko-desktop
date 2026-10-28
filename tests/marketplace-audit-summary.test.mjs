import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {c as createTar} from '../runtime/node_modules/tar/dist/esm/index.js';
import {createRegistryClient} from '../runtime/marketplace-source.mjs';

test('audit summary reports six medium findings accurately',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'umeko-audit-summary-'));
 await mkdir(join(dir,'package'));
 await writeFile(join(dir,'package','index.js'),Array.from({length:6},(_,i)=>`const value${i}=process.env.VALUE_${i};`).join('\n'));
 const archive=join(dir,'fixture.tgz');
 await createTar({file:archive,cwd:dir,gzip:true},['package']);
 const bytes=await readFile(archive);
 const client=createRegistryClient({agent:{npmRegistry:'https://fixture.example.invalid'},fetch:async(url)=>{
  if(url.endsWith('/fixture.tgz'))return new Response(bytes);
  return Response.json({'dist-tags':{latest:'1.0.0'},versions:{'1.0.0':{name:'summary-fixture',version:'1.0.0',pi:{extensions:['index.js']},dist:{tarball:'https://fixture.example.invalid/fixture.tgz'}}}});
 }});
 try{
  const result=await client.fullAudit('summary-fixture',true,'1.0.0');
  assert.equal(result.overallRisk,'medium');
  assert.equal(result.findings.length,6);
  assert.ok(result.findings.every(finding=>finding.severity==='medium'));
  assert.equal(result.summary,'6 finding(s) found (0 critical, 0 high, 6 medium, 0 low, 0 info).');
 }finally{await client.close();await rm(dir,{recursive:true,force:true});}
});
