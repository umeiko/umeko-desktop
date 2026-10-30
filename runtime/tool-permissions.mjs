/**
 * Pre-execution permission gate for the desktop's seven-category policy.
 * Adapted from @xynogen/pix-gate 0.4.5 src/lib.ts (MIT, xynogen 2026):
 * AT_CMD, SEG, stripQuoted, WINDOWS_ROOT_WIPE, critical command families and
 * write-only normalized path rules. Full notice: ../licenses/pix-gate-MIT.txt.
 * Pi Coding Agent 1.3.0 permission-gate/protected-paths examples supply the
 * tool_call shape: https://github.com/earendil-works/pi/tree/main/packages/coding-agent/examples/extensions
 * cc-safety-net 2.7.0 supplied categories/test checklist only, no copied code:
 * https://github.com/kenryu42/cc-safety-net/tree/v2.7.0
 * This is a direct-command/literal-wrapper detector, not an OS sandbox.
 */
/*
MIT License

Copyright (c) 2026 xynogen

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
*/
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

// Upstream command-position guard, retained as the common rule entry guard.
const AT_CMD = String.raw`(?:^|(?<!\\)[;&|({\x60!]|\$\(|-c\s+["'])\s*(?:(?:sudo|doas|env|nohup|time|exec|nice|xargs|command|builtin|then|do|else)\s+(?:-\S+\s+)*)*`;
const SEG = String.raw`[^;&|\n]*`;
const WINDOWS_ROOT_WIPE = /\b(?:rd|rmdir|del|erase|Remove-Item|ri|rm)\b(?=[^|;\n]*\s(?:\/s|-r\w*)\b)[^|;\n]*\s["']?(?:[A-Za-z]:|~|\$env:USERPROFILE|%USERPROFILE%|\$HOME)[\\/]?["']?(?=\s|$|[;|&])/i;
const atCommand = new RegExp(AT_CMD + String.raw`\S`,'i');
// Adaptation: preserve offsets so quote-masked text can guide token boundaries.
function stripQuoted(command) {
  return command.replace(/'[^']*'|"(?:[^"\\]|\\.)*"/g, m => ' '.repeat(m.length));
}

const REASONS = {
 '1a':['Recursive deletion targets a root, system, home or Umeko data path.','递归删除的目标是磁盘根目录、系统目录、用户主目录或 Umeko 数据。'],
 '1b':['Recursive deletion targets a root, system, home or Umeko data path.','递归删除的目标是磁盘根目录、系统目录、用户主目录或 Umeko 数据。'],
 '2a':['This command formats, erases or changes a disk or partition.','此命令会格式化、擦除或修改磁盘或分区。'],
 '2b':['This command writes directly to a raw disk device.','此命令会直接写入原始磁盘设备。'],
 '3':['This command shuts down, restarts or logs off the computer.','此命令会关机、重启或注销计算机。'],
 '4a':['This command changes the machine-wide HKLM registry.','此命令会修改系统级 HKLM 注册表。'],
 '4b':['This command accesses boot configuration through bcdedit.','此命令通过 bcdedit 操作启动配置。'],
 '4c':['This command disables security protection or firewall controls.','此命令会关闭安全防护或防火墙控制。'],
 '4d':['This command changes machine-wide environment variables.','此命令会修改系统级环境变量。'],
 '5a':['This command recursively changes permissions or ownership on a protected path.','此命令会递归修改受保护目录的权限或所有者。'],
 '5b':['This command changes permissions or ownership on a protected system or root path.','此命令会修改系统目录或根目录的权限或所有者。'],
 '6':['This command force-pushes to main or master.','此命令会向 main 或 master 分支强制推送。'],
 '7':['This file operation writes inside a system directory.','此文件操作会写入系统目录。'],
 ask:['Ask mode requires approval for this modifying tool call.','询问模式要求先批准此次修改操作。'],
};
const decision = id => ({category:Number(id[0]) || 0, ruleId:id, reason:REASONS[id][0]});

function environment(context) {
 const env = {...process.env,...context.env};
 const get = name => Object.entries(env).find(([key])=>key.toLowerCase()===name.toLowerCase())?.[1];
 return {env,get};
}
function normalizePath(value, context={}) {
 if (typeof value !== 'string' || !value) return '';
 const {get}=environment(context);
 const home=context.home || context.userProfile || get('USERPROFILE') || get('HOME') || os.homedir();
 let p=value.replace(/^['"]|['"]$/g,'');
 p=p.replace(/^~(?=$|[\\/])/,home);
 const known = name => {
   if (/^(HOME|USERPROFILE)$/i.test(name)) return /USERPROFILE/i.test(name) ? context.userProfile || home : home;
   if (/^(UMEKO_DATA_DIR|UMEKO_USER_DATA_DIR|UMEKO_DATA|UMEKO_DATA_ROOT)$/i.test(name)) return Array.isArray(context.dataDir)?context.dataDir[0]:context.dataDir;
   return get(name);
 };
 p=p.replace(/\$env:([\w()]+)|%([^%]+)%|\$\{([^}]+)\}|\$(\w+)/gi,(all,...args)=> known(args.slice(0,4).find(Boolean)) ?? all);
 p=p.replace(/\\/g,'/').replace(/^\/([a-z])(?=\/|$)/i,'$1:');
 const cwd=String(context.cwd||process.cwd()).replace(/\\/g,'/').replace(/^\/([a-z])(?=\/|$)/i,'$1:');
 if (/^[a-z]:/i.test(p)) p=path.posix.normalize(p.replace(/^([a-z]):\/?/i,'$1:/'));
 else if (p.startsWith('/')) p=path.posix.normalize(p);
 else p=path.posix.normalize(cwd+'/'+p);
 return p.replace(/\/+$/,'') || '/';
}
function pathSets(context) {
 const {get}=environment(context);
 const home=normalizePath(context.home||context.userProfile||get('USERPROFILE')||get('HOME')||os.homedir(),context);
 const win=get('SystemRoot')||get('windir')||'C:/Windows';
 const systems=[win,get('ProgramFiles')||'C:/Program Files',get('ProgramFiles(x86)')||'C:/Program Files (x86)',get('ProgramData')||'C:/ProgramData',
 '/bin','/boot','/dev','/etc','/lib','/lib64','/proc','/sbin','/sys','/usr','/System','/Library'].map(p=>normalizePath(p,context));
 const data=[context.dataDir,context.dataDirs,context.userDataDir,home+'/.umeko'].flat(2).filter(p=>typeof p==='string'&&p).map(p=>normalizePath(p,context));
 return {home,systems,data};
}
function inside(p,root) {
 if (/^[a-z]:/i.test(root)) {p=p.toLowerCase();root=root.toLowerCase();}
 return p===root || p.startsWith(root+'/');
}
function protectedPath(value,context,{systemOnly=false,noData=false}={}) {
 const p=normalizePath(value,context).replace(/\/\*$/,'') || (value==='/*'?'/':'');
 if (!p) return false;
 const {home,systems,data}=pathSets(context);
 if(systems.some(root=>inside(p,root))) return true;
 if(systemOnly) return false;
 const exactHome=/^[a-z]:/i.test(home)?p.toLowerCase()===home.toLowerCase():p===home;
 return p==='/' || /^[a-z]:$/i.test(p) || exactHome || ['/home','/root'].includes(p) || (!noData&&data.some(root=>inside(p,root)));
}
/** Only native structured write/edit calls use category 7. */
export function classifyPath(filePath,context={}) {
 return protectedPath(filePath,context,{systemOnly:true}) ? decision('7') : null;
}

// Tokenize operators outside quotes and preserve decoded operand values. Quote
// masking is used only for boundaries; actual target tokens are never masked.
function lex(command) {
 const tokens=[],nested=[],masked=stripQuoted(command);
 let value='',started=false,quote='',quoted=false;
 const push=()=>{if(started){tokens.push({value,quoted});value='';started=false;quoted=false;}};
 const substitution=(start,close)=>{
   let end=start,depth=1,q='';
   for(;end<command.length;end++){
     const c=command[end];
     if(c==='\\'&&q!=="'"){end++;continue;}
     if(q){if(c===q)q='';continue;}
     if(c==='"'||c==="'"){q=c;continue;}
     if(close===')'&&c==='(')depth++;
     if(c===close&&!--depth)break;
   }
   nested.push(command.slice(start,end));
   return end;
 };
 for(let i=0;i<command.length;i++){
   const c=command[i];
   if(quote){
     if(c===quote){quote='';continue;}
     if(quote==='"'&&c==='$'&&command[i+1]==='('){i=substitution(i+2,')');value+='$(...)';continue;}
     if(quote==='"'&&c==='`'&&command.indexOf('`',i+1)>=0){i=substitution(i+1,'`');value+='`...`';continue;}
     if(c==='\\'&&quote==='"'&&/["$`]/.test(command[i+1]||'')&&command.slice(i+2).includes('"')){value+=command[++i];continue;}
     value+=c;continue;
   }
   if(c==='"'||c==="'"){started=true;quoted=true;quote=c;continue;}
   if(c==='$'&&command[i+1]==='('){started=true;i=substitution(i+2,')');value+='$(...)';continue;}
   if(c==='`'&&command.indexOf('`',i+1)>=0){started=true;i=substitution(i+1,'`');value+='`...`';continue;}
   if(c==='\\'&&!/^(?:[a-z]:|\\\\)/i.test(value)&&/[\s;&|<>"'(){}]/.test(command[i+1]||'')){started=true;value+=command[++i];continue;}
   if(/\s/.test(c)){push();if(c==='\n')tokens.push({op:';'});continue;}
   if(c==='#'&&!started&&masked[i]==='#'){while(i<command.length&&command[i]!=='\n')i++;push();tokens.push({op:';'});continue;}
   // PowerShell's static method invocation is a command in its own right.
   if(c==='('&&value.includes('::')){
     let end=i+1,q='',depth=1;
     for(;end<command.length;end++){
       const x=command[end];if(q){if(x===q)q='';continue;}if(x==='"'||x==="'"){q=x;continue;}
       if(x==='(')depth++;if(x===')'&&!--depth)break;
     }
     value+=command.slice(i,end+1);i=end;continue;
   }
   if(/[;&|()<>{}]/.test(c)){
     push();let op=c;if(command[i+1]===c&&/[;&|<>]/.test(c))op+=command[++i];tokens.push({op});continue;
   }
   started=true;value+=c;
 }
 push();return {tokens,nested};
}
function executable(value) {return value.replace(/\\/g,'/').split('/').at(-1).replace(/\.(exe|com)$/i,'').toLowerCase();}
const wrappers=new Set(['sudo','doas','env','nohup','time','exec','nice','xargs','command','builtin','then','do','else']);
function invocation(tokens) {
 let i=0;
 while(i<tokens.length){
   const name=executable(tokens[i].value||'');
   if(/^[\w]+=.*/.test(tokens[i].value||'') || ['!','&'].includes(tokens[i].value)){i++;continue;}
   if(!wrappers.has(name))break;
   i++;
   while(i<tokens.length && (/^-/.test(tokens[i].value)||/^\w+=/.test(tokens[i].value))){
     const flag=tokens[i++].value;
     if(/^(?:-u|-g|-n|--user|--group|--adjustment|-P|-I|-L)$/.test(flag))i++;
   }
 }
 if(i>=tokens.length)return null;
 const name=executable(tokens[i].value);
 // Every command predicate enters through the shared command-position guard.
 if(!atCommand.test(name))return null;
 return {name,args:tokens.slice(i+1).filter(t=>!t.op).map(t=>t.value),tokens:tokens.slice(i),raw:tokens.slice(i).map(t=>t.value||t.op).join(' ')};
}
const rawDisk=value=>/^(?:\/dev\/(?:sd[a-z]\d*|hd[a-z]\d*|vd[a-z]\d*|xvd[a-z]\d*|nvme\d+n\d+(?:p\d+)?|mmcblk\d+(?:p\d+)?|disk\d+(?:s\d+)?)|\/\/\.\/(?:PhysicalDrive\d+|[a-z]:|Harddisk\d+(?:\/Partition\d+)?))$/i.test(value.replace(/\\/g,'/'));
const hklm=value=>/^(?:HKLM(?=:|\\|\/|$)|HKEY_LOCAL_MACHINE(?=:|\\|\/|$)|(?:Registry::)?HKEY_LOCAL_MACHINE(?=\\|\/|$))/i.test(value);
const trueValue=value=>/^(?:\$?true|1|on|yes)$/i.test(value||'');
const securityService=value=>/^(?:WinDefend|WdNisSvc|Sense|SecurityHealthService|mpssvc|BFE|wscsvc|firewalld|ufw|MicrosoftDefender)$/i.test(value);
const flagValue=(args,pattern)=>{const i=args.findIndex(a=>pattern.test(a));return i<0?undefined:args[i+1];};
const param=(a,name)=>new RegExp('^-'+name+'(?::|$)','i').test(a);
function targetArgs(args) {
 const skipValue=/^-(?:filter|include|exclude|credential|erroraction|warningaction|informationaction|errorvariable|warningvariable|outvariable|outbuffer|pipelinevariable)$/i;
 const out=[];
 for(let i=0;i<args.length;i++){
   const a=args[i];if(skipValue.test(a)){i++;continue;}
   if(/^-(?:literalpath|path)(?::|$)/i.test(a)){const x=a.includes(':')?a.slice(a.indexOf(':')+1):args[++i];if(x)out.push(x);continue;}
   if(a==='--'){out.push(...args.slice(i+1));break;}
   if(a.startsWith('-')||/^\/[sqft]$/i.test(a))continue;
   out.push(...a.split(',').filter(Boolean));
 }
 return out;
}

// Only a forced push without a destination reads these small metadata files.
// No git child process is started and ordinary command classification does no IO.
function barePushDestination(args,context) {
 if(context.currentBranch||context.gitBranch)return context.currentBranch||context.gitBranch;
 try {
   let dir=path.resolve(context.cwd||process.cwd()),gitDir;
   while(true){
     const entry=path.join(dir,'.git');
     if(fs.existsSync(entry)){
       const info=fs.statSync(entry);gitDir=info.isDirectory()?entry:path.resolve(dir,fs.readFileSync(entry,'utf8').trim().replace(/^gitdir:\s*/,''));break;
     }
     const parent=path.dirname(dir);if(parent===dir)return null;dir=parent;
   }
   const head=fs.readFileSync(path.join(gitDir,'HEAD'),'utf8').trim();
   const branch=head.match(/^ref: refs\/heads\/(.+)$/)?.[1];if(!branch)return null;
   let config='',configDir=gitDir;
   const common=path.join(gitDir,'commondir');if(fs.existsSync(common))configDir=path.resolve(gitDir,fs.readFileSync(common,'utf8').trim());
   if(fs.existsSync(path.join(configDir,'config')))config=fs.readFileSync(path.join(configDir,'config'),'utf8');
   const sections=new Map();let current='';
   for(const line of config.split(/\r?\n/)){
     const header=line.match(/^\s*\[([^\]]+)\]/);if(header){current=header[1];continue;}
     const item=line.match(/^\s*([\w.-]+)\s*=\s*(.*?)\s*$/);if(item){const list=sections.get(current)||[];list.push([item[1].toLowerCase(),item[2]]);sections.set(current,list);}
   }
   const branchOptions=sections.get(`branch "${branch}"`)||[];
   const get=(list,key)=>list.find(([k])=>k===key)?.[1];
   const pushOptions=sections.get('push')||[];
   const nonFlags=args.filter(a=>!a.startsWith('-'));
   const remote=nonFlags[0]||get(branchOptions,'pushremote')||get(sections.get('remote')||[],'pushdefault')||get(branchOptions,'remote')||'origin';
   const configured=(sections.get(`remote "${remote}"`)||[]).filter(([k])=>k==='push').map(([,v])=>v);
   if(configured.length)return configured;
   const mode=get(pushOptions,'default');
   if(mode==='nothing')return null;
   if(mode==='upstream')return get(branchOptions,'merge')||branch;
   if(mode==='matching')return ['main','master'];
   return branch;
 } catch {return null;}
}
function protectedBranch(ref) {
 if(typeof ref!=='string')return false;
 const dest=ref.replace(/^\+/,'').split(':').at(-1).replace(/^refs\/heads\//,'');
 return dest==='main'||dest==='master';
}
function forcePush(args,context) {
 let push=0;
 while(push<args.length&&args[push].startsWith('-')){
   const option=args[push++];
   if(['-c','-C','--git-dir','--work-tree','--namespace','--config-env','--exec-path'].includes(option))push++;
 }
 if(args[push]!=='push')return false;
 const tail=args.slice(push+1);
 const force=tail.some(a=>/^(?:-[A-Za-z]*f[A-Za-z]*|--force|--force-with-lease(?:=.*)?)$/.test(a)||a.startsWith('+'));
 if(!force)return false;
 if(tail.some(a=>a==='--all'||a==='--mirror'))return true;
 if(tail.some(a=>/^--force-with-lease=/.test(a)&&protectedBranch(a.slice(a.indexOf('=')+1).split(':')[0])))return true;
 const values=[];
 for(let i=0;i<tail.length;i++){
   if(['--repo','--receive-pack','--exec','--push-option','-o'].includes(tail[i])){i++;continue;}
   if(!tail[i].startsWith('-'))values.push(tail[i]);
 }
 if(values.slice(1).some(protectedBranch))return true;
 // +refspec without an explicit remote is still an explicit destination.
 if(values.some(a=>a.startsWith('+')&&protectedBranch(a)))return true;
 if(values.length>1)return false;
 return [barePushDestination(tail,context)].flat().some(protectedBranch);
}

function classifyInvocation(call,context,depth) {
 const {name:n,args:a,raw}=call,lower=a.map(v=>v.toLowerCase());
 // Supported literal shell wrappers recurse only on their command argument.
 if(['bash','sh','zsh','dash','ksh','cmd','powershell','pwsh'].includes(n)){
   const i=a.findIndex(v=> n==='cmd'?/^\/c$/i.test(v):['powershell','pwsh'].includes(n)?/^-(?:c|command)$/i.test(v):/^-[a-z]*c[a-z]*$/.test(v));
   if(i>=0&&a[i+1]){const result=classifyInternal(a.slice(i+1).join(' '),context,depth+1);if(result)return result;}
 }
 const targets=targetArgs(a);
 const unixRecursive=a.some(v=>/^-[a-z]*r[a-z]*$/i.test(v)||v==='--recursive');
 const psRecursive=a.some(v=>/^-(?:r|re|rec|recu|recur|recurs|recurse)(?::\$?true)?$/i.test(v));
 const windowsRecursive=a.some(v=>/^\/s$/i.test(v));
 // WINDOWS_ROOT_WIPE is reused as an early family cue; parsed target semantics
 // extend it to quoted and normalized paths without its upstream substring scan.
 const windowsDelete=WINDOWS_ROOT_WIPE.test(raw)||(['rd','rmdir','del','erase','remove-item','ri','rm'].includes(n)&&(psRecursive||windowsRecursive));
 if(n==='rm'&&unixRecursive&&targets.some(p=>protectedPath(p,context)))return decision('1a');
 if(windowsDelete&&['rd','rmdir','del','erase','remove-item','ri','rm'].includes(n)&&targets.some(p=>protectedPath(p,context)))return decision('1b');
 const help=a.some(v=>/^(?:--help|--version|-h|\/\?|\/?help)$/i.test(v));
 if(n==='diskpart')return decision('2a');
 if(!help){
   if(['format-volume','clear-disk','initialize-disk','format-disk','format'].includes(n)&&a.length)return decision('2a');
   if(/^(?:mkfs(?:\.[\w-]+)?|mke2fs|newfs|wipefs|blkdiscard)$/.test(n)&&a.some(v=>rawDisk(v)||/^\/dev\//.test(v)))return decision('2a');
   if(n==='parted'&&a.some(v=>/^(?:mklabel|mktable|mkpart|rm|resizepart|rescue|set|name|align-check)$/i.test(v))&&!lower.includes('align-check'))return decision('2a');
   if(n==='sgdisk'&&a.some(v=>/^(?:--(?:zap(?:-all)?|clear|delete|new|typecode|change-name|replicate|load-backup|move-second-header|randomize-guids)(?:=|$)|-[oZzdntceG])/i.test(v)))return decision('2a');
   if(n==='fdisk'&&a.length&&!a.some(v=>/^(?:-l|--list|-s|--getsz)$/i.test(v)))return decision('2a');
   if(n==='diskutil'&&a.some(v=>/^(?:erase|partition)/i.test(v)))return decision('2a');
 }
 if(n==='dd'){
   for(let i=0;i<a.length;i++){
     const v=a[i];const out=v.match(/^of=(.*)$/i)?.[1]||(v.toLowerCase()==='of'?(a[i+1]==='='?a[i+2]:a[i+1]?.replace(/^=/,'')):undefined);
     if(out&&rawDisk(out))return decision('2b');
   }
 }
 if(n==='tee'&&targets.some(rawDisk))return decision('2b');
 if(['shutdown','reboot','halt','poweroff','logoff','stop-computer','restart-computer'].includes(n))return decision('3');
 if(n==='systemctl'&&['poweroff','reboot','halt','kexec'].includes(lower.find(v=>!v.startsWith('-'))))return decision('3');
 if(n==='init'&&a.some(v=>v==='0'||v==='6'))return decision('3');
 if(n==='rundll32'&&a.some(v=>/^user32(?:\.dll)?,exitwindowsex$/i.test(v)))return decision('3');
 if(n==='reg'&&['add','delete','import','restore','load','unload','copy'].includes(lower[0])){
   const dest=lower[0]==='copy'?a[2]:a[1];if(dest&&hklm(dest))return decision('4a');
 }
 if(/^(?:set|new|remove|clear)-(?:item|itemproperty)$|^(?:rename|copy|move)-item$/.test(n)&&targets.some(hklm))return decision('4a');
 if(n==='bcdedit')return decision('4b');
 if(n==='set-mppreference'&&a.some((v,i)=>/^-disable/i.test(v)&&trueValue(v.includes(':')?v.slice(v.indexOf(':')+1):a[i+1])))return decision('4c');
 if(n==='add-mppreference'&&a.some(v=>/^-exclusion/i.test(v)))return decision('4c');
 if(n==='netsh'&&((lower[0]==='advfirewall'&&/\bstate\s+off\b/i.test(a.join(' ')))||(lower[0]==='firewall'&&/\bopmode\s+(?:mode\s*=\s*)?disable\b/i.test(a.join(' ')))))return decision('4c');
 if(n==='set-netfirewallprofile'&&a.some((v,i)=>/^-enabled(?::|$)/i.test(v)&&/^(?:\$?false|0)$/i.test(v.includes(':')?v.slice(v.indexOf(':')+1):a[i+1]||'')))return decision('4c');
 if(n==='sc'&&((lower[0]==='stop')||(lower[0]==='config'&&/start\s*=\s*disabled/i.test(a.join(' '))))&&a.some(securityService))return decision('4c');
 if(n==='net'&&lower[0]==='stop'&&a.some(securityService))return decision('4c');
 if(n==='stop-service'&&targets.some(securityService))return decision('4c');
 if(n==='set-service'&&lower.some(v=>v==='disabled')&&a.some(securityService))return decision('4c');
 if(n==='ufw'&&lower[0]==='disable')return decision('4c');
 if(n==='systemctl'&&lower.some(v=>v==='stop'||v==='disable')&&a.some(v=>securityService(v.replace(/\.service$/i,''))))return decision('4c');
 if(n==='setx'&&lower.includes('/m'))return decision('4d');
 if(/^\[(?:system\.)?environment\]::setenvironmentvariable\(/i.test(n)&&/(?:['"]Machine['"]|EnvironmentVariableTarget\]::Machine)\s*\)$/i.test(raw))return decision('4d');
 if(['chmod','chown','chgrp'].includes(n)&&a.some(v=>/^-[a-z]*R[a-z]*$/.test(v)||v==='--recursive')&&targets.some(p=>protectedPath(p,context,{noData:true})))return decision('5a');
 if(n==='takeown'&&lower.includes('/r')){const target=flagValue(a,/^\/f$/i);if(target&&protectedPath(target,context,{noData:true}))return decision('5b');}
 if(['icacls','cacls'].includes(n)&&a.some(v=>/^\/(?:grant(?::r)?|deny|remove(?::[gd])?|reset|setowner|inheritance(?::[edr])?|g|p|r|e)(?::|$)/i.test(v))&&a[0]){
   const aclTarget=normalizePath(a[0],context).replace(/\/\*$/,'');
   if(aclTarget==='/'||/^[a-z]:$/i.test(aclTarget)||protectedPath(a[0],context,{systemOnly:true}))return decision('5b');
 }
 if(n==='git'&&forcePush(a,context))return decision('6');
 return null;
}
function classifyInternal(command,context,depth) {
 if(depth>12)return null;
 const {tokens,nested}=lex(command);
 for(const inner of nested){const hit=classifyInternal(inner,context,depth+1);if(hit)return hit;}
 let segment=[];
 const check=()=>{const call=invocation(segment);segment=[];return call?classifyInvocation(call,context,depth):null;};
 for(let i=0;i<tokens.length;i++){
   const token=tokens[i];
   if(token.op&&/^>{1,2}$/.test(token.op)){
     // A redirect is active shell syntax, including after ordinary emitters.
     if(tokens[i+1]?.value&&rawDisk(tokens[i+1].value)&&invocation(segment))return decision('2b');
     i++;continue;
   }
   if(token.op){const result=check();if(result)return result;continue;}
   segment.push(token);
 }
 return check();
}
export function classifyCommand(command,context={}) {
 if(typeof command!=='string'||!command.trim())return null;
 return classifyInternal(command,context,0);
}

/** Per-session factory; getPolicy is the sole source of the active mode. */
export function createToolPermissionExtension({getPolicy,classify=classifyCommand}={}) {
 if(typeof getPolicy!=='function')throw new TypeError('getPolicy is required');
 return pi=>{
   pi.on('tool_call',async(event,ctx)=>{
     let language='en';
     const notify=message=>{try{ctx.ui?.notify?.(message,'error');}catch{/* model-visible block below remains authoritative */}};
     try{
       const policy=await getPolicy();language=policy.language==='zh'?'zh':'en';
       const name=String(event.toolName||'').toLowerCase();
       if(['read','grep','find','ls'].includes(name))return undefined;
       // Product configuration tools retain their own operation dispatch.
       if(name==='umeko_desktop'||name==='pi'||name==='pi_commands')return undefined;
       const input=event.input||{};
       const backgroundStart=name==='background_job'&&input.action==='start';
       const baseCwd=ctx.cwd||policy.cwd||process.cwd();
       const context={...policy,cwd:backgroundStart&&input.cwd ? path.resolve(baseCwd,input.cwd) : baseCwd};
       const shell=name==='bash'||name==='powershell'||backgroundStart;
       const file=name==='write'||name==='edit';
       let hit=null;
       if(shell)hit=await classify(String(input.command??input.script??''),context);
       else if(file)hit=classifyPath(String(input.path??input.file_path??''),context);
       if(policy.mode==='ask'){
         if(shell||file)hit=hit||decision('ask');
         else{
           const tools=typeof pi.getAllTools==='function'?pi.getAllTools():[];
           const tool=tools.find(t=>t.name===event.toolName);
           const hints=tool?.annotations||event.annotations||{};
           if(hints.readOnlyHint!==true&&(hints.destructiveHint===true||hints.readOnlyHint===false))hit=decision('ask');
         }
       }
       if(!hit)return undefined;
       const reason=REASONS[hit.ruleId]?.[language==='zh'?1:0]||hit.reason;
       const original=shell?String(input.command??input.script??''):file?String(input.path??input.file_path??''):JSON.stringify(input);
       if(!ctx.hasUI||!ctx.ui?.confirm){
         const message=language==='zh'?`未执行：无法显示审批对话框。${reason}`:`Not executed: approval UI is unavailable. ${reason}`;
         notify(message);return {block:true,reason:message};
       }
       const title=language==='zh'?'批准工具操作':'Approve tool operation';
       const message=language==='zh'?`原因：${reason}\n\n原始${shell?'命令':'路径/输入'}：\n${original}`:`Reason: ${reason}\n\nOriginal ${shell?'command':'path/input'}:\n${original}`;
       const approved=await ctx.ui.confirm(title,message);
       if(approved!==true)return {block:true,reason:language==='zh'?`用户拒绝执行。${reason}`:`User denied execution. ${reason}`};
       return undefined;
     }catch(error){
       const detail=error instanceof Error?error.message:String(error);
       const reason=language==='zh'?`权限检查失败，工具未执行：${detail}`:`Permission check failed; tool was not executed: ${detail}`;
       notify(reason);return {block:true,reason};
     }
   });
 };
}
