import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {rootCertificates} from 'node:tls';
import {createRegistryClient} from '../runtime/marketplace-source.mjs';

test('registry client applies Umeko registry, userconfig and CA paths',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'umeko-marketplace-config-'));
 const userconfig=join(dir,'test.npmrc');const cafile=join(dir,'test-ca.pem');
 await writeFile(cafile,rootCertificates[0]);
 await writeFile(userconfig,'registry=https://userconfig.example.invalid/\n');
 let requested;
 const client=createRegistryClient({
  agent:{npmRegistry:'https://umeko-config.example.invalid/registry/',npmUserconfig:userconfig,npmCafile:cafile},
  fetch:async(url)=>{requested=url;return Response.json({'dist-tags':{latest:'1.0.0'},versions:{'1.0.0':{name:'fixture',version:'1.0.0',keywords:['pi-package'],pi:{extensions:['index.ts']},dist:{tarball:'https://umeko-config.example.invalid/fixture.tgz'}}}});}
 });
 try {
  const detail=await client.getPackageDetail('fixture');
  assert.equal(detail.name,'fixture');
  assert.equal(requested,'https://umeko-config.example.invalid/registry/fixture');
  const config=await client.getConfiguration();
  assert.equal(config.registry,'https://umeko-config.example.invalid/registry');
  assert.equal(config.cafile,cafile);
 }finally{await client.close();await rm(dir,{recursive:true,force:true});}
});

test('malformed null search response uses visible exact-name fallback',async()=>{
 const client=createRegistryClient({agent:{npmRegistry:'https://fixture.example.invalid'},fetch:async(url)=>{
  if(url.includes('/-/v1/search'))return Response.json(null);
  return Response.json({'dist-tags':{latest:'1.0.0'},versions:{'1.0.0':{name:'fixture',version:'1.0.0',keywords:['pi-package'],pi:{extensions:['index.ts']}}}});
 }});
 try{const result=await client.searchPackages('fixture');assert.equal(result.method,'exact-name');assert.match(result.searchError,/non-search/);}
 finally{await client.close();}
});

test('HTTP404 exact-name fallback requires the pi-package keyword',async()=>{
 const client=createRegistryClient({agent:{npmRegistry:'https://fixture.example.invalid'},fetch:async(url)=>{
  if(url.includes('/-/v1/search'))return new Response('',{status:404});
  const name=url.endsWith('/untagged')?'untagged':'tagged';
  return Response.json({'dist-tags':{latest:'1.0.0'},versions:{'1.0.0':{name,version:'1.0.0',keywords:name==='tagged'?['pi-package']:[],pi:{extensions:['index.ts']}}}});
 }});
 try{
  const result=await client.searchPackages('tagged');
  assert.equal(result.method,'exact-name');assert.match(result.searchError,/HTTP 404/);
  assert.equal(result.packages[0].name,'tagged');
  await assert.rejects(()=>client.searchPackages('untagged'),/not tagged pi-package/);
 }finally{await client.close();}
});
