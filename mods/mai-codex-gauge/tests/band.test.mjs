import test from 'node:test';import assert from 'node:assert/strict';
import {bandRows,renderRows,cells,freshLimits,recentRate,spendRate,pace,growthOf} from '../src/band.mjs';
const m={cp:70,tokens:180880,window:258400,limits:[],turn:null,knownTotal:0,totalComplete:false};
test('four mandatory rows and optional now, 12 cells only on wide screens',()=>{
 for(let cols=40;cols<=200;cols++){const rows=bandRows(m,cols),s=renderRows(rows,cols,false);assert.equal(rows.length,4);assert.ok(s.includes('5 hours'));assert.ok(s.includes('7 days'));for(const line of s.split('\n'))assert.ok(cells(line)<=cols);assert.equal(s.includes('─'),cols>=56);}
 assert.equal(bandRows({...m,current:'hello'},80).length,5);
});
test('context cleanup is not auto compact and legacy local amounts are never displayed',()=>{
 const t={requests:4,estimatedCostUsd:.123,coverage:'complete',breakdown:{read:{tokens:1000,usd:.1},out:{tokens:10,usd:.02},fresh:{tokens:10,usd:.003}}};
 const s=renderRows(bandRows({...m,cp:86,turn:t,knownTotal:10,current:'한글 😀\x1b[31m danger\n'},120),120,false);
 assert.match(s,/cleanup/);assert.doesNotMatch(s,/compact after/);assert.match(s,/API unavailable/);assert.doesNotMatch(s,/API-equiv|~\$|\$0.123/);
 assert.equal(renderRows(bandRows({...m,cp:null},80),80,false).includes('$0'),false);
 assert.equal(cells('한글😀a'),7);assert.equal(cells('e\u0301'),1);assert.equal(cells('👨‍👩‍👧‍👦'),2);
});
test('fresh weekly limits never fabricate five hour and reset drops old slope',()=>{
 const now=Date.UTC(2026,9,9),reset=new Date(now+86400000).toISOString();const samples={seven_day:[{at:now-1800000,pct:5,reset},{at:now,pct:7,reset}]};
 const ls=freshLimits([],samples,now);assert.equal(ls[0].kind,'seven_day');assert.equal(recentRate(samples.seven_day,'other',now,'seven_day'),null);
 assert.equal(spendRate(samples.seven_day,reset,[{at:now,cost:1}],now,'seven_day'),null);
 assert.ok(pace(ls[0],now));assert.equal(growthOf([1,2]),null);assert.equal(growthOf([1,2,4]),1.5);
});
test('narrow turn row keeps provider provenance instead of local cost',()=>{
 const turn={requests:44,estimatedCostUsd:2.309,coverage:'complete',breakdown:{}};
 for(const cols of [40,47,48,55,56,80,120]){const line=renderRows(bandRows({...m,turn,knownTotal:15.993,totalComplete:true},cols),cols,false).split('\n')[3];assert.match(line,/API unavailable/);assert.doesNotMatch(line,/15.993|2.309/);assert.ok(cells(line)<=cols);}
});
test('provider estimate and token breakdown keep whole amounts at mobile widths',()=>{
 const model={...m,turn:{requests:3,read:5000,out:20,input:5100,write:0},provider:{kind:'provider-estimate',status:'available',sessionUsd:12.345,turnUsd:.125}};
 for(let cols=40;cols<=200;cols++){const s=renderRows(bandRows(model,cols),cols,false),line=s.split('\n')[3];assert.match(line,/\$0.125/);assert.match(line,/\[\$12.35\]/);assert.match(line,/API est/);assert.doesNotMatch(line,/~\$|API-equiv/);for(const l of s.split('\n'))assert.ok(cells(l)<=cols);}
});
test('thin 12-cell bar and colored verdicts match Claude style, without empty reset brackets',()=>{
 const model={...m,limits:[{name:'5 hours',pct:20,pace:{projected:40,fullAt:null},reset:'2h15m'}]};
 const rows=bandRows(model,120),s=renderRows(rows,120,false);assert.match(s.split('\n')[1],/━{2}╍{3}─{7}/);assert.doesNotMatch(s,/[█░▒]/);assert.match(s,/enough \(2h15m\)/);
 assert.ok(rows[1].some(p=>p.tone==='success'));assert.match(renderRows(rows,120,true),/\x1b\[38;2;51;153;255m/);
 assert.doesNotMatch(renderRows(bandRows({...model,limits:[{name:'5 hours',pct:20,reset:''}]},120),120,false),/\(\)/);
});
test('large API amounts keep their whole digits and closing bracket at every supported width',()=>{
 const model={...m,provider:{kind:'provider-estimate',status:'available',sessionUsd:Number.MAX_SAFE_INTEGER/1e6,turnUsd:1234567.89}};
 for(let cols=40;cols<=200;cols++){
  const line=renderRows(bandRows(model,cols),cols,false).split('\n')[3];
  assert.match(line,/\$1234567.89/);assert.match(line,/\[\$9007199254.74\]/);assert.ok(cells(line)<=cols);
 }
});
test('colored display distinguishes used, forecast, free and threshold instead of coloring the entire bar',()=>{
 const rows=bandRows({...m,cp:20,limits:[{name:'5 hours',pct:20,pace:{projected:40,fullAt:null},reset:'2h15m'}],outside:2,current:'Build gauge',job:'Waiting'},120);
 const lines=renderRows(rows,120,true).split('\n');
 // Literal colors are the Claude screenshot's dark daltonized theme, not terminal ANSI green.
 assert.match(lines[1],/\x1b\[38;2;51;153;255m━━\x1b\[0m/);
 assert.match(lines[1],/\x1b\[2;38;2;51;153;255m╍╍╍\x1b\[0m/);
 assert.match(lines[1],/\x1b\[2;38;2;153;153;153m───────\x1b\[0m/);
 assert.match(lines[0],/\x1b\[38;2;255;255;255m┃\x1b\[0m/);
 assert.match(lines[0],/\x1b\[38;2;255;255;255m● cleanup at 85%/);
 assert.match(lines[4],/\x1b\[38;2;255;204;0m▲ outside repo 2/);
 assert.match(lines[4],/\x1b\[38;2;153;204;255m · Build gauge/);
 assert.doesNotMatch(lines.join('\n'),/\x1b\[32m/);
 for(const [pct,rgb] of [[70,'255;204;0'],[90,'255;102;102']])assert.ok(renderRows(bandRows({...m,cp:pct},120),120,true).includes(`38;2;${rgb}m`));
});
