export type Candle = {time:number;open:number;high:number;low:number;close:number;volume:number};
export type Zone = {kind:string;direction:string;lower:number;upper:number;time:number};
export type Analysis = {trend:string;event:string;support:number|null;resistance:number|null;atr:number;zones:Zone[];sweeps:string[]};
export type Signal = {side:string;entry?:number;stop?:number;target?:number;reasons:string[];analysis:Record<string,Analysis>};
export type Position = {ticket:number;symbol:string;volume:number;profit:number};
export type Status = {
  source:string;mode:string;automation_enabled:boolean;automation_symbol?:string;
  emergency:boolean;demo_execution_enabled:boolean;news_clear_until:number;timeframes:string[];
  account:{connected?:boolean;equity:number;balance?:number;margin_free?:number;currency:string;demo:boolean;server?:string;positions:Position[];pending_orders?:number};
  limits:Record<string,number>;
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
