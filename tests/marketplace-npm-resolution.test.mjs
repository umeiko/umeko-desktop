import test from 'node:test';
import assert from 'node:assert/strict';
import {resolveNpmCliPath} from '../runtime/marketplace-source.mjs';

test('npm resolver supports setup-node Linux prefix/lib layout',()=>{
 const expected='/opt/hostedtoolcache/node/24.10.0/x64/lib/node_modules/npm/bin/npm-cli.js';
 assert.equal(resolveNpmCliPath({execPath:'/opt/hostedtoolcache/node/24.10.0/x64/bin/node',env:{},platform:'linux',exists:path=>path===expected}),expected);
});

test('npm resolver keeps the Windows adjacent npm layout',()=>{
 const expected='C:\\Program Files\\nodejs\\node_modules\\npm\\bin\\npm-cli.js';
 assert.equal(resolveNpmCliPath({execPath:'C:\\Program Files\\nodejs\\node.exe',env:{},platform:'win32',exists:path=>path===expected}),expected);
});

test('npm resolver prefers an existing npm_execpath',()=>{
 const expected='/custom/npm/bin/npm-cli.js';
 assert.equal(resolveNpmCliPath({execPath:'/opt/node/bin/node',env:{npm_execpath:expected},platform:'linux',exists:()=>true}),expected);
});

test('npm resolver retains the missing npm error',()=>{
 assert.throws(()=>resolveNpmCliPath({execPath:'/opt/node/bin/node',env:{},platform:'linux',exists:()=>false}),/npm-cli.js not found/);
});
