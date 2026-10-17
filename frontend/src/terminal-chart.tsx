import {useEffect, useRef, useState} from 'react';
import {ColorType, createChart, LineStyle} from 'lightweight-charts';
import type {IChartApi, ISeriesApi, Time, UTCTimestamp} from 'lightweight-charts';
import {bollinger, ema, macd, rsi, sma} from './indicators';
import type {IndicatorPoint, IndicatorSettings} from './indicators';
import type {Analysis, Candle, Drawing} from './types';
import {Rectangle} from './rectangle';

const colors = {ema:'#f3bd66',sma:'#b3a1ff',bands:'#678fc3',rsi:'#bca4ff',macd:'#69aafc',signal:'#f3bd66'};
const chartOptions = {
  layout:{background:{type:ColorType.Solid,color:'#0b1421'},textColor:'#91a5be',fontSize:11,attributionLogo:false},
  grid:{vertLines:{color:'#142235'},horzLines:{color:'#142235'}},
  rightPriceScale:{borderColor:'#24344c',minimumWidth:68},
  timeScale:{timeVisible:true,borderColor:'#24344c',rightOffset:5},
};

type Props = {
  symbol:string;tf:string;data:Candle[];snapshot?:Analysis;settings:IndicatorSettings;
  tool:string;drawings:Drawing[];onDrawing:(drawing:Drawing)=>void;
  pricePrecision?:number;priceMinMove?:number;
};

