// Desktop-only, per-conversation visibility. Native Pi exclusion removes tools
// from declarations, discovery and nested execution, including after /reload.
export function blockedToolNames(value) {
  return Array.isArray(value) ? [...new Set(value.filter(name => typeof name === "string" && name.length > 0 && name.length <= 256 && !/[*?\x00-\x20]/.test(name)))].slice(0, 4096) : [];
}

// Administrative inventory intentionally includes excluded definitions; it is
// returned only to the desktop, never to the model or a discovery tool.
export function toolInventory(session, nativeDefinitions, blocked) {
  const denied = new Set(blockedToolNames(blocked));
  const definitions = new Map(Object.values(nativeDefinitions).map(definition => [definition.name,
    { ...definition, sourceInfo: {path: "builtin:" + definition.name} }]));
  for (const {definition, sourceInfo} of session.extensionRunner.getAllRegisteredTools())
    definitions.set(definition.name, {...definition, sourceInfo});
  for (const tool of session.getAllTools()) definitions.set(tool.name, tool);
  const active = new Set(session.getActiveToolNames());
  return [...definitions.values()].map(tool => ({name:tool.name, description:tool.description,
    parameters:tool.parameters, exposure:tool.exposure || "direct", active:active.has(tool.name),
    visible:!denied.has(tool.name) && tool.exposure !== "hidden",
    source:tool.sourceInfo?.path || tool.sourceInfo?.kind || "Pi"}));
}
