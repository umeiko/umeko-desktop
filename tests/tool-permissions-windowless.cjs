'use strict';
// Test-only native process launch options. Execution still belongs to Pi.
const cp=require('node:child_process');
const {syncBuiltinESMExports}=require('node:module');
const {promisify}=require('node:util');
const marker=Symbol.for('umeko.p400.windowsHide');
if(!cp[marker]){
  function wrap(name,indexFor){
    const original=cp[name];
    function hidden(args){
      globalThis[Symbol.for('umeko:test:before-process')]?.(name,args);
      const i=indexFor(args),old=args[i];
      if(old!=null&&typeof old!=='object'&&typeof old!=='function')return args;
      const options={...(old&&typeof old==='object'?old:{}),windowsHide:true};
      if(typeof old==='function')args.splice(i,0,options);else args[i]=options;
      return args;
    }
    const wrapped=function(...args){return Reflect.apply(original,this,hidden(args));};
    for(const symbol of Object.getOwnPropertySymbols(original)){
      const d=Object.getOwnPropertyDescriptor(original,symbol);
      Object.defineProperty(wrapped,symbol,symbol===promisify.custom&&typeof original[symbol]==='function'
        ?{...d,value:function(...args){return Reflect.apply(original[symbol],this,hidden(args));}}:d);
    }
    cp[name]=wrapped;
  }
  for(const name of ['spawn','spawnSync','execFile','execFileSync'])wrap(name,args=>Array.isArray(args[1])?2:1);
  for(const name of ['exec','execSync'])wrap(name,()=>1);
  cp[marker]=true;syncBuiltinESMExports();
}
