import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';import os from 'node:os';
const idPattern=/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/;
export function validateId(id){if(typeof id!=='string'||!idPattern.test(id))throw Error('invalid session id');return id;}
export function safePath(base,...parts){
 if(parts.some(p=>typeof p!=='string'||p==='..'||p.includes('..')||/[\\/]/.test(p)))throw Error('unsafe path component');
 const target=path.resolve(base,...parts);let p=target;
 while(true){try{if(fs.lstatSync(p).isSymbolicLink())throw Error('symlink/junction refused');}catch(e){if(e.code!=='ENOENT')throw e;}const up=path.dirname(p);if(up===p)break;p=up;}
 return target;
}
const digest=x=>crypto.createHash('sha256').update(x).digest('hex');
function read(file){try{return fs.readFileSync(file);}catch(e){if(e.code==='ENOENT')return null;throw e;}}
function deadLocalOwner(bytes){
 try{const owner=JSON.parse(bytes?.toString('utf8')??'');
 if(!Number.isSafeInteger(owner.pid)||owner.pid<1||owner.host!==os.hostname()||typeof owner.nonce!=='string'||!/^[a-zA-Z0-9_-]{1,100}$/.test(owner.nonce))return null;
 try{process.kill(owner.pid,0);return null;}catch(e){return e.code==='ESRCH'?owner:null;}
 }catch{return null;}
}
function recoverTerminatedWriter(lock){
 // An engine timeout can terminate a hook without running finally. Only a
 // proved-dead local PID is recoverable. Age alone, legacy empty locks and
 // foreign-host locks never authorize stealing a writer's lock.
 if(!deadLocalOwner(read(lock)))return false;
 const guard=`${lock}.recovery-lock`;let guardFd;
 try{guardFd=fs.openSync(guard,'wx',0o600);}catch(e){if(e.code==='EEXIST')return false;throw e;}
 try{
  const owner=deadLocalOwner(read(lock));if(!owner)return false;
  fs.renameSync(lock,`${lock}.abandoned-${owner.nonce}`);return true;
 }finally{fs.closeSync(guardFd);fs.unlinkSync(guard);}
}
export function atomicUpdate(file,expectedOwner,update,{waitMs=350}={}){
 safePath(path.dirname(file),path.basename(file));fs.mkdirSync(path.dirname(file),{recursive:true});
 const lock=`${file}.gauge-lock`;let fd;
 const began=performance.now();while(true){try{fd=fs.openSync(lock,'wx',0o600);fs.writeFileSync(fd,JSON.stringify({pid:process.pid,host:os.hostname(),nonce:crypto.randomUUID(),at:Date.now()}));break;}catch(e){if(e.code!=='EEXIST')throw e;if(recoverTerminatedWriter(lock))continue;if(performance.now()-began>=waitMs)return {written:false,reason:'writer busy'};Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,Math.min(10,Math.max(1,waitMs-(performance.now()-began))));}}
 let tmp=null;
 try {
 const bytes=read(file);const old=bytes===null?null:JSON.parse(bytes.toString('utf8'));
 if(old!==null&&(typeof old!=='object'||Array.isArray(old)))throw Error('invalid shared JSON schema');
 if(expectedOwner&&old&&((old.id??old.sessionId)!==expectedOwner))throw Error('owner mismatch');
 const next=update(old);if(next===null)return {written:false,reason:'no change',value:old};
 if(expectedOwner&&(next.id??next.sessionId)!==expectedOwner)throw Error('new owner mismatch');
 const current=read(file);if((current===null)!==(bytes===null)||current&&digest(current)!==digest(bytes))return {written:false,reason:'concurrent external edit'};
 tmp=`${file}.${crypto.randomUUID()}.tmp`;const out=fs.openSync(tmp,'wx',0o600);try{fs.writeFileSync(out,JSON.stringify(next,null,2)+'\n');fs.fsyncSync(out);}finally{fs.closeSync(out);}
 const recheck=read(file);if((recheck===null)!==(bytes===null)||recheck&&digest(recheck)!==digest(bytes))return {written:false,reason:'concurrent external edit'};
 // Windows readers may briefly omit FILE_SHARE_DELETE. Retain the complete
 // temp file, retry only this rename, and recheck the original on every retry.
 const replaceBegan=performance.now();
 while(true){
  const latest=read(file);if((latest===null)!==(bytes===null)||latest&&digest(latest)!==digest(bytes))return {written:false,reason:'concurrent external edit'};
  try{fs.renameSync(tmp,file);break;}catch(e){if(process.platform!=='win32'||!['EPERM','EACCES','EBUSY'].includes(e.code)||performance.now()-replaceBegan>=waitMs)throw e;Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,10);}
 }
 tmp=null;return {written:true,reason:'saved',value:next};
 }finally{if(tmp&&fs.existsSync(tmp))fs.unlinkSync(tmp);fs.closeSync(fd);fs.unlinkSync(lock);}
}
export function readJson(file){const b=read(file);return b===null?null:JSON.parse(b.toString('utf8'));}
export function saveSession(base,id,event){
 validateId(id);if(!Number.isFinite(event.at)||event.at<0)throw Error('invalid event time');
 const f=safePath(base,'sessions',`${id}.json`);
 const result=atomicUpdate(f,id,old=>{
 if(old&&(!Number.isFinite(old.startedAt)||!Number.isFinite(old.updatedAt)||typeof old.name!=='string'||!Array.isArray(old.issues)))throw Error('invalid session schema');
 if(old&&event.at<old.updatedAt)return null;
 const s=old??{id,name:`Codex ${id.slice(0,8)}`,handle:null,cwd:event.cwd??'',repo:null,doing:'',issues:[],waiting:'',next:'',contextPercent:null,startedAt:event.at,updatedAt:event.at,statusAt:null};
 const next={...s,updatedAt:event.at,contextPercent:null};
 if(!s.titled&&typeof event.name==='string')next.name=event.name;
 if(event.titled===true&&typeof event.name==='string'){next.name=event.name;next.titled=true;}
 for(const key of ['doing','waiting','next','cwd','repo'])if(typeof event[key]==='string')next[key]=event[key];
 if(Array.isArray(event.issues)&&event.issues.every(x=>typeof x==='string'))next.issues=event.issues;
 if(Object.hasOwn(event,'handle'))next.handle=typeof event.handle==='string'?event.handle:null;
 if(Object.hasOwn(event,'doing')||event.titled)next.statusAt=event.at;
 return next;
 });if(!result.written&&result.reason!=='no change')throw Error('session writer busy or external edit');return result.value;
}
export function saveTurn(base,id,account,tally){
 return saveTurns(base,id,account,[tally]);
}
export function saveTurns(base,id,account,tallies,options={}){
 validateId(id);if(!/^codex:[a-zA-Z0-9_-]+$/.test(account))throw Error('explicit Codex account alias required');
 if(!Array.isArray(tallies)||!tallies.length)throw Error('nonempty turn batch required');
 const tally=tallies[0];
 const date=new Date(tally.startedAt??tally.at).toISOString().slice(0,10), file=safePath(base,'costlog',date,`${id}.json`);
 if(tallies.some(t=>new Date(t.startedAt??t.at).toISOString().slice(0,10)!==date))throw Error('turn batch must share its UTC start date');
 return atomicUpdate(file,id,old=>{
 if(old&&(old.account!==account||!Array.isArray(old.events)))throw Error('costlog account/schema mismatch');
 const data=old??{sessionId:id,name:`Codex ${id.slice(0,8)}`,account,events:[]};
 const indexes=new Map(data.events.map((x,i)=>[x.kind==='turn'?(x.key??x.turn_id):null,i]));let changed=false;
 for(const tally of tallies){
 const event={kind:'turn',at:tally.at,key:tally.key??tally.turn_id??`at:${tally.at}`,startedAt:tally.startedAt??tally.at,turn_id:tally.turn_id??null,prompt:'',steps:tally.requests,avgInput:tally.requests?tally.input/tally.requests:null,costUsd:null,estimatedCostUsd:tally.estimatedCostUsd??null,coverage:tally.coverage,knownCostUsd:tally.knownCostUsd??null,requests:tally.requests,totalTokens:tally.total,inputTokens:tally.input,cachedInputTokens:tally.read,outputTokens:tally.out,tokenSource:'Codex token_count',cacheBreaks:0,topTool:'',subagentSteps:0,durationMs:null};
 const index=indexes.get(event.key)??-1;
 const quota=tally.quotaChange??(index>=0?data.events[index].quotaChange:null);if(quota?.scope==='account'&&quota.source==='Codex account/rateLimits/read')event.quotaChange=quota;
 const evidence=tally.providerCost??(index>=0?data.events[index].providerCost:null);
 if(evidence?.kind==='provider-estimate-delta'&&evidence.turnId===tally.turn_id&&Number.isSafeInteger(evidence.beforeUsdMicros)&&Number.isSafeInteger(evidence.afterUsdMicros)&&evidence.beforeUsdMicros>=0&&evidence.afterUsdMicros>=evidence.beforeUsdMicros){event.costUsd=(evidence.afterUsdMicros-evidence.beforeUsdMicros)/1e6;event.costSource=evidence.kind;event.providerCost=evidence;event.estimatedCostUsd=event.costUsd;}
 if(index>=0){if(data.events[index].at>event.at)continue;data.events[index]=event;}else {indexes.set(event.key,data.events.length);data.events.push(event);}changed=true;
 }
 return changed?data:null;
 },options);
}
export function saveLimits(base,account,ob,freshRequest){
 if(!freshRequest)return {written:false,reason:'idle read only'};
 if(!/^codex:[a-zA-Z0-9_-]+$/.test(account))throw Error('explicit Codex account alias required');
 if(!Number.isFinite(ob.observedAt))return {written:false,reason:'missing sample time'};
 const next=[];
 for(const l of [ob.primary,ob.secondary]){if(!l)continue;const kind=l.window_minutes===300?'five_hour':l.window_minutes===10080?'seven_day':null;
 if(!kind||!Number.isFinite(l.used_percent)||l.used_percent<0||l.used_percent>100||!Number.isFinite(l.resets_at))continue;
 next.push({kind,at:ob.observedAt,pct:l.used_percent,reset:new Date(l.resets_at*1000).toISOString()});}
 if(!next.length)return {written:false,reason:'no recognized window'};
 return atomicUpdate(safePath(base,'limits.json'),null,old=>{
 const d=old??{},a=d[account]??{};if(typeof a!=='object'||Array.isArray(a)||a===null)throw Error('invalid account samples');let changed=false;
 for(const s of next){const list=a[s.kind]??[];if(!Array.isArray(list))throw Error('invalid samples');const latest=list.at(-1);if(latest&&latest.at>=s.at)continue;
 a[s.kind]=[...list.filter(x=>x.reset===s.reset&&x.at>=s.at-(s.kind==='five_hour'?18000000:86400000)),{at:s.at,pct:s.pct,reset:s.reset}].slice(-400);changed=true;}
 if(!changed)return null;d[account]=a;return d;
 });
}
export function saveUnits(base,id,codex){validateId(id);return atomicUpdate(safePath(base,'units',`${id}.json`),id,old=>{
 if(old?.codex?.account&&old.codex.account!==codex.account)throw Error('units account mismatch');
 const next={...codex};if(old?.codex?.provider&&(!next.provider||old.codex.provider.at>=next.provider.at))next.provider=old.codex.provider;
 return {...(old??{sessionId:id,units:[]}),codex:next};
});}
export function saveProvider(base,id,account,ob){
 validateId(id);if(!/^codex:[a-zA-Z0-9_-]+$/.test(account))throw Error('explicit Codex account alias required');
 if(!ob||ob.threadId!==id||ob.kind!=='provider-estimate'||!Number.isFinite(ob.at)||ob.at<0||!['available','unavailable'].includes(ob.status))throw Error('invalid provider observation');
 const validMicros=n=>Number.isSafeInteger(n)&&n>=0;
 if(ob.status==='available'&&!validMicros(ob.usdMicros))throw Error('invalid provider USD');
 const fields=['model','reasoningEffort','speed','inputTokens','cachedInputTokens','netNewInputTokens','outputTokens','totalTokens','estimatedUsageCreditsMicros'];
 const groups=Array.isArray(ob.groups)?ob.groups.filter(x=>x&&typeof x==='object'&&!Array.isArray(x)).map(x=>Object.fromEntries(fields.filter(k=>['model','reasoningEffort','speed'].includes(k)?typeof x[k]==='string':validMicros(x[k])).map(k=>[k,x[k]]))):[];
 const sample={threadId:id,at:ob.at,kind:'provider-estimate',status:ob.status,usdMicros:ob.status==='available'?ob.usdMicros:null,sessionUsd:ob.status==='available'?ob.usdMicros/1e6:null,turnUsd:null,creditsMicros:validMicros(ob.creditsMicros)?ob.creditsMicros:null,groups,reason:ob.status==='available'?null:'provider USD unavailable'};
 const reasons=['no thread billing route','USD not provided','thread mismatch','RPC timeout','RPC usage unavailable','RPC initialize refused','RPC WebSocket upgrade refused','RPC launch unavailable','RPC closed before response'];
 if(sample.status==='unavailable'&&reasons.includes(ob.reason))sample.reason=ob.reason;
 if(['received','unavailable','not-requested'].includes(ob.quotaStatus))sample.quotaStatus=ob.quotaStatus;
 if(ob.rateLimits&&Number.isFinite(ob.rateLimits.observedAt)){
  const window=x=>x&&Number.isFinite(x.used_percent)&&x.used_percent>=0&&x.used_percent<=100&&Number.isSafeInteger(x.window_minutes)&&x.window_minutes>0&&Number.isFinite(x.resets_at)?{used_percent:x.used_percent,window_minutes:x.window_minutes,resets_at:x.resets_at}:null;
  sample.rateLimits={observedAt:ob.rateLimits.observedAt,primary:window(ob.rateLimits.primary),secondary:window(ob.rateLimits.secondary)};
 }
 return atomicUpdate(safePath(base,'units',`${id}.json`),id,old=>{
  if(!old?.codex||old.codex.account!==account)throw Error('provider account/schema mismatch');
  if(old.codex.provider?.at>=sample.at)return null;
  return {...old,codex:{...old.codex,provider:sample}};
 });
}
