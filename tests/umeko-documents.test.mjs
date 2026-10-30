import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { prepareDocumentation, availableModels } from '../runtime/releases/coding-1.3.0/umeko-documents.mjs';
import { configureUmekoDocs, umekoHelp, UMEKO_PROMPT } from '../runtime/releases/coding-1.3.0/umeko-control.mjs';

test('delegation guide contains current wrapped model names without changing the prompt', () => {
  const root = mkdtempSync(join(tmpdir(), 'umeko-docs-test-'));
  const models = [{id:'analysis-model',owned_by:'Local Provider',contextWindow:32000,input:['text'],apiKey:'must-not-leak'}];
  const source = readFileSync(new URL('../runtime/umeko-docs/delegate-subagents.md', import.meta.url),'utf8');
  const prompt = UMEKO_PROMPT;
  const first = prepareDocumentation({directory:join(root,'first'),models});
  const text = readFileSync(join(first.docsRoot,'delegate-subagents.md'),'utf8');
  assert.match(text,/umeko\/analysis-model/); assert.match(text,/Local Provider/);
  assert.doesNotMatch(text,/must-not-leak|UMEKO_AVAILABLE_MODELS/);
  assert.match(readFileSync(first.entry,'utf8'),/委派子代理.*delegate-subagents\.md/);
  assert.equal(readFileSync(new URL('../runtime/umeko-docs/delegate-subagents.md',import.meta.url),'utf8'),source);
  configureUmekoDocs({directory:join(root,'second'),models:[{id:'other-model'}]});
  assert.notEqual(umekoHelp().docsRoot,first.docsRoot);
  const current = readFileSync(join(umekoHelp().docsRoot,'delegate-subagents.md'),'utf8');
  assert.match(current,/umeko\/other-model/); assert.doesNotMatch(current,/analysis-model/);
  assert.equal(UMEKO_PROMPT,prompt);
  assert.deepEqual(availableModels(models).map(row=>row.model),['umeko/analysis-model']);
});

test('updated model lists replace stale entries and markup stays inside table cells', () => {
  const directory = mkdtempSync(join(tmpdir(),'umeko-docs-update-'));
  prepareDocumentation({directory,models:[{id:'old'}]});
  prepareDocumentation({directory,models:[{id:'new',owned_by:'A|B\nprovider'}]});
  const text = readFileSync(join(directory,'delegate-subagents.md'),'utf8');
  assert.match(text,/umeko\/new/); assert.doesNotMatch(text,/umeko\/old/);
  assert.ok(text.includes('A\\|B provider'));
  prepareDocumentation({directory,models:[]});
  assert.match(readFileSync(join(directory,'delegate-subagents.md'),'utf8'),/尚无可用模型/);
});
