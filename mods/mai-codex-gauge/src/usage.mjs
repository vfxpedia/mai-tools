import fs from 'node:fs';
import crypto from 'node:crypto';
const n=v=>Number.isSafeInteger(v)&&v>=0;
export function newState(id) {return {id,model:null,turnId:null,tier:'standard',region:'default',watermark:null,lastOffset:-1,epoch:0,requests:0,estimatedCostUsd:null,knownCostUsd:null,coverage:'complete',gapTokens:0,inheritedTokens:0,turns:{},last:null,rate:null,freshRequest:false,historyComplete:false,sourceCreatedAt:null,fork:false};}
export function reduceRecord(state,record,byteOffset,{mutate=false}={}) {
 // Public callers retain immutable reduction. The observer owns the parsed
 // state inside its exclusive transaction and must not clone its whole history
 // once per JSONL row.
 const s=mutate?state:structuredClone(state); s.freshRequest=false;
 if(byteOffset<=s.lastOffset)return s; s.lastOffset=byteOffset;
 const p=record.payload??{}, at=Date.parse(record.timestamp); const type=record.type;
 if(type==='session_meta') {if(p.id!==s.id){s.foreign=true;return s;} s.foreign=false; s.fork=!!(p.forked_from_id||p.forked_from); s.sourceCreatedAt=Number.isFinite(at)?at:null; return s;}
 if(s.foreign||s.fork&&s.sourceCreatedAt!==null&&Number.isFinite(at)&&at<s.sourceCreatedAt)return s;
 if(type==='turn_context') {s.model=p.model??null; s.turnId=p.turn_id??null; s.tier=p.service_tier??'standard';s.region=p.region??'default';return s;}
 if(type==='event_msg'&&p.type==='task_started') {s.turnId=p.turn_id??s.turnId; return s;}
 if(type!=='event_msg'||p.type!=='token_count')return s;
 if(p.rate_limits)s.rate={...p.rate_limits,observedAt:Number.isFinite(at)?at:null};
 const info=p.info,u=info?.last_token_usage,total=info?.total_token_usage?.total_tokens;
 if(!u||!n(total)||!n(u.input_tokens)||!n(u.output_tokens))return s;
 if(total===s.watermark)return s;
 const tokens=u.input_tokens+u.output_tokens;
 if(s.watermark!==null&&total<s.watermark)s.epoch++;
 const delta=s.watermark===null||total<s.watermark?total:total-s.watermark;
 if(delta<tokens){s.coverage='partial';s.diagnostic='cumulative delta smaller than request';s.watermark=total;return s;}
 if(delta>tokens){if(s.fork&&s.watermark===null)s.inheritedTokens+=delta-tokens;else{s.gapTokens+=delta-tokens;s.coverage='partial';}}
 s.watermark=total;
 s.requests++;s.freshRequest=true;
 s.knownCostUsd=null;s.estimatedCostUsd=null;
 const key=s.turnId??`request:${s.epoch}:${total}`, t=s.turns[key]??{key,turn_id:s.turnId,startedAt:Number.isFinite(at)?at:0,requests:0,input:0,read:0,write:0,out:0,total:0,knownCostUsd:null,estimatedCostUsd:null,coverage:'complete',models:[],at:Number.isFinite(at)?at:0};
 t.requests++;t.input+=u.input_tokens;t.read+=u.cached_input_tokens??0;t.write+=u.cache_write_input_tokens??0;t.out+=u.output_tokens;t.total+=tokens;t.at=Number.isFinite(at)?at:t.at;
 t.knownCostUsd=null;t.estimatedCostUsd=null;
 if(!t.models.includes(s.model))t.models.push(s.model);
 s.turns[key]=t;s.last={usage:u,model:s.model,turnId:s.turnId,at:Number.isFinite(at)?at:null,offset:byteOffset,window:info.model_context_window??null};
 return s;
}
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
export function readIncrement(file,cursor=null,maxBytes=1024*1024,deadlineMs=500,{onRecord=null,maxRecords=Infinity}={}) {
 if(!Number.isSafeInteger(maxBytes)||maxBytes<1||maxBytes>16*1024*1024)throw new Error('invalid read budget');
 const began=performance.now(),fd=fs.openSync(file,'r');
 try {
 const st=fs.fstatSync(fd), inode=`${st.dev}:${st.ino}`,prefixLength=cursor?.prefixLength??Math.min(st.size,256),prefix=Buffer.alloc(prefixLength);fs.readSync(fd,prefix,0,prefixLength,0);
 const prefixHash=hash(prefix);
 if(cursor&&(cursor.inode!==inode||st.size<cursor.offset||cursor.prefixHash!==prefixHash))return {records:[],cursor,incomplete:true,changed:true};
 const start=cursor?.offset??0,buf=Buffer.alloc(Math.min(maxBytes,st.size-start));fs.readSync(fd,buf,0,buf.length,start);
 const records=[];let offset=0,count=0,skipNonMetric=cursor?.skipNonMetric??false;
 while(count<maxRecords&&performance.now()-began<deadlineMs){const end=buf.indexOf(10,offset);
 if(skipNonMetric){if(end<0){offset=buf.length;break;}offset=end+1;skipNonMetric=false;continue;}
 if(end<0){const prefix=buf.subarray(offset,Math.min(buf.length,offset+512)).toString('utf8');
 // Oversized image/tool/message rows are not accounting events. Stream past them
 // without copying their private content into the cursor or altering the original.
 if(buf.length===maxBytes&&(/"type"\s*:\s*"(?:response_item|compacted)"/.test(prefix)||/"type"\s*:\s*"event_msg"[\s\S]*"payload"\s*:\s*\{\s*"type"\s*:\s*"(?:agent_message|agent_reasoning|user_message|item_completed|item_started)"/.test(prefix))){skipNonMetric=true;offset=buf.length;}break;}
 const line=buf.subarray(offset,end).toString('utf8').replace(/\r$/,'');
 let record;try {if(line)record=JSON.parse(line);}catch {throw new Error(`invalid JSONL at byte ${start+offset}`);}
 if(record){if(onRecord)onRecord(record,start+offset);else records.push({record,byteOffset:start+offset});count++;}
 offset=end+1;
 }
 return {records,count,cursor:{offset:start+offset,inode,prefixLength,prefixHash,skipNonMetric},incomplete:start+offset<st.size||skipNonMetric,changed:false};
 }finally{fs.closeSync(fd);}
}
