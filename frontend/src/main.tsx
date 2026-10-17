import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {createChart, ColorType, IChartApi, ISeriesApi, Time, UTCTimestamp, LineStyle} from 'lightweight-charts';
import './style.css';
import {Rectangle} from './rectangle';

type Candle={time:number;open:number;high:number;low:number;close:number;volume:number};
type Zone={kind:string;direction:string;lower:number;upper:number;time:number};
type Analysis={trend:string;event:string;support:number|null;resistance:number|null;atr:number;zones:Zone[];sweeps:string[]};
type Signal={side:string;entry?:number;stop?:number;target?:number;reasons:string[];analysis:Record<string,Analysis>};
type Status={source:string;mode:string;automation_enabled:boolean;emergency:boolean;demo_execution_enabled:boolean;news_clear_until:number;timeframes:string[];account:{equity:number;currency:string;demo:boolean;positions:{ticket:number;symbol:string;volume:number;profit:number}[]};limits:Record<string,number>};
type Drawing={tool:string;points:{time:number;price:number}[]};

function App(){
 const [token,setToken]=useState(''); const [activeToken,setActiveToken]=useState('');
 const [status,setStatus]=useState<Status>(); const [symbols,setSymbols]=useState<string[]>(['EURUSD']);
 const [symbol,setSymbol]=useState('EURUSD'),[tf,setTf]=useState('M30');
 const [data,setData]=useState<Candle[]>([]),[snapshot,setSnapshot]=useState<Analysis>();
 const [signal,setSignal]=useState<Signal>(); const [error,setError]=useState(''),[notice,setNotice]=useState('');
 const [busy,setBusy]=useState(false),[refresh,setRefresh]=useState(0);
 const [tool,setTool]=useState('cursor'),[drawings,setDrawings]=useState<Drawing[]>([]);
 const [ema,setEma]=useState(true),[period,setPeriod]=useState(20),[zones,setZones]=useState(true);
 const [sma,setSma]=useState(false),[bands,setBands]=useState(false);
 const [events,setEvents]=useState<{id:number;time:string;kind:string;payload:unknown}[]>([]);
 const host=useRef<HTMLDivElement>(null),chart=useRef<IChartApi|undefined>(undefined),series=useRef<ISeriesApi<'Candlestick'>|undefined>(undefined);
 const [chartReady,setChartReady]=useState(0);
 const drawRef=useRef<{tool:string;symbol:string;tf:string;points:Drawing['points']} >({tool:'cursor',symbol,tf,points:[]});
 async function api<T>(path:string,body?:unknown):Promise<T>{
  const r=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+activeToken,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  if(!r.ok){let message='Request failed ('+r.status+')';try{message=JSON.stringify((await r.json()).detail)}catch{}throw new Error(message)}
  return r.json();
 }
 useEffect(()=>{if(!activeToken)return;let live=true;setBusy(true);setError('');
  Promise.all([api<Status>('status'),api<string[]>('symbols'),api<{candles:Candle[];analysis:Analysis}>('candles?symbol='+encodeURIComponent(symbol)+'&tf='+tf),api<Signal>('analysis?symbol='+encodeURIComponent(symbol)),api<typeof events>('events')])
   .then(([s,sy,c,a,e])=>{if(live){setStatus(s);setSymbols(sy);setData(c.candles);setSnapshot(c.analysis);setSignal(a);setEvents(e)}})
   .catch(e=>{if(live){setError(String(e));setData([]);setSignal(undefined);setSnapshot(undefined)}}).finally(()=>{if(live)setBusy(false)});
  return()=>{live=false};
 },[activeToken,symbol,tf,refresh]);
 useEffect(()=>{if(!activeToken)return; const id=setInterval(()=>setRefresh(x=>x+1),30000);return()=>clearInterval(id)},[activeToken]);
 useEffect(()=>{drawRef.current={tool,symbol,tf,points:[]}},[tool,symbol,tf]);
 useEffect(()=>{
  if(!host.current || !activeToken)return;
  const c=createChart(host.current,{height:480,layout:{background:{type:ColorType.Solid,color:'#0b1421'},textColor:'#8295af'},grid:{vertLines:{color:'#172336'},horzLines:{color:'#172336'}},rightPriceScale:{borderColor:'#24344c'},timeScale:{timeVisible:true,borderColor:'#24344c'}});
  chart.current=c; const s=c.addCandlestickSeries({upColor:'#2dd4a1',downColor:'#fb7185',borderVisible:false,wickUpColor:'#2dd4a1',wickDownColor:'#fb7185'});series.current=s;
  const observer=new ResizeObserver(()=>{if(host.current)c.applyOptions({width:host.current.clientWidth})});observer.observe(host.current);
  const element=host.current;
  let down:{x:number;y:number}|undefined;
  const onDown=(e:PointerEvent)=>{down={x:e.clientX,y:e.clientY}};
  const onDraw=(e:PointerEvent)=>{const d=drawRef.current;if(d.tool==='cursor'||!down||Math.hypot(e.clientX-down.x,e.clientY-down.y)>5)return;down=undefined;const bounds=element.getBoundingClientRect();const x=e.clientX-bounds.left,y=e.clientY-bounds.top;if(x<0||y<0||x>bounds.width-c.priceScale('right').width()||y>bounds.height-c.timeScale().height())return;const time=c.timeScale().coordinateToTime(x);if(time===null||typeof time!=='number')return;const p={time};const price=s.coordinateToPrice(y);if(price===null)return;
   if(d.points[0]?.time===Number(p.time))return;d.points.push({time:Number(p.time),price});if(d.points.length===2){const drawing={tool:d.tool,points:[...d.points]};setDrawings(ds=>{const next=[...ds,drawing];localStorage.setItem('forex-draw-'+d.symbol+'-'+d.tf,JSON.stringify(next));return next});d.points=[]}};
  element.addEventListener('pointerdown',onDown,true);element.addEventListener('pointerup',onDraw,true);
  setChartReady(v=>v+1);
  return()=>{element.removeEventListener('pointerdown',onDown,true);element.removeEventListener('pointerup',onDraw,true);observer.disconnect();c.remove();chart.current=undefined;series.current=undefined};
 },[activeToken]);
 useEffect(()=>{try{setDrawings(JSON.parse(localStorage.getItem('forex-draw-'+symbol+'-'+tf)||'[]'))}catch{setDrawings([])}},[symbol,tf]);
 useEffect(()=>{if(!series.current)return;series.current.applyOptions({priceFormat:{type:'price',precision:symbol.includes('XAU')?2:symbol.includes('JPY')?3:5,minMove:symbol.includes('XAU')?.01:symbol.includes('JPY')?.001:.00001}});series.current.setData(data.map(c=>({...c,time:c.time as UTCTimestamp})));chart.current?.timeScale().fitContent()},[data,chartReady]);
 useEffect(()=>{
  const c=chart.current,s=series.current;if(!c||!s||!data.length)return;
  const rectangles:Rectangle[]=[];const overlays:ISeriesApi<'Line'>[]=[];const prices:ReturnType<typeof s.createPriceLine>[]=[];
  const line=(points:{time:number;price:number}[],color:string)=>{const pts=[...points].sort((a,b)=>a.time-b.time);if(pts.length<2||pts[0].time===pts[1].time)return;const l=c.addLineSeries({color,lineWidth:1,lastValueVisible:false,priceLineVisible:false,crosshairMarkerVisible:false});l.setData(pts.map(p=>({time:p.time as Time,value:p.price})));overlays.push(l)};
  if(ema){let value=data[0].close;const l=c.addLineSeries({color:'#e9b85e',lineWidth:2,lastValueVisible:false,priceLineVisible:false});l.setData(data.map(x=>{value=x.close*2/(period+1)+value*(1-2/(period+1));return{time:x.time as Time,value}}));overlays.push(l)}
  if(sma||bands){const values=data.map((x,i)=>{const sample=data.slice(Math.max(0,i-period+1),i+1);const avg=sample.reduce((sum,c)=>sum+c.close,0)/sample.length;const std=Math.sqrt(sample.reduce((sum,c)=>sum+(c.close-avg)**2,0)/sample.length);return{time:x.time as Time,avg,std}});for(const kind of (bands?[-1,0,1]:[0])){const l=c.addLineSeries({color:kind===0?'#bda0ee':'#527695',lineWidth:1,lastValueVisible:false,priceLineVisible:false});l.setData(values.map(x=>({time:x.time,value:x.avg+kind*2*x.std})));overlays.push(l)}}
  if(zones && snapshot){for(const [name,price] of [['Support',snapshot.support],['Resistance',snapshot.resistance]] as const){if(price)prices.push(s.createPriceLine({price,color:'#658db5',lineWidth:1,lineStyle:LineStyle.Dashed,axisLabelVisible:true,title:name}))}
   snapshot.zones.slice(-4).forEach(z=>[z.lower,z.upper].forEach(price=>prices.push(s.createPriceLine({price,color:z.direction==='bullish'?'#227c69':'#854253',lineWidth:1,lineStyle:LineStyle.Dotted,axisLabelVisible:false,title:z.kind}))));}
  drawings.forEach(d=>{const [a,b]=d.points;if(!a||!b)return;if(d.tool==='trendline')line(d.points,'#9bb8ff');
   if(d.tool==='rectangle'){const r=new Rectangle(d.points);s.attachPrimitive(r);rectangles.push(r)}
   if(d.tool==='fibonacci')[0,.236,.382,.5,.618,1].forEach(v=>line([{time:a.time,price:a.price+(b.price-a.price)*v},{time:b.time,price:a.price+(b.price-a.price)*v}],'#b39259'));
  });
  return()=>{if(chart.current!==c)return;rectangles.forEach(r=>s.detachPrimitive(r));overlays.forEach(l=>c.removeSeries(l));prices.forEach(l=>s.removePriceLine(l))};
 },[data,ema,sma,bands,period,zones,snapshot,drawings,chartReady]);
 async function action(path:string,body:unknown){setBusy(true);setError('');try{const r=await api(path,body);setNotice(JSON.stringify(r));setRefresh(x=>x+1)}catch(e){setError(String(e))}finally{setBusy(false)}}
 if(!activeToken)return <main className="login"><div className="eyebrow">FOREXLAB / PRIVATE TERMINAL</div><h1>Your market.<br/><span>With clear limits.</span></h1><p>Connect to your local research backend. Trading is disabled by default.</p><form onSubmit={e=>{e.preventDefault();setActiveToken(token)}}><label>Backend API token<input type="password" required minLength={24} autoComplete="off" value={token} onChange={e=>setToken(e.target.value)} /></label><button>Open terminal →</button></form><small>Token stays in memory. Generate it with the Windows setup script.</small></main>;
 return <div className="shell"><aside><div className="brand">◈ Forex<span>Lab</span></div><div className="eyebrow mt-10">WORKSPACE</div><div className="nav active">◫ &nbsp; Research terminal</div><a className="nav" href="#strategy">⌁ &nbsp; Strategy evidence</a><a className="nav" href="#journal">▤ &nbsp; Event journal</a><div className="side-bottom"><div className="status-dot"/> Private workspace<p>Rule-based · v0.1</p><button onClick={()=>{setActiveToken('');setToken('');setData([]);setStatus(undefined)}}>Lock terminal</button></div></aside>
 <main><header><div><div className="eyebrow">MARKET INTELLIGENCE / TERMINAL</div><h1>Research terminal</h1><p>Read the structure. Respect the risk.</p></div><div className="badge">{status?.source==='synthetic'?'SYNTHETIC DATA · NO BROKER':status?.account.demo?'MT5 DEMO ACCOUNT':'MT5 · ANALYSIS ONLY'}</div></header>
 <div className="disclaimer">{status?.source==='synthetic'?'Development fixture: these prices and equity are simulated.':'Broker prices · closed candles only.'} Live execution is unavailable. Returns are never guaranteed.</div>
 {error&&<div role="alert" className="error">{error}<button onClick={()=>setRefresh(x=>x+1)}>Retry</button></div>}{notice&&<div className="notice">{notice}</div>}
 <div className="metrics"><div><label>{status?.source==='synthetic'?'Fixture equity':'Account equity'}</label><strong>{status?.account.equity.toFixed(2)??'—'} <small>{status?.account.currency}</small></strong></div><div><label>Risk per entry</label><strong>{status?.limits.risk_percent??'—'}<small>%</small></strong></div><div><label>Daily loss cap</label><strong>{status?.limits.max_daily_loss??'—'}<small>%</small></strong></div><div><label>Strategy decision</label><strong className={signal?.side==='WAIT'?'muted':'green'}>{signal?.side??'—'}</strong></div></div>
 <div className="workspace"><section className="panel chart-panel"><div className="panel-head"><div className="flex gap-2"><select aria-label="Symbol" value={symbol} onChange={e=>setSymbol(e.target.value)}>{symbols.map(s=><option key={s}>{s}</option>)}</select><select aria-label="Timeframe" value={tf} onChange={e=>setTf(e.target.value)}>{(status?.timeframes??['M30']).map(t=><option key={t}>{t}</option>)}</select></div><button disabled={busy} onClick={()=>setRefresh(x=>x+1)}>{busy?'Loading…':'↻ Refresh'}</button></div>
 <div className="chart-tools">{['cursor','trendline','fibonacci','rectangle'].map(t=><button className={tool===t?'selected':''} key={t} onClick={()=>setTool(t)}>{t}</button>)}<button onClick={()=>{setDrawings([]);localStorage.removeItem('forex-draw-'+symbol+'-'+tf)}}>Clear</button></div>
 <div ref={host} className="chart"/><div className="chart-foot"><span>{tool==='cursor'?'Scroll to zoom · drag to pan':'Click two candle points to draw · drawings follow price and time'}</span><a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">Charts by TradingView</a></div>
 <div className="indicators"><label><input type="checkbox" checked={ema} onChange={e=>setEma(e.target.checked)}/> EMA</label><input aria-label="EMA period" type="number" min={2} max={300} value={period} onChange={e=>setPeriod(Math.min(300,Math.max(2,Number(e.target.value)||20)))}/><label><input type="checkbox" checked={sma} onChange={e=>setSma(e.target.checked)}/> SMA</label><label><input type="checkbox" checked={bands} onChange={e=>setBands(e.target.checked)}/> Bollinger ±2σ</label><label><input type="checkbox" checked={zones} onChange={e=>setZones(e.target.checked)}/> Structure & zones</label></div></section>
 <section id="strategy" className="panel"><div className="panel-head"><h2>Structure alignment</h2><span className="eyebrow">D1 → H4 → M30</span></div>{signal&&Object.entries(signal.analysis).map(([t,a])=><div className="alignment" key={t}><strong>{t}</strong><div><b className={a.trend==='bullish'?'green':a.trend==='bearish'?'red':'muted'}>{a.trend.toUpperCase()}</b><small>{a.event}</small></div></div>)}<div className="explain"><label>WHY THIS DECISION</label>{signal?.reasons.map(r=><p key={r}>· {r}</p>)}{signal?.entry&&<p>Entry {signal.entry.toFixed(5)}<br/>SL {signal.stop?.toFixed(5)} · TP {signal.target?.toFixed(5)}</p>}</div><div className="explain"><label>SELECTED TIMEFRAME</label><p>{snapshot?.sweeps.join(', ')||'No fresh liquidity sweep'}</p><p>ATR {snapshot?.atr.toFixed(5)??'—'} · {snapshot?.zones.length??0} active zones</p></div></section></div>
 <div className="bottom-grid"><section className="panel"><div className="panel-head"><h2>Execution controls</h2><span className="badge">DEMO ONLY</span></div><div className="p-5 space-y-3"><p>Demo automation is {status?.automation_enabled?'ON':'OFF'}. News clearance expires after 15 minutes. Automation resets to off after restart.</p><button disabled={busy} onClick={()=>action('emergency',{enabled:!status?.emergency})}>{status?.emergency?'Release entry stop':'■ Emergency stop new entries'}</button><p className={status?.emergency?'red':'muted'}>{status?.emergency?'New entries blocked':'Entry stop inactive'} · Existing positions are managed in MT5.</p><button disabled={busy||status?.source!=='mt5'} onClick={()=>{if(confirm('Have you reviewed a reliable economic calendar and confirmed no relevant high-impact event within the next 15 minutes?'))action('news-clearance',{minutes:15,confirmed_review:true})}}>Confirm calendar reviewed · 15 min</button><button disabled={busy||!status?.demo_execution_enabled||status.emergency||signal?.side==='WAIT'} onClick={()=>{if(confirm('Send one risk-checked order to the broker-confirmed DEMO account?'))action('demo/execute',{symbol,confirmation:'DEMO ONLY'})}}>Evaluate & submit one demo order</button><button disabled={busy||!status?.demo_execution_enabled} onClick={()=>{if(status?.automation_enabled||confirm('Enable automatic risk-checked entries on this DEMO account while news clearance is active?'))action('demo/automation',{enabled:!status?.automation_enabled,symbol,confirmation:'DEMO ONLY'})}}>{status?.automation_enabled?'Stop demo automation':'Enable demo automation'}</button><small>All conditions are checked again on the server. A $10 account may be unable to trade within the risk budget.</small></div></section>
 <section id="journal" className="panel"><div className="panel-head"><h2>Event journal</h2><span className="eyebrow">LATEST 100</span></div><div className="journal">{events.length?events.map(e=><details key={e.id}><summary><time>{new Date(e.time).toLocaleString()}</time> {e.kind}</summary><pre>{JSON.stringify(e.payload,null,2)}</pre></details>):<div className="empty">No events yet.<p>Risk blocks, controls and broker responses appear here.</p></div>}</div></section></div><footer>ForexLab · Research software · Not validated for real-money or commercial use</footer>
 </main></div>
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
