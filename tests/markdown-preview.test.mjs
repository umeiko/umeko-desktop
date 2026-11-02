import {test} from 'node:test';
import assert from 'node:assert/strict';
import {markdownBlocks, textChunks} from '../runtime/markdown-preview.mjs';

test('all code survives bounded chunks, including astral Unicode and literal pipes',()=>{
  const code=('fn main() { println!("𠮷🙂 | **literal**"); }\n').repeat(5000);
  const blocks=markdownBlocks('```rust\n'+code+'```');
  assert.equal(blocks.map(b=>b.text).join(''),code.trimEnd());
  assert.ok(blocks.every(b=>b.kind==='code' && b.language==='rust' && b.text.length<=8192));
  assert.ok(blocks.every(b=>!/[\uD800-\uDBFF]$/.test(b.text)));
  const chunks=textChunks('x'.repeat(8192)+'\n'+'🙂'.repeat(20000));
  assert.equal(chunks.join(''),'x'.repeat(8192)+'\n'+'🙂'.repeat(20000));
  assert.ok(chunks.every(c=>c.length<=8192));
});

test('large tables render all rows with repeated headers and reference links',()=>{
  const source='| Name | Value |\n| --- | --- |\n'+Array.from({length:1000},(_,i)=>`| row-${i} | [docs][ref] **${i}** |\n`).join('')+'\n[ref]: https://example.com/docs';
  const blocks=markdownBlocks(source);
  assert.equal(blocks.length,42);
  assert.ok(blocks.every(b=>b.html.includes('<th>Name</th>')));
  assert.ok(blocks.at(-1).html.includes('row-999'));
  assert.ok(blocks.every(b=>b.html.includes('href="https://example.com/docs"')));
});

test('large documents preserve headings, final paragraphs and list numbering',()=>{
  const paragraphs=Array.from({length:1000},(_,i)=>`## Section ${i}\n\n**Paragraph ${i}**\n\n`).join('');
  const blocks=markdownBlocks(paragraphs+'[Jump](#section-999)\n');
  assert.ok(blocks.some(b=>b.anchor==='section-999'));
  assert.ok(blocks.at(-1).html.includes('href="#section-999"'));
  const list=markdownBlocks(Array.from({length:1000},(_,i)=>`${i+1}. item-${i} long description\n`).join(''));
  assert.ok(list.at(-1).html.includes('item-999'));
  assert.ok(list[1].html.includes('start="25"'));
});

test('long paragraphs keep inline markup and the tail instead of becoming plain source',()=>{
  const blocks=markdownBlocks('**'+('large paragraph words 🙂 ').repeat(2000)+'TAIL**');
  assert.ok(blocks.length>2);
  assert.ok(blocks.every(b=>b.html.includes('<strong>')));
  assert.ok(blocks.at(-1).html.includes('TAIL'));
  assert.ok(blocks.every(b=>b.html.length<20000));
});

test('images, HTML resources and active links cannot fetch content',()=>{
  const blocks=markdownBlocks('<script>alert(1)</script>\n\n<img src="file:///secret">\n\n![alt](https://example.com/img)\n\n[bad](javascript:alert) [good](https://example.com)');
  const html=blocks.map(b=>b.html).join('');
  assert.ok(!/<script|<img|href="javascript:/i.test(html));
  assert.ok(html.includes('[图片: alt]'));
  assert.ok(html.includes('href="https://example.com"'));
});
