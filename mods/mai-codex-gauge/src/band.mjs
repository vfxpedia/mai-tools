// Layout and piece semantics adapted from mai-gauge, commit ce92211 (1.5.0).
// Codex differences: provider USD only, absent windows, model-window cleanup recommendation.
export const SOURCE_PIN='ce92211';
// Matches the supplied Claude screenshot's dark daltonized theme. Not an automatic theme detector.
const colors={success:'38;2;51;153;255',warning:'38;2;255;204;0',error:'38;2;255;102;102',inactive:'38;2;153;153;153',suggestion:'38;2;153;204;255',text:'38;2;255;255;255'};
export const clean=s=>String(s??'').replace(/\x1b\][\s\S]*?(?:\x07|\x1b\\)/g,'').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'').replace(/[\x00-\x1f\x7f-\x9f]/g,' ');
const segments=s=>[...new Intl.Segmenter('en',{granularity:'grapheme'}).segment(clean(s))].map(x=>x.segment);
const size=s=>/\p{Extended_Pictographic}/u.test(s)?2:[...s].reduce((n,c)=>n+(/\p{Mark}/u.test(c)||c==='\u200d'?0:/[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\uff00-\uff60]/u.test(c)?2:1),0);
export const cells=s=>segments(s).reduce((n,x)=>n+size(x),0);
export function fit(s,w){let out='',n=0;for(const c of segments(s)){const v=size(c);if(n+v>w)break;out+=c;n+=v;}return out;}
const pad=(s,n,right=false)=>{s=fit(s,n);return right?' '.repeat(Math.max(0,n-cells(s)))+s:s+' '.repeat(Math.max(0,n-cells(s)));};
const compact=n=>n>=1e6?`${(n/1e6).toFixed(1)}M`:n>=1e3?`${(n/1e3).toFixed(1)}k`:`${n}`;
const usd=n=>Number.isFinite(n)&&n>=0?`$${n>=10?n.toFixed(2):n>0&&n<.001?n.toFixed(6):n.toFixed(3)}`:'-';
const span={five_hour:18000000,seven_day:604800000};
const sameSource=s=>{s=[...s].sort((a,b)=>a.at-b.at);let start=0;for(let i=1;i<s.length;i++)if(s[i].pct<s[i-1].pct)start=i;return s.slice(start);};
export function freshLimits(own,samples,now){const out=[];for(const kind of new Set([...own.map(x=>x.kind),...Object.keys(samples)])){const m=own.find(x=>x.kind===kind),last=(samples[kind]??[]).filter(x=>Number.isFinite(x.pct)&&x.pct>=0&&x.pct<=100&&Date.parse(x.reset)>now&&x.at<=now).sort((a,b)=>Date.parse(b.reset)-Date.parse(a.reset)||b.pct-a.pct)[0];if(last)out.push({kind,percentUsed:(!m||Date.parse(m.resetsAt)<=Date.parse(last.reset)+60000)?Math.max(last.pct,Date.parse(m?.resetsAt)===Date.parse(last.reset)?m.percentUsed:0):m.percentUsed,resetsAt:last.reset});else if(m&&Date.parse(m.resetsAt)>now)out.push(m);}return out;}
export function recentRate(samples,reset,now,kind='five_hour'){const window=kind==='seven_day'?21600000:1800000,s=sameSource(samples.filter(x=>x.reset===reset&&x.at>=now-window&&x.at<=now));if(s.length<2||s.at(-1).at-s[0].at<window/6)return null;return Math.max(0,(s.at(-1).pct-s[0].pct)/Math.max(s.at(-1).at-s[0].at,window/2));}
export function spendRate(samples,reset,events,now,kind='five_hour'){const s=sameSource(samples.filter(x=>x.reset===reset&&x.at<=now));if(s.length<2||s.at(-1).pct-s[0].pct<3)return null;const sum=(a,b)=>events.filter(x=>x.at>a&&x.at<=b&&Number.isFinite(x.cost)).reduce((n,x)=>n+x.cost,0),spent=sum(s[0].at,s.at(-1).at);if(spent<=0)return null;const w=kind==='seven_day'?10800000:900000;return (s.at(-1).pct-s[0].pct)/spent*sum(now-w,now)/w;}
export function pace(l,now,recent=null){const len=span[l.kind],reset=Date.parse(l.resetsAt);if(!len||!Number.isFinite(reset)||reset<=now)return null;let rate=recent,basis='recent';if(rate===null){const elapsed=now-(reset-len);if(elapsed<len*.1||l.percentUsed<=0)return null;rate=l.percentUsed/elapsed;basis='window';}const full=rate>0?now+(100-l.percentUsed)/rate:null;return {projected:Math.round(l.percentUsed+rate*(reset-now)),fullAt:l.percentUsed>=100?now:full&&full<reset?full:null,basis};}
export function growthOf(s){const rises=s.slice(1).map((x,i)=>x-s[i]).filter(x=>x>0);return rises.length<2?null:rises.reduce((a,x)=>a+x,0)/rises.length;}
function barPieces(pct,mark,ahead,tone){const pieces=[];for(let i=0;i<12;i++){
 const p=mark!==null&&i===Math.min(11,Math.round(mark*12/100))?{t:'┃',tone:'text'}:pct!==null&&i<Math.round(pct*12/100)?{t:'━',tone}:ahead!==null&&i<Math.round(Math.min(100,ahead)*12/100)?{t:'╍',tone,dim:true}:{t:'─',tone:'inactive',dim:true};
 const last=pieces.at(-1);if(last&&last.t.at(-1)===p.t&&last.tone===p.tone&&last.dim===p.dim)last.t+=p.t;else pieces.push(p);
 }return pieces;}
