// Read-only conversation search. Like VS Code: rg --json, streamed matches,
// cancellation and a result limit. The cache is a text projection, not an index.
import {createReadStream} from 'node:fs';
import * as fs from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {join, resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {setImmediate as yieldTurn} from 'node:timers/promises';

const VERSION = 1;
const memory = new Map();
let memoryBytes=0;
function remember(key,value,weight) {
  if(memory.has(key))memoryBytes-=memory.get(key).weight;
  memory.delete(key);memory.set(key,{value,weight});memoryBytes+=weight;
  while(memoryBytes>32*1024*1024 && memory.size){const oldest=memory.keys().next().value;memoryBytes-=memory.get(oldest).weight;memory.delete(oldest);}
}
const hash = value => createHash('sha256').update(value).digest('hex').slice(0,32);
const check = signal => { if (signal?.aborted) throw new DOMException('Cancelled','AbortError'); };
const textOf = content => typeof content === 'string' ? content : (Array.isArray(content) ? content : []).filter(b => b.type === 'text').map(b => b.text || '').join('\n');
const stamp = value => typeof value === 'number' ? value : Date.parse(value) || 0;

function bodyOf(message) {
  let text = textOf(message.content);
  if (message.role === 'user') {
    // Encoded attachment metadata is not visible chat text. Keep the same body
    // prefix as the desktop renderer, without searching hidden local paths.
    const attachment = text.search(/<!-- umeko-attachments:[A-Za-z0-9+/=]+ -->/);
    if (attachment >= 0) {
      const note = text.lastIndexOf('\n\n附件（用户提供的路径');
      text = text.slice(0,note >= 0 ? note : attachment).trimEnd();
    }
  }
  return text;
}

async function signature(file, end) {
  const handle = await fs.open(file,'r');
  try {
    const bytes = Buffer.alloc(Math.min(4096,end));
    await handle.read(bytes,0,bytes.length,Math.max(0,end-bytes.length));
    return createHash('sha256').update(bytes).digest('hex');
  } finally { await handle.close(); }
}

async function scan(file, start, graph, signal) {
  const bodies = new Map();
  let offset = start, latest = '', count = 0;
  // Split bytes before decoding: offsets remain valid for Chinese and emoji.
  const stream = createReadStream(file,{start,highWaterMark:256*1024});
  const abort = () => stream.destroy();
  signal?.addEventListener('abort',abort,{once:true});
  let pending = Buffer.alloc(0);
  try {
    for await (const chunk of stream) {
      check(signal);
      const bytes = pending.length ? Buffer.concat([pending,chunk]) : chunk;
      let at = 0, newline;
      while ((newline = bytes.indexOf(10,at)) >= 0) {
        const length = newline+1-at;
        let entry;
        try { entry = JSON.parse(bytes.subarray(at,newline).toString('utf8')); } catch { /* malformed completed line */ }
        if (entry?.id) {
          const node = {id:entry.id,parent:entry.parentId || '',offset,length,
            role:entry.type === 'message' ? entry.message?.role : '',
            timestamp:stamp(entry.message?.timestamp || entry.timestamp),
            omitted:entry.type === 'context_edit' && entry.replacement == null ? entry.targetId : ''};
          if (['user','assistant'].includes(node.role)) {
            const body=bodyOf(entry.message);node.searchable=body.length>0;bodies.set(node.id,body);
          }
          graph.set(node.id,node); latest = node.id;
        }
        offset += length; at = newline+1;
        if (++count % 256 === 0) { await yieldTurn(); check(signal); }
      }
      pending = bytes.subarray(at);
    }
  } finally { signal?.removeEventListener('abort',abort); stream.destroy(); }
  check(signal);
  // A partially written last JSON line is retried on the next search.
  return {offset,latest,bodies};
}

export async function projectSession(session, directory, signal) {
  check(signal);
  await fs.mkdir(directory,{recursive:true});
  const key = hash(session.id+'\0'+(session.file || 'live'));
  const file = join(directory,key+'.txt'), metadata = join(directory,key+'.json');
  let old=memory.get(metadata)?.value;
  if(old){const item=memory.get(metadata);memory.delete(metadata);memory.set(metadata,item);}
  else try { const encoded=await fs.readFile(metadata,'utf8');old=JSON.parse(encoded);remember(metadata,old,encoded.length*3); } catch { /* cold cache */ }
  let stat, reusable = false;
  if (session.file) {
    stat = await fs.stat(session.file);
    reusable = old?.version === VERSION && old.source === session.file && old.identity === String(stat.ino) && stat.size >= old.offset;
    if (reusable && old.size === stat.size && old.mtime === stat.mtimeMs && (!session.leaf || session.leaf === old.leaf) && !session.live?.length) {
      try { if ((await fs.stat(file)).size === old.bytes) return {...old,file,key,session}; } catch { /* rebuild missing cache */ }
    }
    if (reusable) reusable = await signature(session.file,old.offset) === old.tail;
    if (reusable && old.size === stat.size && old.mtime !== stat.mtimeMs) reusable = false;
  }
  const graph = new Map(reusable ? old.graph.map(row => [row.id,row]) : []);
  const parsed = session.file ? await scan(session.file,reusable ? old.offset : 0,graph,signal) : {offset:0,latest:'',bodies:new Map()};
  const leaf = session.leaf || parsed.latest || (reusable ? old.leaf : '');
  const branch = [], visited = new Set();
  for (let id=leaf;id;) {
    check(signal);
    if (visited.has(id) || !graph.has(id)) throw new Error('Conversation branch is no longer available');
    visited.add(id); const row = graph.get(id); branch.push(row); id=row.parent;
  }
  branch.reverse();
  const omitted = new Set(branch.map(row=>row.omitted).filter(Boolean));
  const nodes = branch.filter(row=>row.searchable && !omitted.has(row.id));
  const oldRows = new Map(reusable ? old.messages.map(row=>[row.entryId,row]) : []);
  let append = reusable && !session.live?.length && !old.live && old.messages.length <= nodes.length && old.messages.every((row,i)=>row.entryId === nodes[i].id);
  if (append) {
    try { append = (await fs.stat(file)).size >= old.bytes; } catch { append=false; }
  }
  const temporary = file+'.tmp';
  let writer, source, previous;
  const messages = append ? old.messages.slice() : [];
  let bytes = append ? old.bytes : 0, line = append ? old.lines : 1;
  try {
    writer = await fs.open(append ? file : temporary,append ? 'r+' : 'w',0o600);
    if (append) await writer.truncate(bytes);
    if (session.file) source = await fs.open(session.file,'r');
    if (reusable && !append) { try { previous = await fs.open(file,'r'); } catch { /* use source */ } }
    const write = async (node,text,live=false) => {
      const lineOffsets = [0];
      for (let i=0;i<text.length;i++) if(text[i]==='\n')lineOffsets.push(i+1);
      const data = Buffer.from(text+'\n');
      messages.push({entryId:node.id,role:node.role,timestamp:node.timestamp,firstLine:line,
        lineOffsets,start:bytes,length:data.length,live,sourceIndex:node.sourceIndex});
      await writer.write(data,0,data.length,bytes);
      bytes += data.length; line += lineOffsets.length;
    };
    for (let i=append ? old.messages.length : 0;i<nodes.length;i++) {
      check(signal);
      const node=nodes[i]; let text=parsed.bodies.get(node.id);
      if (text === undefined) {
        const cached=oldRows.get(node.id);
        if (cached && previous) {
          const data=Buffer.alloc(cached.length-1);await previous.read(data,0,data.length,cached.start);text=data.toString('utf8');
        } else {
          const data=Buffer.alloc(node.length);await source.read(data,0,data.length,node.offset);
          text=bodyOf(JSON.parse(data.toString('utf8')).message);
        }
      }
      await write(node,text);
      if(i%128===0)await yieldTurn();
    }
    for (const item of session.live || []) {
      if (graph.has(item.entryId)) continue;
      await write({id:item.entryId,role:item.role,timestamp:stamp(item.timestamp),sourceIndex:item.sourceIndex},item.text || '',true);
    }
    await writer.close();writer=null;
    await previous?.close();previous=null;
    check(signal);
    if(!append)await fs.rename(temporary,file);
    const value={version:VERSION,source:session.file,identity:String(stat?.ino || ''),size:stat?.size || 0,mtime:stat?.mtimeMs || 0,
      offset:parsed.offset,tail:session.file ? await signature(session.file,parsed.offset) : '',leaf,graph:[...graph.values()],messages,bytes,lines:line,live:!!session.live?.length};
    const encoded=JSON.stringify(value);
    await fs.writeFile(metadata+'.tmp',encoded,{mode:0o600});
    check(signal);await fs.rename(metadata+'.tmp',metadata);
    remember(metadata,value,encoded.length*3);
    return {...value,file,key,session};
  } finally {
    await writer?.close();await source?.close();await previous?.close();
    await fs.rm(temporary,{force:true}).catch(()=>{});
  }
}

function locate(messages,line) {
  let low=0,high=messages.length;
  while(low<high){const mid=(low+high)>>>1;if(messages[mid].firstLine<=line)low=mid+1;else high=mid;}
  return messages[low-1];
}

export function mapMatch(data, projection, options={}) {
  const text=data.lines.text ?? Buffer.from(data.lines.bytes,'base64').toString('utf8');
  const encoded=Buffer.from(text);
  return data.submatches.flatMap(match=>{
    const start=encoded.subarray(0,match.start).toString('utf8').length;
    const end=encoded.subarray(0,match.end).toString('utf8').length;
    const prefix=text.slice(0,start),line=data.line_number+(prefix.match(/\n/g) || []).length;
    const row=locate(projection.messages,line);
    if(!row || data.absolute_offset+match.end>row.start+row.length-1 || options.role && row.role!==options.role || options.since && row.timestamp<options.since || options.until && row.timestamp>options.until)return [];
    const before=text.slice(Math.max(0,start-45),start).replace(/[\r\n]/g,' ');
    const hit=text.slice(start,end).replace(/[\r\n]/g,' ');
    const after=text.slice(end,end+100).replace(/[\r\n]/g,' ');
    return {sessionId:projection.session.id,title:projection.session.title,entryId:row.entryId,role:row.role,
      timestamp:row.timestamp,line:line-row.firstLine+1,
      offset:(row.lineOffsets[line-row.firstLine] || 0)+prefix.slice(prefix.lastIndexOf('\n')+1).length,
      before,hit:hit.slice(0,200),after,sourceIndex:row.sourceIndex,live:row.live,
      file:projection.source,revision:projection.mtime};
  });
}

export async function search(job, signal, emit) {
  const query=String(job.query || '');
  if(!query.trim()) {emit({type:'done',count:0});return;}
  const options=job.options || {}, directory=join(resolve(job.cache),hash(job.workspace || 'unassigned'));
  const projections=new Map();
  let skipped=0,prepared=0;
  emit({type:'preparing',total:job.sessions.length});
  const prepare=async session=>{
    check(signal);
    try {
      const value=await projectSession({...session,live:[]},directory,signal);projections.set(value.key+'.txt',value);
      if(session.live?.length){
        const nativeIds=new Set(value.graph.map(row=>row.id));
        const overlay=await projectSession({id:session.id+':live',title:session.title,file:'',live:session.live.filter(row=>!nativeIds.has(row.entryId))},directory,signal);
        overlay.session=session;projections.set(overlay.key+'.txt',overlay);
      }
    }
    catch(error){check(signal);skipped++;emit({type:'source_error',sessionId:session.id,message:error.message});}
    if(++prepared%10===0)emit({type:'preparing',completed:prepared,total:job.sessions.length});
  };
  // Bound parallel filesystem work. Wait for every cancelled preparation to
  // release its files before the next generation can touch the same cache.
  let next=0;
  await Promise.allSettled(Array.from({length:Math.min(4,job.sessions.length)},async()=>{
    while(next<job.sessions.length){check(signal);await prepare(job.sessions[next++]);}
  }));
  check(signal);
  if(!projections.size){emit({type:'done',count:0,skipped});return;}
  const args=['--json','--no-config','--no-ignore','--hidden','--glob','*.txt','--color','never','--crlf'];
  if(!options.regex)args.push('--fixed-strings');else args.push('--engine','auto');
  if(!options.caseSensitive)args.push('--ignore-case');
  if(options.wholeWord)args.push('--word-regexp');
  // Multiline matches get complete byte offsets as in VS Code's rg provider.
  if(query.includes('\n'))args.push('--multiline');
  args.push('--',query,'.');
  const process=spawn(job.rg,args,{cwd:directory,windowsHide:true,stdio:['ignore','pipe','pipe']});
  const abort=()=>process.kill();signal.addEventListener('abort',abort,{once:true});
  const decoder=createInterface({input:process.stdout,crlfDelay:Infinity});
  let stderr='',count=0,limitHit=false,batch=[],lastFlush=Date.now();
  process.stderr.on('data',bytes=>{if(stderr.length<8000)stderr+=bytes.toString('utf8');});
  const completed=new Promise((resolve,reject)=>{process.on('error',reject);process.on('close',code=>resolve(code));});
  const flush=()=>{if(batch.length){emit({type:'matches',items:batch});batch=[];}lastFlush=Date.now();};
  try {
    emit({type:'searching'});
    for await(const line of decoder) {
      check(signal);
      const event=JSON.parse(line);if(event.type!=='match')continue;
      const path=event.data.path.text ?? Buffer.from(event.data.path.bytes,'base64').toString('utf8');
      const key=path.replaceAll('\\','/').split('/').pop();const projection=projections.get(key);
      if(!projection)continue; // stale/deleted conversations never leak into results
      for(const hit of mapMatch(event.data,projection,options)) {
        batch.push(hit);count++;
        if(count>=Math.min(job.maxResults || 20000,20000)){limitHit=true;process.kill();break;}
      }
      if(batch.length>=50 || Date.now()-lastFlush>=35)flush();
      if(limitHit)break;
    }
    const code=await completed;check(signal);flush();
    if(!limitHit && code!==0 && code!==1)throw new Error(stderr.trim() || 'ripgrep could not search');
    emit({type:'done',count,limitHit,skipped});
  } finally {signal.removeEventListener('abort',abort);decoder.close();if(process.exitCode===null)process.kill();}
}

export function serve(input=process.stdin,output=process.stdout) {
  let running=null,pending=null,draining=false;
  const send=(id,event)=>output.write(JSON.stringify({id,...event})+'\n');
  const drain=async()=>{
    if(draining)return;draining=true;
    try {
      while(pending){const job=pending;pending=null;const controller=new AbortController();running=controller;
        try{await search(job,controller.signal,event=>{if(!controller.signal.aborted)send(job.id,event);});}
        catch(error){if(!controller.signal.aborted)send(job.id,{type:'error',message:error.message});}
        finally{if(running===controller)running=null;}
      }
    }finally{draining=false;}
  };
  const reader=createInterface({input,crlfDelay:Infinity});
  reader.on('line',line=>{
    try{const job=JSON.parse(line);running?.abort();pending=job.type==='search'?job:null;if(pending)void drain();}
    catch{/* malformed local protocol input is ignored */}
  });
  reader.on('close',()=>{pending=null;running?.abort();});
}
if(process.argv[1] && import.meta.url===pathToFileURL(resolve(process.argv[1])).href)serve();