export function TerminalChart({symbol,tf,data,snapshot,settings,tool,drawings,onDrawing,pricePrecision,priceMinMove}:Props) {
  const host=useRef<HTMLDivElement>(null), rsiHost=useRef<HTMLDivElement>(null), macdHost=useRef<HTMLDivElement>(null);
  const chart=useRef<IChartApi|undefined>(undefined), candleSeries=useRef<ISeriesApi<'Candlestick'>|undefined>(undefined);
  const drawRef=useRef({tool,onDrawing,points:[] as Drawing['points']});
  const viewKey=useRef('');
  const [ready,setReady]=useState(0),[anchor,setAnchor]=useState(false);
  const precision=Number.isInteger(pricePrecision)&&pricePrecision!>=0&&pricePrecision!<=12?pricePrecision!:(symbol.includes('XAU')?2:symbol.includes('JPY')?3:5);
  const minMove=priceMinMove!==undefined&&Number.isFinite(priceMinMove)&&priceMinMove>0?priceMinMove:10**-precision;

  useEffect(()=>{drawRef.current={tool,onDrawing,points:[]};setAnchor(false)},[tool,symbol,tf,onDrawing]);

  useEffect(()=>{
    if(!host.current)return;
    const element=host.current;
    const c=createChart(element,{...chartOptions,height:element.clientHeight||430,width:element.clientWidth});
    chart.current=c;
    const s=c.addCandlestickSeries({upColor:'#2dd4a1',downColor:'#fb7185',borderVisible:false,wickUpColor:'#2dd4a1',wickDownColor:'#fb7185'});
    candleSeries.current=s;
    const observer=new ResizeObserver(()=>{
      if(element.clientWidth)c.applyOptions({width:element.clientWidth,height:element.clientHeight});
    });
    observer.observe(element);
    let down:{x:number;y:number}|undefined;
    const onDown=(event:PointerEvent)=>{down={x:event.clientX,y:event.clientY}};
    const onUp=(event:PointerEvent)=>{
      const d=drawRef.current;
      if(d.tool==='cursor'||!down||Math.hypot(event.clientX-down.x,event.clientY-down.y)>9){down=undefined;return}
      down=undefined;
      const bounds=element.getBoundingClientRect();
      const x=event.clientX-bounds.left,y=event.clientY-bounds.top;
      if(x<0||y<0||x>bounds.width-c.priceScale('right').width()||y>bounds.height-c.timeScale().height())return;
      const time=c.timeScale().coordinateToTime(x),price=s.coordinateToPrice(y);
      if(typeof time!=='number'||price===null||d.points[0]?.time===time)return;
      d.points.push({time,price});setAnchor(d.points.length===1);
      if(d.points.length===2){d.onDrawing({tool:d.tool,points:[...d.points]});d.points=[];setAnchor(false)}
    };
    element.addEventListener('pointerdown',onDown,true);
    element.addEventListener('pointerup',onUp,true);
    setReady(v=>v+1);
    return()=>{
      element.removeEventListener('pointerdown',onDown,true);element.removeEventListener('pointerup',onUp,true);
      observer.disconnect();c.remove();chart.current=undefined;candleSeries.current=undefined;
    };
  },[]);

  useEffect(()=>{
    chart.current?.applyOptions({handleScroll:tool==='cursor',handleScale:tool==='cursor'});
  },[tool,ready]);

  useEffect(()=>{
    const s=candleSeries.current,c=chart.current;if(!s||!c)return;
    s.applyOptions({priceFormat:{type:'price',precision,minMove}});
    s.setData(data.map(row=>({...row,time:row.time as UTCTimestamp})));
    const key=symbol+':'+tf;
    if(data.length&&viewKey.current!==key){c.timeScale().fitContent();viewKey.current=key}
  },[data,symbol,tf,precision,minMove,ready]);

  useEffect(()=>{
    const c=chart.current,s=candleSeries.current;if(!c||!s||!data.length)return;
    const rectangles:Rectangle[]=[],overlays:ISeriesApi<'Line'>[]=[],prices:ReturnType<typeof s.createPriceLine>[]=[];
    function line(points:IndicatorPoint[],color:string,width:1|2=1){
      const series=c!.addLineSeries({color,lineWidth:width,lastValueVisible:false,priceLineVisible:false,crosshairMarkerVisible:false});
      series.setData(points.map(p=>({...p,time:p.time as Time})));overlays.push(series);
    }
    if(settings.ema)line(ema(data,settings.emaPeriod),colors.ema,2);
    if(settings.sma)line(sma(data,settings.smaPeriod),colors.sma,2);
    if(settings.bands){
      const values=bollinger(data,settings.bandsPeriod,settings.bandsDeviation);
      for(const key of ['upper','middle','lower'] as const)line(values.map(p=>({time:p.time,value:p[key]})),colors.bands);
    }
    if(settings.zones&&snapshot){
      for(const [name,price] of [['Support',snapshot.support],['Resistance',snapshot.resistance]] as const){
        if(price!==null)prices.push(s.createPriceLine({price,color:'#658db5',lineWidth:1,lineStyle:LineStyle.Dashed,axisLabelVisible:true,title:name}));
      }
      snapshot.zones.slice(-4).forEach(z=>[z.lower,z.upper].forEach(price=>prices.push(s.createPriceLine({price,color:z.direction==='bullish'?'#277f6e':'#914d5f',lineWidth:1,lineStyle:LineStyle.Dotted,axisLabelVisible:false,title:z.kind}))));
    }
    drawings.forEach(d=>{
      const [a,b]=d.points;if(!a||!b||a.time===b.time)return;
      const segment=(points:Drawing['points'],color:string)=>line([...points].sort((p,q)=>p.time-q.time).map(p=>({time:p.time,value:p.price})),color);
      if(d.tool==='trendline')segment(d.points,'#9bb8ff');
      if(d.tool==='rectangle'){const r=new Rectangle(d.points);s.attachPrimitive(r);rectangles.push(r)}
      if(d.tool==='fibonacci')[0,.236,.382,.5,.618,1].forEach(v=>segment([{time:a.time,price:a.price+(b.price-a.price)*v},{time:b.time,price:a.price+(b.price-a.price)*v}],'#b39259'));
    });
    return()=>{if(chart.current!==c)return;rectangles.forEach(r=>s.detachPrimitive(r));overlays.forEach(l=>c.removeSeries(l));prices.forEach(l=>s.removePriceLine(l))};
  },[data,settings,snapshot,drawings,ready]);

  useEffect(()=>{
    const primary=chart.current;if(!primary)return;
    const subcharts:IChartApi[]=[],observers:ResizeObserver[]=[];
    const build=(element:HTMLDivElement)=>{
      const sub=createChart(element,{...chartOptions,height:146,width:element.clientWidth,handleScroll:false,handleScale:false,timeScale:{...chartOptions.timeScale,visible:false}});
      const observer=new ResizeObserver(()=>{if(element.clientWidth)sub.applyOptions({width:element.clientWidth})});
      observer.observe(element);observers.push(observer);subcharts.push(sub);return sub;
    };
    const add=(c:IChartApi,points:IndicatorPoint[],color:string)=>{
      const s=c.addLineSeries({color,lineWidth:1,lastValueVisible:true,priceLineVisible:false,crosshairMarkerVisible:false});
      // Whitespace keeps logical candle indices aligned with the main price chart.
      const pointsByTime=new Map(points.map(p=>[p.time,p.value]));
      s.setData(data.map(p=>pointsByTime.has(p.time)?{time:p.time as Time,value:pointsByTime.get(p.time)!}:{time:p.time as Time}));
      return s;
    };
    if(settings.rsi&&rsiHost.current){
      const c=build(rsiHost.current);
      c.priceScale('right').applyOptions({scaleMargins:{top:.12,bottom:.12}});
      const values=rsi(data,settings.rsiPeriod),s=add(c,values,colors.rsi);
      s.applyOptions({priceFormat:{type:'price',precision:1,minMove:.1},autoscaleInfoProvider:()=>({priceRange:{minValue:0,maxValue:100}})});
      [30,70].forEach(price=>s.createPriceLine({price,color:'#60758e',lineWidth:1,lineStyle:LineStyle.Dashed,axisLabelVisible:true,title:''}));
    }
    if(settings.macd&&macdHost.current){
      const c=build(macdHost.current),values=macd(data,settings.macdFast,settings.macdSlow,settings.macdSignal);
      const macdPrecision=Math.min(precision+2,12);
      const priceFormat={type:'price' as const,precision:macdPrecision,minMove:10**-macdPrecision};
      const histogram=c.addHistogramSeries({priceLineVisible:false,lastValueVisible:false,priceFormat});
      const byTime=new Map(values.filter(p=>p.histogram!==undefined).map(p=>[p.time,p.histogram!]));
      histogram.setData(data.map(p=>byTime.has(p.time)?{time:p.time as Time,value:byTime.get(p.time)!,color:byTime.get(p.time)!>=0?'#238b72':'#ac5364'}:{time:p.time as Time}));
      add(c,values.map(p=>({time:p.time,value:p.macd})),colors.macd).applyOptions({priceFormat});
      add(c,values.filter(p=>p.signal!==undefined).map(p=>({time:p.time,value:p.signal!})),colors.signal).applyOptions({priceFormat});
    }
    const sync=()=>{
      const range=primary.timeScale().getVisibleLogicalRange();
      if(range)subcharts.forEach(c=>c.timeScale().setVisibleLogicalRange(range));
    };
    primary.timeScale().subscribeVisibleLogicalRangeChange(sync);sync();
    return()=>{primary.timeScale().unsubscribeVisibleLogicalRangeChange(sync);observers.forEach(o=>o.disconnect());subcharts.forEach(c=>c.remove())};
  },[data,settings,precision,ready]);

  const last=data.at(-1);
  const active=[settings.ema&&`EMA ${settings.emaPeriod}`,settings.sma&&`SMA ${settings.smaPeriod}`,settings.bands&&`BB ${settings.bandsPeriod} · ${settings.bandsDeviation}σ`].filter(Boolean);
  return <>
    <div className="chart-caption"><strong>{symbol||'Select a symbol'} <span>· {tf}</span></strong><span>{last?`O ${last.open.toFixed(precision)}  H ${last.high.toFixed(precision)}  L ${last.low.toFixed(precision)}  C ${last.close.toFixed(precision)}`:'No closed candles loaded'}</span></div>
    {active.length>0&&<div className="indicator-legend">{active.map(name=><span key={String(name)}>{name}</span>)}</div>}
    <div ref={host} className="chart" aria-label={`${symbol} ${tf} candlestick chart`}/>
    {settings.rsi&&<section className="oscillator"><div>RSI ({settings.rsiPeriod}) <span>Wilder · 30 / 70</span></div><div ref={rsiHost}/>{data.length<=settings.rsiPeriod&&<small>More candles needed for RSI.</small>}</section>}
    {settings.macd&&<section className="oscillator"><div>MACD ({settings.macdFast}, {settings.macdSlow}, {settings.macdSignal}) <span>MACD / signal / histogram</span></div><div ref={macdHost}/>{data.length<settings.macdSlow+settings.macdSignal-1&&<small>More candles needed for the MACD signal.</small>}</section>}
    <div className="chart-foot"><span>{tool==='cursor'?'Pinch or scroll to zoom · drag to pan':`${anchor?'Second':'First'} point: tap a candle to place ${tool}. Switch to Move to pan.`}</span><a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">Charts by TradingView</a></div>
  </>;
}
