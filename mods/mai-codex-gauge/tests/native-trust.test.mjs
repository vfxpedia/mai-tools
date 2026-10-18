import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

test('approved native trust updates only the eight exact product handlers and preserves other trust',async()=>{
 const {trustGaugeHooks}=await import('../src/native-trust.mjs');
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'mai-trust-test-'));
 const home=path.join(root,'home');fs.mkdirSync(home);fs.writeFileSync(path.join(home,'config.toml'),'[features]\nhooks = true\n');
 const events=['sessionStart','userPromptSubmit','preToolUse','postToolUse','stop','interrupt','preCompact','postCompact'];
 const command=`node "${path.join(home,'mai-codex-gauge','src','hook.mjs').replaceAll('\\','/')}"`;
 const hooks=events.map((eventName,i)=>({key:`gauge:${i}`,currentHash:`sha256:${String(i).repeat(64)}`,eventName,command,handlerType:'command',sourcePath:path.join(home,'hooks.json'),enabled:true,isManaged:false,trustStatus:'untrusted'}));
 hooks.push({...hooks[0],key:'orca:other',command:'node orca-hook.js',trustStatus:'untrusted'});
 let reads=0,writes=0;
 const rpc=async(method,params)=>{
  if(method==='hooks/list'){reads++;return {data:[{cwd:root,hooks:hooks.map(h=>({...h,trustStatus:writes&&h.key.startsWith('gauge:')?'trusted':h.trustStatus})),errors:[],warnings:[]}]};}
  assert.equal(method,'config/batchWrite');writes++;
  assert.equal(params.reloadUserConfig,true);assert.equal(params.edits[0].keyPath,'hooks.state');
  assert.equal(params.edits[0].mergeStrategy,'upsert');assert.deepEqual(Object.keys(params.edits[0].value),events.map((_,i)=>`gauge:${i}`));
  fs.appendFileSync(path.join(home,'config.toml'),'# verified trust fixture\n');return {status:'ok',version:'new'};
 };
 const plan=await trustGaugeHooks({home,cwd:root,rpc,approved:false});assert.equal(plan.review.length,8);assert.equal(writes,0);
 const result=await trustGaugeHooks({home,cwd:root,rpc,approved:true});assert.equal(result.verified,true);assert.equal(writes,1);assert.equal(result.handlers,8);
 const manifest=JSON.parse(fs.readFileSync(result.manifest,'utf8'));assert.equal(manifest.files.length,1);assert.equal(manifest.files[0].path,path.join(home,'config.toml'));
 assert.equal(fs.readFileSync(manifest.files[0].backup,'utf8'),'[features]\nhooks = true\n');assert.ok(reads>=3);
});

test('missing, duplicated, disabled or foreign-source handler cannot obtain blanket trust',async()=>{
 const {trustGaugeHooks}=await import('../src/native-trust.mjs');
 const home=path.join(os.tmpdir(),'trust-invalid-home');
 for(const hooks of [[],[{command:'node other/mai-codex-gauge/src/hook.mjs',eventName:'stop',key:'foreign',currentHash:'sha256:'+('a'.repeat(64)),enabled:true,sourcePath:path.join(home,'hooks.json')} ]]){
  let writes=0;const rpc=async(method)=>{if(method!=='hooks/list')writes++;return {data:[{hooks,errors:[],warnings:[]}]};};
  await assert.rejects(trustGaugeHooks({home,cwd:os.tmpdir(),rpc,approved:true}));assert.equal(writes,0);
 }
});

test('native RPC keeps error contents private and initializes before the permitted request',async()=>{
 const {nativeRpc}=await import('../src/native-rpc.mjs');
 const server=String.raw`let b='';let ready=false;process.stdin.on('data',s=>{b+=s;let n;while((n=b.indexOf('\n'))>=0){const q=JSON.parse(b.slice(0,n));b=b.slice(n+1);if(q.method==='initialize'){ready=true;process.stdout.write(JSON.stringify({id:q.id,result:{}})+'\n');}else if(q.method==='initialized'){}else if(ready&&q.method==='hooks/list'){process.stdout.write(JSON.stringify({id:q.id,result:{data:[]}})+'\n');}else process.stdout.write(JSON.stringify({id:q.id,error:{message:'SECRET_VALUE'}})+'\n');}});`;
 const value=await nativeRpc({executable:process.execPath,args:['-e',server],transport:'stdio',timeoutMs:1000},'hooks/list',{cwds:[]});assert.deepEqual(value,{data:[]});
 await assert.rejects(nativeRpc({executable:process.execPath,args:['-e',server],transport:'stdio',timeoutMs:1000},'thread/start',{}),/not permitted/);
});
