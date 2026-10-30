// Run against the frozen package, outside its source runtime dependency tree.
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {tmpdir} from 'node:os';
import {pathToFileURL} from 'node:url';

const runtime=resolve(process.argv[2]);
const temporary=await mkdtemp(join(tmpdir(),'umeko-packaged-background-'));
process.env.PI_CODING_AGENT_DIR=join(temporary,'agent');
let jobs;
try {
  const load=name=>import(pathToFileURL(join(runtime,name)).href);
  const {createJobManager}=await load('background-jobs.mjs');
  const {createToolPermissionExtension}=await load('tool-permissions.mjs');
  const {blockedProcessCommand}=await load('process-guard.mjs');
  assert.ok(blockedProcessCommand('sudo pkill fixture'));
  assert.equal(blockedProcessCommand("printf '%s' 'pkill fixture'"),undefined);
  let hook,prompts=0;
  createToolPermissionExtension({getPolicy:()=>({mode:'ask'})})({on:(_name,handler)=>{hook=handler;}});
  const denied=await hook({toolName:'background_job',input:{action:'start',command:'printf harmless'}},
    {cwd:temporary,hasUI:true,ui:{confirm:async()=>{prompts++;return false;}}});
  assert.equal(denied.block,true);assert.equal(prompts,1);
  jobs=await createJobManager({cwd:temporary});
  const quote=value=>"'"+value.replaceAll("'","'\\''")+"'";
  const command=quote(process.execPath.replaceAll('\\','/'))+' -e '+quote("console.log('UMEKO_BACKGROUND_PACKAGED_OK');console.error('separate stderr')");
  const job=await jobs.start({command});
  assert.equal((await jobs.wait(job.id,{timeoutMs:10000})).exitCode,0);
  const output=await jobs.read(job.id);
  assert.equal(output.stdout,'UMEKO_BACKGROUND_PACKAGED_OK\n');
  assert.equal(output.stderr,'separate stderr\n');
  assert.equal(output.hasMore,false);
  console.log('Packaged background job, separate logs and permission gate verified');
} finally {
  await jobs?.dispose();
  if(jobs)await rm(jobs.directory,{recursive:true,force:true});
  await rm(temporary,{recursive:true,force:true});
}
