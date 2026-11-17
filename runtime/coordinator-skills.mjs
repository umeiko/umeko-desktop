// Global coordinators have an explicit, default-empty Skill loadout. Never
// discover a user's normal Pi/project resources or execute imported modules.
import { existsSync, lstatSync, realpathSync, readFileSync, opendirSync, openSync, readSync, closeSync, fstatSync } from 'node:fs';
import { dirname, join, resolve, relative, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Type } from 'typebox';
import { coordinatorNativeTools } from './umeko-control.mjs';

export const validSkillId = id => typeof id === 'string' && /^(builtin|imported):[^/\\\0:]{1,160}$/.test(id)
  && !['.', '..'].includes(id.slice(id.indexOf(':') + 1));
const inside = (path, root) => { const part = relative(root, path); return part && !part.startsWith('..' + '/') && !part.startsWith('..' + '\\') && part !== '..' && !isAbsolute(part); };
function skillFile(root, name) {
  try {
    if (!root) return;
    const base = realpathSync(root), folder = join(base, name), file = join(folder, 'SKILL.md');
    if (lstatSync(folder).isSymbolicLink() || lstatSync(file).isSymbolicLink() || !inside(realpathSync(file), base)) return;
    const info = lstatSync(file);
    if (info.isFile() && info.size <= 64 * 1024) return realpathSync(file);
  } catch {}
}
export function coordinatorSkillPaths(input) {
  if (!input.globalCoordinator || !Array.isArray(input.coordinatorSkills)) return [];
  const roots = input.coordinatorSkillRoots || {}, paths = [];
  for (const id of [...new Set(input.coordinatorSkills)].slice(0, 32)) {
    if (!validSkillId(id)) continue;
    const [source, name] = id.split(':');
    const file = skillFile(roots[source], name);
    if (file) paths.push(file);
  }
  return paths;
}
export function createCoordinatorSkills(input) {
  const paths = coordinatorSkillPaths(input), roots = paths.map(dirname);
  return {
    paths,
    resourceOptions: { noSkills: true, additionalSkillPaths: paths,
      skillsOverride: result => ({ ...result, skills: result.skills.filter(skill => paths.includes(skill.filePath)) }) },
    extension(pi) {
      // An explicitly enabled native reader has Pi's normal file/image support.
      if (coordinatorNativeTools(input.coordinatorTools).includes('read')) return;
      // Override Pi's broad reader even if all selected folders disappeared.
      pi.registerTool({ name: 'read', label: '读取 Skill', exposure: 'direct',
        description: 'Read text files inside this global coordinator\'s explicitly enabled Skill directories. Other files require enabling the native read tool in the agent settings.',
        parameters: Type.Object({path: Type.String({minLength:1,maxLength:4096}), offset: Type.Optional(Type.Integer({minimum:1})), limit: Type.Optional(Type.Integer({minimum:1,maximum:500}))}),
        execute: async (_id, args) => {
          let fd;
          try {
            const target = realpathSync(args.path);
            if (!roots.some(root => inside(target, root))) throw new Error('只能读取为当前子智能体启用的 Skill 文件');
            if (!lstatSync(target).isFile()) throw new Error('请选择 Skill 内的文本文件');
            fd = openSync(target, 'r');
            const info = fstatSync(fd);
            if (!info.isFile() || info.size > 256 * 1024) throw new Error('Skill 文本文件超过 256 KiB 限制');
            const buffer = Buffer.alloc(info.size), count = readSync(fd, buffer, 0, buffer.length, 0);
            if (buffer.subarray(0,count).includes(0)) throw new Error('仅支持读取 Skill 文本文件');
            const lines = buffer.subarray(0,count).toString('utf8').split(/\r?\n/), start = Math.max(0,(args.offset || 1)-1);
            return {content:[{type:'text',text:lines.slice(start,start + Math.min(args.limit || 500,500)).join('\n') || '(empty)'}]};
          } catch(error) { return {content:[{type:'text',text:error.message}],isError:true}; }
          finally { if (fd !== undefined) closeSync(fd); }
        },
      });
    },
  };
}

export function coordinatorSkillCatalog(Pi, input) {
  const roots = input.coordinatorSkillRoots || {}, skills = [];
  let bytes = 0, truncated = false;
  let descriptions = {};
  try { descriptions = JSON.parse(readFileSync(join(roots.builtin,'descriptions.json'),'utf8')); } catch {}
  for (const source of ['builtin','imported']) {
    const root = roots[source]; if (!root || !existsSync(root)) continue;
    const directory = opendirSync(root);
    try { let count=0;
    for (let entry; (entry=directory.readSync());) {
      if (++count > 2000 || skills.length >= 512) {truncated=true;break;}
      if (!entry.isDirectory() || entry.isSymbolicLink() || entry.name.startsWith('.')) continue;
      const id = source + ':' + entry.name;
      if (!validSkillId(id)) continue;
      const file = skillFile(root,entry.name); if (!file) continue;
      const loaded = Pi.loadSkills({cwd:input.cwd, agentDir:input.agentDir, skillPaths:[file], includeDefaults:false});
      const skill = loaded.skills.find(row => row.filePath === file);
      const row={id,name:skill?.name || entry.name,description:skill?.description || '',
        descriptions:source === 'builtin' ? descriptions[entry.name] || {} : {}, source, path:file, valid:!!skill};
      const size=Buffer.byteLength(JSON.stringify(row));
      if(bytes+size>150*1024){truncated=true;break;}bytes+=size;skills.push(row);
    }
    } finally {directory.closeSync();}
  }
  return {ok:true,truncated,skills:skills.sort((a,b)=>a.source.localeCompare(b.source) || a.name.localeCompare(b.name))};
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    process.env.PI_OFFLINE = '1';
    let raw = ''; for await (const chunk of process.stdin) raw += chunk;
    const input = JSON.parse(raw);
    const Pi = await import('@earendil-works/pi-coding-agent');
    const value = input.action === 'validateText'
      ? await (await import('./skills.mjs')).validateSkillDocuments(input.documents)
      : coordinatorSkillCatalog(Pi,input);
    process.stdout.write(JSON.stringify(value)+'\n');
  } catch(error) { process.stdout.write(JSON.stringify({ok:false,error:error.message})+'\n'); process.exitCode=1; }
}
