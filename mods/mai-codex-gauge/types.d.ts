export type Coverage = 'complete' | 'partial';
export interface SessionFile { id: string; name: string; titled?: boolean; handle: string|null; cwd: string; repo: string|null; doing: string; issues: string[]; waiting: string; next: string; contextPercent: number|null; startedAt: number; updatedAt: number; statusAt: number|null; endedAt?: number; outside?: number }
export interface Usage { input_tokens:number; cached_input_tokens?:number; cache_write_input_tokens?:number; output_tokens:number; reasoning_output_tokens?:number; total_tokens?:number }
export interface Piece { t:string; tone?:string; dim?:boolean; bold?:boolean; fill?:boolean }
export interface CostEvent { kind:'turn'|'compact'; at:number; turn_id?:string; costUsd:number|null; costSource?:'provider-estimate-delta'; estimatedCostUsd:number|null; coverage:Coverage; account?:string; source?:string; [key:string]:unknown }
export interface Cursor { offset:number; inode:string; prefixHash:string; prefixLength:number }
// Codex-only nested observation. The shared Claude required fields are unchanged.
export interface ProviderUsage { threadId:string; at:number; kind:'provider-estimate'; status:'available'|'unavailable'; usdMicros:number|null; sessionUsd:number|null; turnUsd:number|null; creditsMicros:number|null; groups:Record<string,string|number>[]; reason:string|null; quotaStatus?:'received'|'unavailable'|'not-requested'; rateLimits?:{observedAt:number;primary:unknown;secondary:unknown} }
export interface ProviderTurnDelta { turnUsd:number|null; kind?:'provider-estimate-delta'; turnId?:string; reason:string|null }
export interface TokenTotals { input:number; cache:number; output:number; total:number }
export interface QuotaChange { scope:'account'; source:'Codex account/rateLimits/read'; beforeAt:number|null; afterAt:number|null; windows:{five_hour:{beforePercent:number;afterPercent:number;deltaPercentagePoints:number;resetsAt:number}|null;seven_day:{beforePercent:number;afterPercent:number;deltaPercentagePoints:number;resetsAt:number}|null} }
