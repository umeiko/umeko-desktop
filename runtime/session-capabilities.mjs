// A per-conversation loadout. Native Pi settings on disk remain unchanged.
export const CORE_TOOLS = ['read', 'bash', 'powershell', 'edit', 'write', 'grep', 'find', 'ls'];
export const MINIMAL_TOOLS = ['read', 'bash', 'edit', 'write'];
const presets = new Set(['full', 'standard', 'minimal', 'custom']);
export function capabilityProfile(value = {}) {
  const preset = presets.has(value?.preset) ? value.preset : 'full';
  const custom = value?.custom || {};
  const clean = (map, max) => Object.fromEntries(Object.entries(map && typeof map === 'object' && !Array.isArray(map) ? map : {})
    .filter(([key, enabled]) => key.length > 0 && key.length <= max && typeof enabled === 'boolean').slice(0, 2000));
  return {preset, custom:{base:['full','standard','minimal'].includes(custom.base) ? custom.base : 'full',
    tools:clean(custom.tools,256), plugins:clean(custom.plugins,4096)}};
}
export function effectiveProfile(value) {
  const profile=capabilityProfile(value);
  return profile.preset==='custom' ? profile.custom : {base:profile.preset,tools:{},plugins:{}};
}
export function pluginSelection(value, source, nativeEnabled = true) {
  const profile=effectiveProfile(value);
  if (typeof profile.plugins[source]==='boolean') return profile.plugins[source];
  return source==='native' || (profile.base==='full' && nativeEnabled);
}
export function sourceOf(tool) {
  const source=tool.sourceInfo?.path || tool.source;
  if (CORE_TOOLS.includes(tool.name) && (source==='builtin:'+tool.name || source==='native' || (!source && tool.sourceInfo?.kind==='builtin'))) return 'native';
  if (tool.name.startsWith('mcp__')) return 'builtin:mcp';
  return tool.owner || tool.sourceInfo?.path || tool.source || 'Pi';
}
export function toolSelection(value, tool, nativeEnabled = true) {
  const profile=effectiveProfile(value), source=sourceOf(tool);
  if (!pluginSelection(value,source,nativeEnabled)) return false;
  if (typeof profile.tools[tool.name]==='boolean') return profile.tools[tool.name];
  return source!=='native' || profile.base!=='minimal' || MINIMAL_TOOLS.includes(tool.name);
}
export function excludedSessionTools(value) {
  const profile=effectiveProfile(value), excluded=new Set();
  for (const name of CORE_TOOLS) if(!toolSelection(value,{name,source:'native'})) excluded.add(name);
  for (const [name, enabled] of Object.entries(profile.tools)) if(!enabled) excluded.add(name);
  return [...excluded];
}
export function controlledExtensions(value, rows, legacy = {}) {
  const profile=effectiveProfile(value), overrides={};
  for(const row of rows) {
    if(typeof profile.plugins[row.path]==='boolean') overrides[row.path]=profile.plugins[row.path];
    else if(profile.base!=='full') overrides[row.path]=false;
    else if(typeof legacy[row.path]==='boolean') overrides[row.path]=legacy[row.path];
  }
  return overrides;
}
export function collectToolCatalog(session) {
  const tools=new Map();
  // Extension definitions survive tool allow/deny filtering, so disabled tools
  // remain visible and can be re-enabled after reload. Dynamic MCP tools too.
  for(const extension of session.resourceLoader.getExtensions().extensions) {
    for(const registered of extension.tools?.values?.() || []) {
      const tool=registered.definition || registered;
      if(tool.name) tools.set(tool.name,{name:tool.name,description:tool.description || '',parameters:tool.parameters,
        exposure:tool.exposure || 'direct',source:extension.path,owner:sourceOf({...tool,source:extension.path})});
    }
  }
  for(const tool of session.getAllTools()) tools.set(tool.name,{name:tool.name,description:tool.description,parameters:tool.parameters,
    exposure:tool.exposure,source:tool.sourceInfo?.path || tool.sourceInfo?.kind || 'Pi',owner:sourceOf(tool)});
  return [...tools.values()];
}
