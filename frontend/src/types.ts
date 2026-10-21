export type Candle = {time:number;open:number;high:number;low:number;close:number;volume:number};
export type Zone = {kind:string;direction:string;lower:number;upper:number;time:number};
export type Analysis = {trend:string;event:string;support:number|null;resistance:number|null;atr:number;zones:Zone[];sweeps:string[]};
export type Signal = {side:string;entry?:number;stop?:number;target?:number;reasons:string[];analysis:Record<string,Analysis>};
export type Position = {ticket:number;symbol:string;volume:number;profit:number};
export type NewsClearance = {symbol?:string;mode:string;allowed:boolean;reason:string;expires_at?:number;provider?:string;buffer_minutes?:number};
export type Status = {
  source:string;mode:string;automation_enabled:boolean;automation_symbol?:string;
  emergency:boolean;demo_execution_enabled:boolean;news_clear_until:number;timeframes:string[];
  account:{connected?:boolean;equity:number;balance?:number;margin_free?:number;currency:string;demo:boolean;server?:string;positions:Position[];pending_orders?:number};
  limits:Record<string,number>;
  news_clearance?:NewsClearance;
};
export type Drawing = {tool:string;points:{time:number;price:number}[]};
export type JournalEvent = {id:number;time:string;kind:string;payload:unknown};
export type ConnectionReport = {
  checked_at:string|number;requested_symbol?:string;resolved_symbol?:string|null;
  connected?:boolean;candidates?:string[];
  ready_for_data:boolean;ready_for_demo:boolean;
  market_activity?:{state:'fresh'|'stale'|'unavailable';quote_age_seconds?:number|null;notice:string};
  checks:{id:string;status:string;title:string;detail:string;action?:string}[];
};

export type ApiClient = <T>(path:string,body?:unknown)=>Promise<T>;
export type DatasetMetadata = {id:string;name:string;bar_count:number;source:string;symbol?:string;valid:boolean;eligible:boolean;issues?:unknown[];warnings?:unknown[];sha256?:string;[key:string]:unknown};
export type ResearchJob = {job_id?:string;status:'queued'|'running'|'completed'|'failed';report_id?:string;error?:string};
export type ResearchReportIndex = {id:string;created_at:string|number;source?:string;symbol?:string;kind?:string;summary?:unknown};
export type ReconciliationResponse = {orders?:{signal_id:string;status:string;payload:unknown;request?:unknown;metadata?:unknown;response?:unknown}[];checked_at?:string|number;account?:unknown;resolved?:unknown[];pending?:unknown[];errors?:unknown[];risk_alerts?:unknown[];ledger?:unknown;other_account_submission_blocked?:boolean};
