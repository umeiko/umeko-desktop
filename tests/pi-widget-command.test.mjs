import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../umeko-plugins/pi-manager/qml/Commands.js',import.meta.url),'utf8').replace(/^\.pragma library\s*/,'');
const context=vm.createContext({});vm.runInContext(source,context);
const parse=(value,project=false)=>JSON.parse(JSON.stringify(context.parse(value,project)));

test('Pi Widget passes one literal source with correct install scope',()=>{
  assert.deepEqual(parse('pi install npm:example@1.2.3'),{source:'npm:example@1.2.3',project:false,forcedProject:false});
  assert.equal(parse('git:github.com/example/plugin',true).project,true);
  assert.deepEqual(parse('pi install "/tmp/插件 package" --local'),{source:'/tmp/插件 package',project:true,forcedProject:true});
  assert.equal(parse(String.raw`pi install "C:\Users\User\my plugin"`).source,String.raw`C:\Users\User\my plugin`);
});
test('Pi Widget rejects ambiguous commands without invoking a shell',()=>{
  for(const value of ['', 'pi remove npm:x', 'pi install npm:x npm:y','pi install --unknown npm:x','pi install "missing quote','pi install npm:x\nwhoami','pi install npm:x && whoami','$(whoami)','pi install npm:x; whoami'])
    assert.throws(()=>parse(value),undefined,value);
});
