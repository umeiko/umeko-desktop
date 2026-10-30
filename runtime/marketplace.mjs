// Tools adapted from pi-marketplace 0.1.3 (MIT, ssdiwu).
// Desktop integration omits terminal renderers and optional pi.dev enrichment.
// See marketplace-LICENSE.txt for the complete upstream notice.
import { Type } from 'typebox';
import { createBoundedCache, createRegistryClient } from './marketplace-source.mjs';

export const MARKETPLACE_TOOLS = ['marketplace_search', 'marketplace_detail', 'marketplace_audit', 'marketplace_install'];
export const MARKETPLACE_PROMPT = "Prefer existing dedicated tools to ad hoc scripts. When the tool inventory or tool_search has no suitable dedicated tool for a capability the task needs, treat that as missing even if a shell workaround exists. First inspect installed tools and run_pi_command pi list, then search with marketplace_search, inspect and audit a suitable package, and install its exact version with marketplace_install. Search the market before substituting shell commands or scripts for that missing tool. Prefer a small, clearly described package that directly fits the task. After reload, continue the original task with its tools. If nothing fits, explain what you searched and why nothing fit. Do not write your own extension as a fallback. Installation permission is controlled by the user in the desktop; automatic mode needs no additional user input.";
const packageName = Type.String({ minLength: 1, maxLength: 214 });
const version = Type.String({ pattern: '^\\d+\\.\\d+\\.\\d+(?:-[0-9A-Za-z.-]+)?(?:\\+[0-9A-Za-z.-]+)?$' });
const result = value => ({ content: [{ type: 'text', text: JSON.stringify(value) }], details: value });

export function createMarketplace({ getConfig, runPiCommand, emit = () => {}, registryFactory = createRegistryClient, cacheOptions }) {
  let client, configKey;
  const audits = createBoundedCache(cacheOptions);
  const details = createBoundedCache(cacheOptions);
  function checkCancelled(signal) {
    if (signal?.aborted) throw new Error('Marketplace operation cancelled');
  }
  function registry() {
    const config = getConfig();
    const key = JSON.stringify([config.workspace, config.agent?.npmRegistry, config.agent?.npmCafile, config.agent?.npmUserconfig]);
    if (key !== configKey) {
      configKey = key; audits.clear(); details.clear();
      client = registryFactory({ agent: config.agent || {}, cwd: config.workspace || config.defaultCwd });
    }
    return client;
  }
  async function detail(name, pinned, signal) {
    checkCancelled(signal);
    const api = registry(), key = `${name}@${pinned || 'latest'}`;
    const value = await details.getOrCreate(key, async () => {
      const value = await api.getPackageDetail(name, pinned, { signal });
      checkCancelled(signal);
      if (pinned && value.version !== pinned) throw new Error('Registry did not return the requested exact version');
      return value;
    });
    checkCancelled(signal);
    if (!pinned && client === api) details.set(`${name}@${value.version}`, value);
    return value;
  }
  async function audit(name, deepScan, pinned, signal) {
    const value = await detail(name, pinned, signal);
    const api = registry();
    const key = `${name}@${value.version}:${deepScan}`;
    const notes = await audits.getOrCreate(key, async () => {
      const notes = await api.fullAudit(name, deepScan, value.version, { signal });
      checkCancelled(signal);
      if (notes.version !== value.version) throw new Error('Audit did not return the requested exact version');
      return notes;
    });
    checkCancelled(signal);
    if (notes.scanError) audits.delete(key);
    return notes;
  }
  function tool(pi, definition, execute) {
    pi.registerTool({ ...definition, exposure: 'direct',
      async execute(id, params, signal, onUpdate, ctx) {
        emit({ type: 'marketplace_progress', operation: definition.name, package: params.name || '', state: 'running', message: `${definition.label}: ${params.name || params.query || ''}` });
        try {
          checkCancelled(signal);
          const value = await execute(id, params, signal, ctx);
          emit({ type: 'marketplace_progress', operation: definition.name, package: params.name || '', state: 'done', message: `${definition.label} completed` });
          return result(value);
        } catch (error) {
          emit({ type: 'marketplace_progress', operation: definition.name, package: params.name || '', state: 'error', message: error.message });
          return { ...result({ error: error.message }), isError: true };
        }
      },
    });
  }
  return { extension(pi) {
    tool(pi, { name: 'marketplace_search', label: 'Search Pi Packages',
      description: 'Search installable pi-package packages in the configured npm registry. Reports search or exact-name fallback. If a mirror has no search endpoint, supply an exact package name as query.',
      promptSnippet: 'Find a missing capability in the Pi package market after checking installed tools and pi list.',
      parameters: Type.Object({ query: Type.String(), type: Type.Optional(Type.Union(['extension','skill','prompt','theme'].map(v => Type.Literal(v)))), limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 250 })) }),
    }, (_id, params, signal) => registry().searchPackages(params.query, { limit: params.limit ?? 20, type: params.type, signal }));
    tool(pi, { name: 'marketplace_detail', label: 'Package Detail',
      description: 'Show a Pi package version, description, license, manifest, dependencies, size and links before installing.',
      parameters: Type.Object({ name: packageName, version: Type.Optional(version) }),
    }, (_id, params, signal) => detail(params.name, params.version, signal));
    tool(pi, { name: 'marketplace_audit', label: 'Security Audit',
      description: 'Audit a Pi package using metadata and optional published source keyword scanning. Findings are notes, not a guarantee. Uses the configured registry and CA.',
      parameters: Type.Object({ name: packageName, version: Type.Optional(version), deepScan: Type.Optional(Type.Boolean()) }),
    }, (_id, params, signal) => audit(params.name, params.deepScan ?? true, params.version, signal));
    tool(pi, { name: 'marketplace_install', label: 'Install Pi Package',
      description: 'Install an exact Pi package version for the current task through run_pi_command and its queued reload. Respects the user install permission mode. After runtime results arrive, continue with the newly loaded tool; never repeat a declined install.',
      parameters: Type.Object({ name: packageName, version, reason: Type.String({ minLength: 1, maxLength: 2000 }) }),
    }, async (id, params, signal, ctx) => {
      if (!/^(?:@[a-z0-9_.-]+\/)?[a-z0-9_.-]+$/.test(params.name) || !/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(params.version)) throw new Error('An npm package name and exact version are required');
      const value = await detail(params.name, params.version, signal);
      if (!value.keywords?.includes('pi-package')) throw new Error('The selected package does not have the pi-package keyword');
      const notes = await audit(params.name, true, params.version, signal);
      return runPiCommand(`pi install npm:${params.name}@${params.version}`, { signal, toolCallId: id, ctx, reason: params.reason, audit: notes });
    });
  } };
}
