import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {planInstall,applyInstall,rollback} from './install.mjs';
import {safePath,readJson,validateId} from './store.mjs';
import {recordIssueReceipt} from './checkpoint.mjs';
import {readProviderUsage,discoverProviderRpc} from './provider.mjs';
import {readHookDiagnostics} from './hook-diagnostics.mjs';
import {nativeRpc} from './native-rpc.mjs';
import {isGaugeCommand} from './hook-command.mjs';

const source=path.resolve(import.meta.dirname,'..');
const hash=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const optional=file=>{try{return readJson(file);}catch(e){if(e.code==='ENOENT')return null;throw e;}};
export function doctor({home,base,sessionId}){
 const cfg=optional(safePath(home,'mai-codex-gauge.json'));
 const configFile=safePath(home,'config.toml'),text=fs.existsSync(configFile)?fs.readFileSync(configFile,'utf8'):'';
 const hooks=optional(safePath(home,'hooks.json'))?.hooks??{};
 const handlerEvents=Object.entries(hooks).filter(([,groups])=>Array.isArray(groups)&&groups.some(g=>g.hooks?.some(h=>isGaugeCommand(h.command)))).map(([event])=>event);
 const units=sessionId?optional(safePath(base,'units',`${validateId(sessionId)}.json`)):null;
 if(units&&units.sessionId!==sessionId)throw Error('observation owner mismatch');
 const c=units?.codex??{},events=(c.events??[]).filter(x=>typeof x.event==='string');
 const hookFile=path.join(home,'mai-codex-gauge','src','hook.mjs');
 const installed=!!cfg&&fs.existsSync(hookFile);
 const provider=c.provider,validUsd=provider?.status==='available'&&provider.threadId===sessionId&&Number.isSafeInteger(provider.usdMicros)&&provider.usdMicros>=0;
 const quota=provider?.rateLimits,windows=[quota?.primary,quota?.secondary].filter(Boolean);
 return {home,installed,mode:cfg?.mode??null,account:cfg?.account??null,productHash:installed?hash(hookFile):null,
  handlerEventsConfigured:handlerEvents,pluginConfigured:/\[plugins\."mai-codex-gauge@mai-codex-local"\][^[]*?^\s*enabled\s*=\s*true/m.test(text),
  inheritedNativeGaugeMasked:/\[plugins\."mai-codex-gauge@mai-codex-local"\][^[]*?^\s*enabled\s*=\s*false/m.test(text),
  hooksDisabled:/\[features\][^[]*?^\s*hooks\s*=\s*false/m.test(text),
  trust:'not inferred; review exact handlers in /hooks',handlerEventsObserved:events.length,
  activation:events.length?'handler events observed; native trust is a separate check':'not observed',pendingTokenTurns:Object.keys(c.pendingTurns??{}).length,
  lastEvent:events.at(-1)??null,hookDiagnostics:readHookDiagnostics(base,sessionId),inlineFiveRows:'unsupported by native statusline',
  cost:{session:validUsd?'provider estimate':provider?.reason??'not observed',sessionUsd:validUsd?provider.usdMicros/1e6:null,
   turn:Object.keys(c.providerTurns??{}).length?'recorded provider deltas':'not observed'},
  quota:{fiveHours:windows.some(x=>x.window_minutes===300)?'provided':'not provided',sevenDays:windows.some(x=>x.window_minutes===10080)?'provided':'not provided'},
  continuity:{checkpoints:c.contextPolicy?.checkpoints?.length??0,verifiedIssueReceipts:(c.contextPolicy?.checkpoints??[]).filter(x=>x.issueStatus==='verified').length},
  restart:'do not restart active sessions automatically; retain exact session ID and original transcript'};
}

function parse(args){
 const options={},allowed=new Set(['home','account','mode','backup','manifest','base','session','comment','native','approve','exe','mask-native']);
 for(let i=0;i<args.length;i++){const key=args[i].replace(/^--/,'');if(!args[i].startsWith('--')||!allowed.has(key)||Object.hasOwn(options,key)||!args[i+1]||args[i+1].startsWith('--'))throw Error('unknown, repeated or incomplete option');options[key]=args[++i];}
 return options;
}
export async function main(args=process.argv.slice(2)){
 const command=args.shift()??'--help';
 if(['--help','help'].includes(command)){console.log('mai-codex-mods: plan | install | doctor | trust | checkpoint | rollback\ninstall --account codex:ALIAS [--home CODEX_HOME] [--mode auto|native|hooks]\ndoctor [--home CODEX_HOME] [--session ID] [--native true]\ntrust [--home CODEX_HOME] [--approve true]: exact eight hashes; explicit user approval only\ncheckpoint --session ID --comment EXACT_ISSUE_COMMENT_URL\nrollback --manifest EXACT_BACKUP_MANIFEST\nshow | metrics | watch | live | status | scan | api: existing gauge commands\nNode >=22; native hook trust review in /hooks or approved native trust RPC is required.');return;}
 if(['show','metrics','watch','live','status','scan','observe','diagnose','api'].includes(command)){const cli=await import('./cli.mjs');return cli.main([command,...args]);}
 const options=parse(args),home=path.resolve(options.home??process.env.CODEX_HOME??path.join(os.homedir(),'.codex')),base=path.resolve(options.base??path.join(os.homedir(),'.mai')),sessionId=options.session??process.env.CODEX_THREAD_ID;
 if(options.exe&&(!['trust','doctor'].includes(command)||!path.isAbsolute(options.exe)))throw Error('--exe requires an absolute native executable for trust or doctor');
 const rpcOptions=options.exe?{executable:options.exe,args:['app-server','--stdio'],environment:{...process.env,CODEX_HOME:home,CODEX_THREAD_ID:''},timeoutMs:5000}:null;
 if(command==='trust'){
  if(options.approve!==undefined&&options.approve!=='true')throw Error('--approve expects true after explicit user review');
  const {trustGaugeHooks}=await import('./native-trust.mjs');return console.log(JSON.stringify(await trustGaugeHooks({home,cwd:process.cwd(),approved:options.approve==='true',rpc:rpcOptions?(method,params)=>nativeRpc(rpcOptions,method,params):null}),null,2));
 }
 if(command==='doctor'){
  const result=doctor({home,base,sessionId});
  if(options.native){if(options.native!=='true')throw Error('--native expects true');const rpc=rpcOptions??discoverProviderRpc(home);
   result.native=rpc?await readProviderUsage({...rpc,timeoutMs:5000,sessionId:sessionId||'installation-check',includeLimits:true,includeHooks:true}):{hooksStatus:'unavailable',reason:'managed read-only RPC not found'};
  }
  return console.log(JSON.stringify(result,null,2));
 }
 if(command==='checkpoint')return console.log(JSON.stringify(await recordIssueReceipt({base,sessionId,url:options.comment})));
 if(command==='rollback'){
  if(!options.manifest||!path.isAbsolute(options.manifest))throw Error('exact absolute manifest required');
  const result=rollback(readJson(safePath(path.dirname(options.manifest),path.basename(options.manifest))));console.log(JSON.stringify(result));if(!result.restored)process.exitCode=1;return;
 }
 if(!['plan','install'].includes(command))throw Error('unknown command');
 if(Number(process.versions.node.split('.')[0])<22)throw Error('Node >=22 required');
 safePath(path.dirname(home),path.basename(home));
 const existing=optional(safePath(home,'mai-codex-gauge.json')),account=options.account??existing?.account;
 let mode=options.mode??'auto';
 if(mode==='auto'){
  const plugins=path.join(home,'plugins');
  mode=['native','hooks'].includes(existing?.mode)?existing.mode:fs.existsSync(plugins)&&fs.lstatSync(plugins).isSymbolicLink()?'hooks':'native';
 }
 if(!['native','hooks'].includes(mode))throw Error('installation mode must be native or hooks');
 if(options['mask-native']!==undefined&&(options['mask-native']!=='true'||mode!=='hooks'))throw Error('--mask-native true requires an explicitly approved hooks-mode install');
 const plan=planInstall({codexHome:home,source,account,mode,maskNative:options['mask-native']==='true'});
 if(command==='plan')return console.log(JSON.stringify({home,mode,trust:plan.hooksTrust,changedFiles:plan.changes.length,paths:plan.changes.map(x=>x.path)},null,2));
 let manifest=null;
 if(plan.changes.length){const backup=options.backup??path.join(home,'mai-codex-gauge-backups',`${Date.now()}-${crypto.randomUUID()}`);manifest=path.join(applyInstall(plan,backup).backup,'manifest.json');}
 console.log(JSON.stringify({home,mode,changedFiles:plan.changes.length,manifest,trust:'review in /hooks',alreadyRunningSessions:'not restarted or claimed active'}));
}
if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url)main().catch(error=>{console.error(`Codex Mods operation refused: ${error.message}. No trust bypass or automatic session restart.`);process.exitCode=1;});
