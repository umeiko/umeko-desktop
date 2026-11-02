import test from 'node:test';
import assert from 'node:assert/strict';
import {CORE_TOOLS,MINIMAL_TOOLS,capabilityProfile,toolSelection,pluginSelection,excludedSessionTools,controlledExtensions,collectToolCatalog} from '../runtime/session-capabilities.mjs';
test('full preserves normal configured capabilities, standard has eight tools, minimal has four',()=>{
  for(const preset of ['full','standard','minimal']) {
    const profile={preset}, core=CORE_TOOLS.filter(name=>toolSelection(profile,{name,source:'native'}));
    assert.deepEqual(core,preset==='minimal'?MINIMAL_TOOLS.filter(n=>CORE_TOOLS.includes(n)).sort((a,b)=>CORE_TOOLS.indexOf(a)-CORE_TOOLS.indexOf(b)):CORE_TOOLS);
    assert.equal(pluginSelection(profile,'builtin:umeko-control'),preset==='full');
  }
  assert.equal(pluginSelection({},'/disabled-extension',false),false);
});
test('custom tool exclusions and parent switches cannot be bypassed by deferred exposure',()=>{
  const profile={preset:'custom',custom:{base:'full',tools:{run_pi_command:false,mcp__sample__read:false},plugins:{'builtin:chatbox':false,native:false}}};
  assert.equal(toolSelection(profile,{name:'submit_to_chatbox',source:'builtin:chatbox'}),false);
  assert.equal(toolSelection(profile,{name:'read',source:'native'}),false);
  assert.equal(toolSelection(profile,{name:'run_pi_command',source:'builtin:pi-commands',exposure:'deferred'}),false);
  assert.ok(excludedSessionTools(profile).includes('mcp__sample__read'));
  assert.ok(excludedSessionTools(profile).includes('read'));
});
test('session presets override legacy enables without writing global configuration',()=>{
  const rows=[{path:'builtin:umeko-control'},{path:'builtin:mcp'},{path:'/package/index.js'}],legacy={'builtin:mcp':true};
  assert.deepEqual(controlledExtensions({preset:'minimal'},rows,legacy),Object.fromEntries(rows.map(r=>[r.path,false])));
  assert.deepEqual(controlledExtensions({preset:'custom',custom:{base:'minimal',plugins:{'builtin:mcp':true}}},rows,legacy),{'builtin:umeko-control':false,'builtin:mcp':true,'/package/index.js':false});
  assert.equal(capabilityProfile({preset:'invalid'}).preset,'full');
});
test('catalog keeps filtered extension definitions, including dynamically registered MCP tools',()=>{
  const session={resourceLoader:{getExtensions:()=>({extensions:[{path:'builtin:mcp',tools:new Map([['x',{definition:{name:'mcp__sample__read',description:'Read'}}]])}]})},getAllTools:()=>[{name:'read',description:'Read file',sourceInfo:{kind:'builtin',path:'builtin:read'}}]};
  assert.deepEqual(collectToolCatalog(session).map(t=>[t.name,t.owner]),[['mcp__sample__read','builtin:mcp'],['read','native']]);
});
