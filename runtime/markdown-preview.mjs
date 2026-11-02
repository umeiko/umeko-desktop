// Parse once outside the GUI/Pi process. Only viewport-sized blocks reach Qt.
import { Marked, Renderer } from 'marked';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const escape = text => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const CHARS = 8192, LINES = 80, TABLE_ROWS = 24;

export function textChunks(text) {
  const chunks = [];
  let start = 0;
  while (start < text.length) {
    let end = Math.min(start + CHARS, text.length);
    const lines = text.slice(start, end).split('\n');
    if (lines.length > LINES) end = start + lines.slice(0, LINES).join('\n').length + 1;
    else if (end < text.length) {
      const boundary = text.lastIndexOf('\n', end - 1);
      if (boundary > start + CHARS / 2) end = boundary + 1;
    }
    if (end < text.length && /[\uD800-\uDBFF]/.test(text[end - 1])) end--;
    chunks.push(text.slice(start, end)); start = end;
  }
  return chunks;
}

export function markdownBlocks(source) {
  const renderer = new Renderer();
  renderer.html = ({text}) => text.replace(/<[^>]*>/g, tag => /^<\/?(?:br|b|strong|em|i|s|del|sub|sup|kbd)\s*\/?\s*>$/i.test(tag) ? tag : escape(tag));
  renderer.image = ({text}) => escape(text ? `[图片: ${text}]` : '[图片]');
  renderer.link = function({href, tokens}) {
    const label = this.parser.parseInline(tokens);
    return /^(?:https?:|#)/i.test(href) ? `<a href="${escape(href)}">${label}</a>` : label;
  };
  renderer.checkbox = ({checked}) => checked ? '☑ ' : '☐ ';
  const md = new Marked({gfm:true, renderer});
  const tokens = md.lexer(source), blocks = [], slugs = new Map();
  let group = {kind:'prose', html:'', text:'', anchor:''};
  const flush = () => {if (group.html) blocks.push(group); group = {kind:'prose', html:'', text:'', anchor:''};};
  const render = token => md.parser([token]).replace(/<table>/g, '<table border="1" cellspacing="0" cellpadding="5" width="100%">');
  const prose = (html, text, anchor='') => {
    if (group.html.length + html.length > 16000 || group.text.split('\n').length + text.split('\n').length > LINES || anchor) flush();
    group.html += html; group.text += text; if (anchor) group.anchor = anchor;
  };
  const fallback = text => {
    flush();
    for (const part of textChunks(text)) blocks.push({kind:'plain', text:part, html:'', anchor:''});
  };
  // Preserve inline formatting even in paragraphs with tens of thousands of
  // characters. Split the token tree, rather than cutting Markdown delimiters.
  const inlineParts = tokens => {
    const parts = []; let part = [], size = 0;
    const add = token => {
      const length = (token.raw || token.text || '').length;
      if (size + length > CHARS && part.length) {parts.push(part);part=[];size=0;}
      part.push(token);size+=length;
    };
    for (const token of tokens) {
      if ((token.raw || token.text || '').length <= CHARS) add(token);
      else if (token.tokens) {
        for (const inner of inlineParts(token.tokens)) add({...token,tokens:inner,raw:'',text:inner.map(t=>t.text || '').join('')});
      } else if (['text','codespan','escape'].includes(token.type)) {
        for (const text of textChunks(token.text)) add({...token,raw:text,text});
      } else {
        for (const text of textChunks(token.raw || token.text || '')) add({type:'text',raw:text,text});
      }
    }
    if (part.length) parts.push(part);
    return parts;
  };
  for (const token of tokens) {
    if (token.type === 'space' || token.type === 'def') continue;
    if (token.type === 'code') {
      flush();
      let continued=false;
      for (const part of textChunks(token.text)) {
        blocks.push({kind:'code', text:part, html:'', language:(token.lang || '').split(/\s/)[0], anchor:'', continued});
        continued=true;
      }
    } else if (token.type === 'table') {
      flush(); let rows = [], size = 0;
      const table = () => {if(rows.length){blocks.push({kind:'prose', text:rows.map(row=>row.map(cell=>cell.text).join(' | ')).join('\n'), html:render({...token, rows}), anchor:''}); rows=[];size=0;}};
      for (const row of token.rows) {
        const length = row.reduce((n,cell)=>n+cell.text.length,0);
        if (rows.length >= TABLE_ROWS || size + length > CHARS) table();
        if (length > CHARS) {fallback(row.map((cell,i)=>`${token.header[i].text}: ${cell.text}`).join('\n'));continue;}
        rows.push(row);size+=length;
      }
      table();
      if (!token.rows.length) blocks.push({kind:'prose',text:token.raw,html:render(token),anchor:''});
    } else if (token.type === 'list' && token.raw.length > CHARS) {
      flush(); let items=[], size=0, start=token.start;
      const list = () => {if(items.length){blocks.push({kind:'prose',text:items.map(item=>item.raw).join(''),html:render({...token,items,start}),anchor:''});if(token.ordered)start+=items.length;items=[];size=0;}};
      for (const item of token.items) {
        if (items.length >= 24 || size + item.raw.length > CHARS) list();
        if (item.raw.length > CHARS) {fallback(item.raw);if(token.ordered)start++;continue;}
        items.push(item);size+=item.raw.length;
      }
      list();
    } else {
      const text=token.raw || token.text || '';
      if (text.length > CHARS) {
        if (token.type === 'paragraph' && token.tokens) {
          flush();
          for (const part of inlineParts(token.tokens)) prose(`<p>${md.Parser.parseInline(part,md.defaults)}</p>`,part.map(t=>t.raw || t.text || '').join(''));
        } else fallback(text);
        continue;
      }
      let anchor='';
      if (token.type === 'heading') {
        const slug=token.text.toLowerCase().replace(/<[^>]*>/g,'').replace(/[^\p{L}\p{N}_\s-]/gu,'').trim().replace(/\s+/g,'-');
        const count=slugs.get(slug)||0;slugs.set(slug,count+1);anchor=slug+(count?'-'+count:'');
      }
      prose(render(token),text,anchor);
    }
  }
  flush();
  return blocks;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    process.stdin.setEncoding('utf8');
    let source='';for await(const chunk of process.stdin)source+=chunk;
    process.stdout.write(JSON.stringify({blocks:markdownBlocks(source)}));
  } catch(error) {process.stderr.write(String(error.message));process.exitCode=1;}
}
