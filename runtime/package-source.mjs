// Source identities come from Pi's registry, shared with the desktop resource list.
import { readFileSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';

export function packageManifest(root) {
  try { return JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')); }
  catch { return {}; }
}

export function packageSource(session, toolName) {
  const tool = session.getAllTools().find(tool => tool.name === toolName);
  const info = tool?.sourceInfo;
  if (!info?.path || info.path.startsWith('builtin:') || info.path.startsWith('<')) return null;
  const metadata = session.resourceLoader.resourceMetadataByPath?.get(info.path) || info;
  const root = metadata.packageRoot || metadata.baseDir || dirname(info.path);
  const manifest = packageManifest(root);
  return { package: manifest.name || basename(root), version: manifest.version || '',
    source: metadata.origin === 'package' ? metadata.source : info.path,
    path: info.path, packageRoot: root };
}

export function installedPackage(manager, source, local) {
  const root = manager.getInstalledPath(source, local ? 'project' : 'user');
  const manifest = root ? packageManifest(root) : {};
  return { package: manifest.name || source.replace(/^npm:/, '').replace(/@[^/@]+$/, ''),
    version: manifest.version || '', source, packageRoot: root || '' };
}
