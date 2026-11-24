import { createCoordinatorSkills } from "./coordinator-skills.mjs";
import { coworkTools } from "./cowork-tools.mjs";

const slot = Symbol.for("umeko:cowork-subagents");
const marker = /\[umeko-cowork-subagent:([a-z0-9-]+)\]/;

export function configureCoworkSubagents(profiles, factories, network) {
  globalThis[slot] = profiles ? { profiles: new Map(profiles.map(row => [row.id, row])), factories, network } : undefined;
}

export function coworkSubagent(id) {
  return globalThis[slot]?.profiles.get(id);
}

export function coworkSubagentFromPrompt(prompt) {
  if (!globalThis[slot]) return;
  const value = typeof prompt === "function" ? prompt("") : prompt;
  return coworkSubagent(String(value || "").match(marker)?.[1]);
}

export function coworkSubagentTools(profile) {
  return [...new Set([...profile.tools, ...(profile.skillPaths.length ? ["read"] : [])])];
}

const coworkSubagentPrompt = profile => `[umeko-cowork-subagent:${profile.id}]\n${profile.prompt}`;

// The native package registers built-in types before loading custom agents.
export function loadCustomAgents() {
  const rows = new Map(["general-purpose", "Explore", "Plan"].map(name =>
    [name, { name, description: name, toolNames: [], systemPrompt: "", promptMode: "replace", enabled: false }]));
  for (const profile of globalThis[slot]?.profiles.values() || []) {
    rows.set(profile.id, {
      name: profile.id,
      displayName: profile.name,
      description: profile.description || profile.name,
      toolNames: coworkSubagentTools(profile),
      systemPrompt: coworkSubagentPrompt(profile),
      promptMode: "replace",
      model: profile.model ? `umeko/${profile.model}` : undefined,
      inheritContext: profile.context === "chat",
      locked: ["inherit_context", "model"],
      enabled: true,
      source: "project",
    });
  }
  return rows;
}

export function coworkSubagentResources(profile) {
  const skills = createCoordinatorSkills({ cowork: { skillPaths: profile.skillPaths }, coordinatorTools: profile.tools });
  // Pi supplies these communication tools when their callbacks are available.
  const allowedTools = [...coworkSubagentTools(profile), "ask_parent", "notify_parent"];
  return {
    noExtensions: true,
    noContextFiles: true,
    noPromptTemplates: true,
    noThemes: true,
    systemPromptOverride: () => coworkSubagentPrompt(profile),
    ...skills.resourceOptions,
    extensionFactories: [
      { name: "cowork-child-tools", hidden: true, replaceable: false, factory: pi => coworkTools(pi, allowedTools, globalThis[slot]?.network) },
      { name: "cowork-child-skills", hidden: true, replaceable: false, factory: pi => skills.extension(pi) },
      ...(globalThis[slot]?.factories?.(profile) || []),
    ],
  };
}
