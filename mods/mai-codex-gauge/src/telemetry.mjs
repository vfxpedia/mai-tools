// Tokens come from Codex token_count records. Cache is a subset of input, not an extra charge.
const count=n=>Number.isSafeInteger(n)&&n>=0;
export function tallyTokens(t){
 if(!t||![t.input,t.read,t.out].every(count)||t.read>t.input)return null;
 return {input:t.input,cache:t.read,output:t.out,total:t.input+t.out};
}
export function sessionTokens(state){
 const total={input:0,cache:0,output:0,total:0};let partial=false;
 for(const t of Object.values(state?.turns??{})){const tokens=tallyTokens(t);if(!tokens){partial=true;continue;}for(const key of Object.keys(total))total[key]+=tokens[key];}
 if(!Object.values(total).every(count))return {tokens:null,coverage:'partial'};
 return {tokens:total,coverage:partial||state?.coverage==='partial'||state?.historyComplete!==true?'partial':'complete'};
}
