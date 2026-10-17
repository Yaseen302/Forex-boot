import type {ISeriesPrimitive,SeriesAttachedParameter,ISeriesPrimitivePaneView,ISeriesPrimitivePaneRenderer,Time} from 'lightweight-charts';

// Price/time anchored shape; redraws with the chart's own pan/zoom lifecycle.
export class Rectangle implements ISeriesPrimitive<Time> {
 private attachment?:SeriesAttachedParameter<Time>;
 constructor(private points:{time:number;price:number}[]){}
 attached(p:SeriesAttachedParameter<Time>){this.attachment=p;p.requestUpdate()}
 detached(){this.attachment=undefined}
 paneViews():ISeriesPrimitivePaneView[]{
  return [{zOrder:()=> 'top',renderer:():ISeriesPrimitivePaneRenderer=>({draw:(target)=>{
   const p=this.attachment;if(!p)return;
   const [a,b]=this.points;
   const x1=p.chart.timeScale().timeToCoordinate(a.time as Time),x2=p.chart.timeScale().timeToCoordinate(b.time as Time);
   const y1=p.series.priceToCoordinate(a.price),y2=p.series.priceToCoordinate(b.price);
   if(x1===null||x2===null||y1===null||y2===null)return;
   target.useMediaCoordinateSpace(({context:ctx})=>{ctx.save();ctx.strokeStyle='#c0a6ff';ctx.fillStyle='rgba(192,166,255,.10)';ctx.lineWidth=1;ctx.fillRect(Math.min(x1,x2),Math.min(y1,y2),Math.abs(x2-x1),Math.abs(y2-y1));ctx.strokeRect(Math.min(x1,x2),Math.min(y1,y2),Math.abs(x2-x1),Math.abs(y2-y1));ctx.restore()});
  }})}];
 }
}
