import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {safePath,readJson} from './store.mjs';
import {discoverProviderRpc} from './provider.mjs';
import {nativeRpc} from './native-rpc.mjs';
import {hookCommand} from './hook-command.mjs';

const expected=['sessionStart','userPromptSubmit','preToolUse','postToolUse','stop','interrupt','preCompact','postCompact'];
const digest=b=>crypto.createHash('sha256').update(b).digest('hex');
const norm=p=>path.resolve(p).replaceAll('\\','/');
function selectGauge(response,home){
 if(!Array.isArray(response?.data)||response.data.some(x=>!Array.isArray(x.hooks)||!Array.isArray(x.errors)||x.errors.length))throw Error('native hook inventory unavailable');
 const cfg=readJson(safePath(home,'mai-codex-gauge.json'));
 const plugin=cfg?.mode==='native',version=plugin?readJson(safePath(home,'mai-codex-gauge','package.json'))?.version:null;
 if(plugin&&!/^\d+\.\d+\.\d+$/.test(version??''))throw Error('installed plugin version unavailable');
 const product=plugin?path.join(home,'plugins','cache','mai-codex-local','mai-codex-gauge',version):path.join(home,'mai-codex-gauge');
 const root=norm(path.join(product,'src','hook.mjs')),source=norm(plugin?path.join(product,'hooks.json'):path.join(home,'hooks.json'));
 const hooks=response.data.flatMap(x=>x.hooks).filter(h=>{
  const command=typeof h.command==='string'?h.command.replaceAll('\\','/'):'';
  const expected=cfg?.hookRuntime?hookCommand(path.join(product,'src','hook.mjs'),cfg.hookRuntime):`node "${root}"`;
  return command===expected.replaceAll('\\','/')&&(!plugin||h.pluginId==='mai-codex-gauge@mai-codex-local');
 });
 if(hooks.length!==8||expected.some(e=>hooks.filter(h=>h.eventName===e).length!==1)||new Set(hooks.map(h=>h.key)).size!==8)throw Error('exact eight product hooks required');
 for(const h of hooks){
  if(h.enabled!==true||h.isManaged||norm(h.sourcePath)!==source||typeof h.key!=='string'||!h.key||!/^(?:sha256:)?[a-f\d]{64}$/.test(h.currentHash)||!['untrusted','modified','trusted'].includes(h.trustStatus))throw Error('product hook review refused');
 }
 return hooks;
}

// Same operation as native /hooks: exact current hashes through config/batchWrite,
// with explicit approval, private backup and independent native readback.
export async function trustGaugeHooks({home,cwd,approved=false,rpc=null,backupDir=null}){
 home=path.resolve(home);cwd=path.resolve(cwd);safePath(path.dirname(home),path.basename(home));
 const options=rpc?null:discoverProviderRpc(home);if(!rpc&&!options)throw Error('managed native RPC unavailable');
 const call=rpc??((method,params)=>nativeRpc({...options,timeoutMs:5000},method,params));
 const hooks=selectGauge(await call('hooks/list',{cwds:[cwd]}),home);
 const review=hooks.map(h=>({event:h.eventName,key:h.key,hash:h.currentHash,command:h.command,status:h.trustStatus}));
 if(!approved)return {approved:false,review};
 const pending=hooks.filter(h=>h.trustStatus!=='trusted');if(!pending.length)return {approved:true,verified:true,handlers:8,changed:0,manifest:null};
 const config=safePath(home,'config.toml'),before=fs.readFileSync(config);
 const backup=backupDir??path.join(home,'mai-codex-gauge-backups',`trust-${Date.now()}-${crypto.randomUUID()}`);
 safePath(path.dirname(backup),path.basename(backup));fs.mkdirSync(backup,{recursive:true});
 const copy=path.join(backup,'0.before'),file=path.join(backup,'manifest.json');
 fs.writeFileSync(copy,before,{flag:'wx',mode:0o600});
 const manifest={version:1,home,backup,selector:'approved-native-hook-trust',at:Date.now(),approval:'explicit user approval',review,files:[{path:config,beforeHash:digest(before),afterHash:null,backup:copy}]};
 fs.writeFileSync(file,JSON.stringify(manifest,null,2)+'\n',{flag:'wx',mode:0o600});
 if(digest(fs.readFileSync(config))!==digest(before))throw Error('config changed before approval; no update sent');
 await call('config/batchWrite',{edits:[{keyPath:'hooks.state',value:Object.fromEntries(pending.map(h=>[h.key,{trusted_hash:h.currentHash}])),mergeStrategy:'upsert'}],reloadUserConfig:true});
 manifest.files[0].afterHash=digest(fs.readFileSync(config));fs.writeFileSync(file,JSON.stringify(manifest,null,2)+'\n',{mode:0o600});
 const after=selectGauge(await call('hooks/list',{cwds:[cwd]}),home);
 if(after.some(h=>h.trustStatus!=='trusted'||!hooks.some(b=>b.key===h.key&&b.currentHash===h.currentHash)))throw Error('native hook trust readback failed; inspect private backup');
 return {approved:true,verified:true,handlers:after.length,changed:pending.length,manifest:file};
}
