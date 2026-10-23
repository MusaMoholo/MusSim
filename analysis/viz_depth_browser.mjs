// Read-only interpretation checks. Start an isolated review server and CDP profile first.
import {mkdirSync,writeFileSync} from 'node:fs';
const [cdp='http://127.0.0.1:9234',app='http://127.0.0.1:8768',date='2026-10-22']=process.argv.slice(2),dir='/private/tmp/football-viz-depth-browser-'+Date.now();mkdirSync(dir);
const target=await(await fetch(cdp+'/json/new?'+encodeURIComponent(app),{method:'PUT'})).json(),ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);
let seq=0,checks=0;const pending=new Map(),exceptions=[],observations=[];
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')exceptions.push(m.params.exceptionDetails);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}};
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
const assert=(ok,message)=>{checks++;if(!ok)throw Error(message);};
const wait=async expression=>{for(let i=0;i<300;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Timed out '+expression+' '+await ev('document.body.innerText.slice(-800)'));};
const change=async(id,value)=>{await ev(`(()=>{const e=document.getElementById(${JSON.stringify(id)});e.closest('details').open=true;e.focus();e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('change'));})()`);await wait(`document.activeElement.id===${JSON.stringify(id)}`);assert(await ev(`document.getElementById(${JSON.stringify(id)}).value===${JSON.stringify(value)}`),'selected native control '+id);};
const nav=async(name,params,ready)=>{await call('Page.navigate',{url:app+'/?viz-depth='+name+'#'+new URLSearchParams({date,...params})});await wait(ready);};
const route=(viz,tab='English Premier League')=>({section:'races',tab,view:'viz',viz});
try{
 await call('Page.enable');await call('Runtime.enable');
 const cases=[['quality',route('sq'),`document.querySelector('[data-product-guide]')`],['goals',route('gx'),`document.querySelector('#competition-evidence-plot svg')`],['points',route('xp'),`document.querySelector('#competition-evidence-plot svg')`],['form',route('fm'),`document.querySelector('#lcevidence')`],['ratings',route('rt'),`document.querySelector('#rtsvg')`],['leagues',{section:'explore',tab:'Visualisations',viz:'ls'},`document.querySelector('[data-league-spread]')`],['runin',route('ri'),`document.querySelector('[data-ri-toughest]')`],['final',route('fp'),`document.querySelector('[data-points-target]')`],['knockout',route('ko','UEFA Champions League'),`document.querySelector('[data-ko-breakdown]')`],['movers',{section:'explore',tab:'Visualisations',viz:'changes'},`document.querySelector('[data-mover-endpoints]')`],...['trajectory','quality','expectation'].map(chart=>['club-'+chart,{section:'clubs',team:'Arsenal',page:'1',clubsection:'performance',clubchart:chart,clubcomp:'English Premier League'},`document.querySelector('#lcperformance')`])];
 for(const [name,params,ready] of cases){
  await nav(name,params,ready);
  if(name==='form')await change('competition-evidence-baseline','on');
  if(name==='ratings')await change('chart-opt-ratingReference','on');
  if(name==='final')await change('chart-opt-pointTarget','70');
  if(name==='club-trajectory'||name==='club-quality')await change('studio-baseline','on');
  if(name==='form'||name.startsWith('club-')){
   const prefix=name==='form'?'lcevidence':'lcperformance';await wait(`document.querySelector('#${prefix} [data-line-baseline]')`);
   const refs=await ev(`(()=>{const c=LC.${prefix};return [...document.querySelectorAll('#${prefix} [data-line-baseline]')].map(e=>({team:e.dataset.lineBaseline,value:+e.dataset.baselineValue,source:c.references.get(e.dataset.lineBaseline)}))})()`);
   assert(refs.length>0&&refs.every(r=>Number.isFinite(r.value)&&r.value===r.source),'explicit finite line references '+name);
   const independent=await ev(`(async()=>{const raw=await(await fetch('/api/performance?'+new URLSearchParams({date:RESULT.source.date,pr:RESULT.source.projection_sha256,scope:'all'}))).json(),state=${name==='form'?'COMP_EVIDENCE_STATE':'STUDIO_STATE'},format=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/London'}),comp=raw.competitions.find(c=>c.competition===state.competition);return [...document.querySelectorAll('#${prefix} [data-line-baseline]')].map(e=>{const team=e.dataset.lineBaseline,rows=raw.fixtures.filter(f=>{const day=format.format(new Date(WORKSPACE.fixtureInstant(f.kickoff,f.competition)));return f.competition===state.competition&&(f.home===team||f.away===team)&&day>=state.from&&day<=state.to&&(state.venue==='all'||(state.venue==='home'?f.home===team:f.away===team))&&(comp.kind!=='uefa'||Number.isFinite(f.round)&&(f.minutes==null||f.minutes===90)&&(!f.outcome||f.outcome==='fulltime'));});let want=null;if(state.chart==='expectation')want=0;else if(state.chart==='quality'){const side=state.side==='against'?1:0,xg=rows.reduce((n,f)=>n+f.xg[(f.home===team?0:1)^side],0),shots=rows.reduce((n,f)=>n+f.shots[(f.home===team?0:1)^side],0);want=xg/shots;}else{const metric=({nd:'xgd',nf:'xgf',na:'xga',pp:'points'})[state.metric]||state.metric;want=rows.reduce((n,f)=>{const i=f.home===team?0:1;return n+(metric==='points'?(f.result[i]>f.result[1-i]?3:f.result[i]===f.result[1-i]?1:0):metric==='gd'?f.result[i]-f.result[1-i]:metric==='xgf'?f.xg[i]:metric==='xga'?f.xg[1-i]:f.xg[i]-f.xg[1-i]);},0)/rows.length;}return {team,n:rows.length,actual:+e.dataset.baselineValue,want};});})()`);
   assert(independent.length>0&&independent.every(r=>r.n>0&&Math.abs(r.actual-r.want)<1e-10),'raw fixture reference identity '+name);observations.push({name,refs,independent});
   const hash=await ev('location.hash');await call('Page.reload');await wait(`document.querySelector('#${prefix} [data-line-baseline]')`);assert(await ev('location.hash')===hash,'baseline saved route/reload '+name);
  }
  if(name==='quality'){
   assert(await ev(`(()=>{const pts=[...document.querySelectorAll('#competition-evidence-plot .hit')];return pts.length>0&&pts.every(e=>e.dataset.tip.includes('Combined threat'))})()`),'quality combined-threat tooltips');
   await change('competition-evidence-side','against');assert(await ev(`document.querySelector('#view').textContent.includes('equal xG against per match')`),'Against contours retain conceded units');await change('competition-evidence-side','for');
  }
  if(name==='goals'||name==='points')assert(await ev(`document.querySelectorAll('#competition-evidence-plot .hit').length>0&&[...document.querySelectorAll('#competition-evidence-plot .hit')].every(e=>e.dataset.tip.includes('/ covered match'))&&document.querySelector('#competition-evidence-plot').textContent.includes('equal values')`),'total and per-covered-match residual '+name);
  if(name==='ratings'){
   const refs=await ev(`(()=>{const g=RTC.g,metric=RTC.metric;return [...document.querySelectorAll('[data-rating-reference]')].map(e=>{const i=g.teams.indexOf(e.dataset.ratingReference),values=g[metric][i].filter((v,k)=>RTC.real[k]&&Number.isFinite(v));return {actual:+e.dataset.value,want:values.reduce((n,v)=>n+v,0)/values.length}})})()`);
   assert(refs.length>0&&refs.every(r=>Math.abs(r.actual-r.want)<1e-10),'rating average independently excludes projected rounds');
   const hash=await ev('location.hash');await call('Page.reload');await wait(`document.querySelector('[data-rating-reference]')`);assert(await ev('location.hash')===hash,'rating reference reload');
  }
  if(name==='final'){
   const tails=await ev(`(()=>{const b=RESULT.leagues.find(b=>b.competition===TAB);return [...document.querySelectorAll('[data-points-target]')].map(e=>{const t=b.teams.find(t=>t.team===e.dataset.pointsTarget),p=t.pts,mass=p.dist.reduce((n,v)=>n+v,0);return {target:+e.dataset.target,actual:+e.dataset.probability,want:p.dist.reduce((n,v,i)=>n+(p.offset+i>=70?v:0),0)/mass}})})()`);
   assert(tails.length>0&&tails.every(t=>t.target===70&&Math.abs(t.actual-t.want)<1e-10),'target probability source identity');assert(await ev(`document.querySelectorAll('[data-points-median]').length===${tails.length}`),'all retained medians visible');
   await call('Page.reload');await wait(`document.querySelector('#chart-opt-pointTarget')?.value==='70'`);assert(await ev(`new URLSearchParams(location.hash.slice(1)).get('ptarget')==='70'`),'target reload pin');
   await ev(`document.querySelector('[data-points-values]').open=true`);await change('chart-opt-pointTarget','71');assert(await ev(`document.querySelector('[data-points-values]').open`),'point values disclosure survives target change');await change('chart-opt-pointTarget','70');
  }
  if(name==='runin'){
   const counts=await ev(`(()=>{const out={};document.querySelectorAll('[data-ri-toughest]').forEach(e=>{const team=e.dataset.ri.split('|')[0];out[team]=(out[team]||0)+1});return Object.values(out)})()`);assert(counts.length>0&&counts.every(n=>n===3),'three outlined fixtures for every available window');
  }
  if(name==='knockout'){
   assert(await ev(`document.querySelectorAll('[data-ko-loss]').length>0&&document.querySelector('[data-ko-breakdown]').textContent.includes('Reach next given previous')`),'knockout losses and conditional progression');
   const losses=await ev(`(()=>{const block=RESULT.uefa.find(b=>b.competition===TAB);return [...document.querySelectorAll('[data-ko-loss]')].map(e=>{const t=block.teams.find(t=>t.team===e.dataset.koLoss),v=[1,1-t.p_out,t.p_r16,t.p_qf,t.p_sf,t.p_f,t.p_win],d=v.slice(1).map((x,i)=>v[i]-x);return {actual:+e.dataset.loss,want:Math.max(...d)}})})()`);
   assert(losses.length>0&&losses.every(r=>Math.abs(r.actual-r.want)<1e-10),'knockout source reach-loss identity');
  }
  if(name==='movers')assert(await ev(`(()=>{const all=[...document.querySelectorAll('[data-mover-endpoints]')];return all.length>0&&all.every(e=>{const circles=e.querySelectorAll('circle');return Math.abs(+circles[0].getAttribute('cx')-2-96*Number(e.dataset.then))<1e-8&&Math.abs(+circles[1].getAttribute('cx')-2-96*Number(e.dataset.now))<1e-8})})()`),'movers common-scale endpoint geometry');
  for(const width of [1440,960,390])for(const theme of ['light','dark']){
   await call('Emulation.setDeviceMetricsOverride',{width,height:1100,deviceScaleFactor:1,mobile:false});await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:theme}]});await ev(`document.documentElement.dataset.theme='${theme}';scrollTo(0,0)`);
   const layout=await ev(`new Promise(resolve=>requestAnimationFrame(()=>resolve({overflow:document.documentElement.scrollWidth-innerWidth,theme:getComputedStyle(document.documentElement).colorScheme,panels:document.querySelectorAll('[data-chart-picker]').length})))`);
   assert(layout.overflow<=1&&layout.theme===theme,'layout '+name+' '+width+' '+theme+' '+JSON.stringify(layout));
   const size=await call('Page.getLayoutMetrics'),height=Math.min(3200,size.cssContentSize.height),shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width,height,scale:1}});writeFileSync(dir+'/'+name+'-'+width+'-'+theme+'.png',Buffer.from(shot.data,'base64'));
  }
 }
 assert(exceptions.length===0,'no browser runtime exceptions');console.log(JSON.stringify({checks,dir,observations,exceptions},null,2));
}finally{await call('Page.close').catch(()=>{});ws.close();}
