import type {ConnectionReport} from './types';
import './connection-guide.css';

type Props={
 source?:string;connected:boolean;symbol:string;report?:ConnectionReport;
 checking:boolean;onCheck:()=>void;onPickSymbol:(symbol:string)=>void;
};

export function ConnectionGuide({source,connected,symbol,report,checking,onCheck,onPickSymbol}:Props){
 const synthetic=source==='synthetic';
 const terminalCheck=report?.checks.find(check=>check.id==='terminal');
 const terminalConnected=report?.connected??(terminalCheck?terminalCheck.status==='pass':connected);
 const quoteCheck=report?.checks.find(check=>check.id==='quote');
 const activity=report?.market_activity?.state??(quoteCheck?(quoteCheck.status==='pass'?'fresh':'stale'):undefined);
 const historyChecks=report?.checks.filter(check=>check.id.startsWith('history_'))??[];
 const historyReady=historyChecks.length>0&&historyChecks.every(check=>check.status==='pass');
 const missingSymbol=report?.checks.some(check=>check.id==='symbol'&&check.status==='fail');
 const summary=report?.ready_for_demo?'Connection prerequisites passed':report?.ready_for_data?'Connected for charts · new entries need attention':report?'Review connection checks':'Connect your Exness demo';
 const groups=[
  {name:'Terminal & account',description:'MT5 login and broker connection',checks:report?.checks.filter(check=>['terminal','account','demo_account'].includes(check.id))??[]},
  {name:'Symbol & historical charts',description:'Exact broker symbol and saved candles',checks:report?.checks.filter(check=>['symbol','symbol_info','market_watch','contract_values'].includes(check.id)||check.id.startsWith('history_'))??[]},
  {name:'New-entry readiness',description:'Fresh quotes, permissions and execution checks',checks:report?.checks.filter(check=>!['terminal','account','demo_account','symbol','symbol_info','market_watch','contract_values'].includes(check.id)&&!check.id.startsWith('history_'))??[]},
 ];
 return <section id="connection-guide" className="connection-guide" aria-labelledby="connection-guide-title">
  <div className="connect-heading"><div><span className="eyebrow">GET CONNECTED</span><h3 id="connection-guide-title">{summary}</h3></div><span className="connect-readonly">READ-ONLY TEST</span></div>
  <p className="connect-weekend">You can connect on Saturday. MT5 login, account details and available historical charts can work while forex trading is paused. The test below sends no orders.</p>
  <div className="connection-stages" aria-label="Connection readiness">
   <div><span className={'stage-light '+(terminalConnected?'good':report||synthetic?'pending':'unknown')}/><div><b>1 · Terminal</b><span>{terminalConnected?'Broker connected':synthetic?'Synthetic preview only':report?'Needs connection':'Not verified yet'}</span></div></div>
   <div><span className={'stage-light '+(historyReady&&report?.ready_for_data?'good':report?'pending':'unknown')}/><div><b>2 · Charts & history</b><span>{historyReady&&report?.ready_for_data?'Historical data available':report?'Review symbol / history checks':'Run the read-only test'}</span></div></div>
   <div><span className={'stage-light '+(report?.ready_for_demo?'good':report?'pending':'unknown')}/><div><b>3 · New entries</b><span>{report?.ready_for_demo?'Connection checks passed':activity==='stale'?'Waiting for fresh market data':report?'Blocked until checks pass':'Not verified yet'}</span></div></div>
  </div>
  {report&&activity!=='fresh'&&<div className="market-pause" role="status"><b>{activity==='stale'?'No fresh quotes; market may be closed':'Fresh quotes are unavailable'}</b><p>{report.market_activity?.notice||'The broker feed may be paused, the market may be closed, or connectivity needs attention. Check the report; stale prices do not prove that MT5 is disconnected.'} Available historical candles can still be viewed. New entries remain blocked.</p></div>}
  <details className="connection-walkthrough" open={!terminalConnected}>
   <summary>Simple setup · teach someone in four steps</summary>
   <ol>
    <li><b>Log in on the Windows PC.</b><span>Open Exness MT5 desktop and sign in to your own MT5 <strong>demo</strong> account. Check MT5’s broker connection indicator. Each person uses their own account; passwords stay in MT5.</span></li>
    <li><b>Connect ForexLab to MT5.</b><span>Keep MT5 open and use the Windows launcher in MT5 analysis mode. Paste its local session token into ForexLab. A synthetic preview is separate from the broker connection.</span></li>
    <li><b>Select the exact instrument and test.</b><span>Use the chart’s broker symbol selector, including any suffix, such as EURUSDm. Run the connection checks below. If history is missing, open that symbol’s D1, H4 and M30 charts in MT5 and let history load.</span></li>
    <li><b>View charts now; test orders when quotes resume.</b><span>Use Charts and Analysis to inspect available history and indicators. When new-entry checks pass, review the economic calendar and explicitly enable demo controls and demo automation. A WAIT signal means no trade.</span></li>
   </ol>
   <p className="connect-account-note">The phone connects to your Windows backend. MT5 and the backend must stay open on that PC. This research/demo version is for your own terminal; it is not a hosted multi-user service.</p>
  </details>
  <button className="primary" disabled={checking} onClick={onCheck}>{checking?'Checking MT5…':'Run MT5 connection checks'}</button>
  <small>No broker password is requested here. This test cannot place an order.</small>
  {report&&<div className="connection-report" aria-live="polite"><p className="connection-checked">Checked {new Date(typeof report.checked_at==='number'?report.checked_at*1000:report.checked_at).toLocaleString()}{symbol?' · '+symbol:''}</p>
   {missingSymbol&&!!report.candidates?.length&&<div className="connection-candidates"><b>Choose an exact broker symbol</b><div>{report.candidates.map(candidate=><button key={candidate} onClick={()=>onPickSymbol(candidate)}>{candidate}</button>)}</div><small>Selection changes the chart instrument. Run the test again for the selected symbol.</small></div>}
   {groups.map(group=>group.checks.length>0&&<details key={group.name} className="connection-group" open={group.checks.some(check=>check.status!=='pass')}><summary><span>{group.name}</span><b>{group.checks.filter(check=>check.status==='pass').length}/{group.checks.length} passed</b></summary><p>{group.description}</p>{group.checks.map(check=><div className={'connection-check '+check.status} key={check.id}><strong><span aria-hidden="true">{check.status==='pass'?'✓':check.status==='fail'?'×':'!'}</span> <span className="sr-only">{check.status}: </span>{check.title}</strong><p>{check.detail}</p>{check.action&&<small>{check.action}</small>}</div>)}</details>)}
   <p className="connect-account-note">Passing connection checks is only a prerequisite. The server still checks strategy, calendar clearance, risk, margin and price freshness before every order.</p>
  </div>}
 </section>;
}