export function bandRows(m,cols){
 const wide=cols>=56,NUM=cols>=48?16:5,rows=[];
 const row=(label,pct,mid,say,mark=null,ahead=null,tone='inactive',sayTone=tone)=>{const r=[{t:pad(label,9),dim:true}];if(wide)r.push(...barPieces(pct,mark,ahead,tone),{t:' '});r.push({t:pad(pct===null?'-':`${pct}%`,4,true),bold:true,tone},{t:' '});if(NUM>5)r.push({t:pad(mid,NUM-5),dim:true});r.push({t:say,fill:true,tone:sayTone});rows.push(r);};
 const short=n=>n>=1000?`${Math.round(n/1000)}k`:`${n}`;
 row('context',m.cp??null,m.tokens==null?'':`${short(m.tokens)}/${short(m.window)}`,m.cp==null?'… no reply yet':m.cp>=85?'▲ cleanup recommended':'● cleanup at 85%',85,null,m.cp==null?'inactive':m.cp>=85?'error':m.cp>=50?'warning':'success',m.cp==null?'inactive':m.cp>=85?'warning':'text');
 for(const name of ['5 hours','7 days']){const l=(m.limits??[]).find(x=>x.name===name);if(!l){row(name,null,'',m.quotaMissing?.[name]==='not provided'?'… not provided':'… no data yet');continue;}const p=l.pace,word=l.pct>=100?'✕ out':!p?'… measuring':p.fullAt?'✕ short':p.projected>=85?'▲ tight':'● enough',tone=l.pct>=100||p?.fullAt?'error':!p?'inactive':p.projected>=85?'warning':'success';row(name,l.pct,p?(p.projected>200?'[>200%]':`[~${p.projected}%]`):'',word+(l.reset?` (${l.reset})`:''),null,p?.projected,tone);}
 const t=m.turn,p=m.provider,hasApi=p?.kind==='provider-estimate'&&p.status==='available'&&Number.isFinite(p.sessionUsd)&&p.sessionUsd>=0;
 if(m.tokenTotals){
  const triplet=x=>x?[x.input,x.cache??x.read,x.output??x.out].map(n=>compact(n)).join('/'):'-';
  const pieces=[{t:pad('turn',9),dim:true},{t:`T ${triplet(t)} · S ${triplet(m.tokenTotals)}`,bold:true}];
  const q=m.quotaChange?.scope==='account'?Object.entries(m.quotaChange.windows??{}).filter(([,v])=>v!==null).map(([k,v])=>`${k==='seven_day'?'7d':'5h'}+${v.deltaPercentagePoints}pp`).join(' '):'';
  const missing=['no thread billing route','USD not provided'].includes(p?.reason)?'USD not provided':'API unavailable';
  const extra=[q?`account ${q}`:'',hasApi?`API est · engine est ${usd(p.turnUsd)} [${usd(p.sessionUsd)}]`:missing];
  let used=pieces.reduce((n,p)=>n+cells(p.t),0);for(const text of extra.filter(Boolean)){const v=` · ${text}`;if(used+cells(v)<=cols){pieces.push({t:v,dim:true});used+=cells(v);}}
  rows.push(pieces);
 }else{
 const amount=hasApi?usd(p.turnUsd):'-',total=hasApi?`[${usd(p.sessionUsd)}]`:'';
 let amountWidth=wide?Math.max(13,cells(amount)):cells(amount)+1,totalWidth=NUM>5?Math.max(NUM-5,cells(total)):cells(total)+1,gap=wide?5:0;
 // Money is never cut to a fixed field width. Remove padding before narrative.
 let excess=Math.max(0,9+amountWidth+gap+totalWidth-cols),take=Math.min(excess,gap);gap-=take;excess-=take;
 take=Math.min(excess,amountWidth-cells(amount));amountWidth-=take;excess-=take;
 take=Math.min(excess,totalWidth-cells(total));totalWidth-=take;
 const r=[{t:pad('turn',9),dim:true},{t:pad(amount,amountWidth),bold:true},{t:' '.repeat(gap)}];r.push({t:pad(total,totalWidth),dim:true});const used=r.reduce((n,p)=>n+cells(p.t),0);
 let say=hasApi?'● API est':['no thread billing route','USD not provided'].includes(p?.reason)?'… USD not provided':'… API unavailable';
 if(t){const parts=[['reads',t.read],['out',t.out],['new',Math.max(0,(t.input??0)-(t.read??0))]].filter(([,n])=>n>0).sort((a,b)=>b[1]-a[1]).map(([k,n])=>`${k} ${compact(n)}`);const req=`${t.requests} req`;for(let n=parts.length;n>=-1;n--){const cand=say+(n>=0?' · '+req:'')+(n>0?' · '+parts.slice(0,n).join(' · '):'');if(used+cells(cand)<=cols){say=cand;break;}}}
 r.push({t:say,fill:true});rows.push(r);
 }
 const alerts=[];const alert=(t,style)=>{if(t)alerts.push({t:`${alerts.length?' · ':''}${t}`,...style,fill:true});};
 alert(m.outside?`▲ outside repo ${m.outside}`:'',{tone:'warning'});alert(m.diagnostic?`▲ ${m.diagnostic}`:'',{tone:'warning'});alert(m.current,{tone:'suggestion'});alert(m.job,{dim:true});
 if(alerts.length)rows.push([{t:pad('now',9),dim:true},...alerts]);return rows;
}
export function renderRows(rows,cols,color=false){return rows.map(r=>{let used=0,out='';for(const p of r){const t=fit(p.t,Math.max(0,cols-used));used+=cells(t);if(color&&t){const codes=[p.bold?1:null,p.dim?2:null,colors[p.tone??(p.dim?'inactive':'text')]??colors.text].filter(x=>x!==null);out+=`\x1b[${codes.join(';')}m${t}\x1b[0m`;}else out+=t;}return out;}).join('\n');}
