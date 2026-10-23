// Read-only whole-dashboard review: node analysis/dashboard_ux_audit.mjs [--baseline] [CDP URL] [review URL]
import {writeFileSync,mkdirSync} from 'node:fs';
const args=process.argv.slice(2),baseline=args.includes('--baseline'),[cdp='http://127.0.0.1:9231',app='http://127.0.0.1:8766']=args.filter(v=>v!=='--baseline'),directory='/private/tmp/football-ux-'+Date.now();mkdirSync(directory);
const target=await(await fetch(cdp+'/json/new?'+encodeURIComponent(app),{method:'PUT'})).json(),ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);
let seq=0;const pending=new Map(),exceptions=[];ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')exceptions.push(m.params.exceptionDetails);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}};
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
const wait=async expression=>{for(let i=0;i<240;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Timed out '+expression);};
const agenda=await(await fetch(app+'/api/agenda?date=2026-10-22')).json(),future=agenda.fixtures.find(f=>f.competition==='English Premier League'&&!f.result&&f.kickoff.slice(0,10)>agenda.as_of);
const centreHash='#'+new URLSearchParams({section:'home',tab:future.competition,date:'2026-10-22',match:[future.home,future.away,future.kickoff.slice(0,10)].join('|'),mc:future.competition,centre:'1'});
const routes=[['home','#section=home&date=2026-10-22'],['comps','#section=races&tab=English+Premier+League&date=2026-10-22'],['clubs','#section=clubs&tab=English+Premier+League&team=Arsenal&page=1&clubsection=performance&date=2026-10-22'],['players','#section=players&tab=English+Premier+League&date=2026-10-22'],['explore','#section=explore&tab=Movers&date=2026-10-22'],['atlas','#section=clubs&tab=English+Premier+League&team=Arsenal&page=1&clubsection=atlas&date=2026-10-22'],['rivals','#section=races&tab=English+Premier+League&view=viz&viz=rivals&date=2026-10-22'],['scenarios','#section=races&tab=English+Premier+League&view=scenarios&date=2026-10-22'],['match-centre',centreHash],['performance','#section=explore&tab=Performance+Studio&date=2026-10-22'],['time-machine','#section=explore&tab=Time+Machine&date=2026-10-22'],['forecast-lab','#section=explore&tab=Forecast+Lab&date=2026-10-22']];
const observations=[],interactions=[];
try{
 await call('Page.enable');await call('Runtime.enable');
 for(const [name,hash] of routes){
  await call('Page.navigate',{url:app+'/?ux-audit='+Date.now()+hash});
  await wait(`Boolean(typeof RESULT!=='undefined'&&RESULT&&document.querySelector('[data-workspace]')&&document.getElementById('view').innerText.trim()&&!document.getElementById('view').innerText.toLowerCase().includes('loading'))`);
  if(name==='atlas')await wait(`Boolean(document.querySelector('[data-atlas-count]'))`);
  if(name==='scenarios')await wait(`Boolean(document.querySelector('#scenario-run'))`);
  if(name==='match-centre')await wait(`Boolean(document.querySelector('#centre-scenario'))`);
  if(name==='performance')await wait(`Boolean(document.querySelector('#studio-chart'))`);
  if(name==='time-machine')await wait(`Boolean(document.querySelector('[data-tm-bridge]'))`);
  if(name==='forecast-lab')await wait(`Boolean(document.querySelector('[data-lab-summary]'))`);
  for(const width of [1440,960,390]){
   await call('Emulation.setDeviceMetricsOverride',{width,height:1100,deviceScaleFactor:1,mobile:false});
   for(const theme of ['light','dark']){
    await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:theme}]});await ev(`document.documentElement.dataset.theme='${theme}';scrollTo(0,0)`);
    const observation=await ev(`(()=>{const visible=el=>Boolean(el.getClientRects().length),controls=[...document.querySelectorAll('select,input:not([type=hidden]),textarea')].filter(visible);return {page:'${name}',width:${width},theme:'${theme}',css_theme:getComputedStyle(document.documentElement).colorScheme,overflow:document.documentElement.scrollWidth-innerWidth,unlabelled:controls.filter(el=>!el.labels?.length&&!el.getAttribute('aria-label')&&!el.getAttribute('aria-labelledby')).map(el=>el.id||el.outerHTML.slice(0,80)),navigation_bottom:Math.round(document.querySelector('.workspace-nav').getBoundingClientRect().bottom),main_buttons:[...document.querySelectorAll('[data-workspace]')].map(el=>({label:el.innerText,height:Math.round(el.getBoundingClientRect().height),top:Math.round(el.getBoundingClientRect().top)})),alerts:[...document.querySelectorAll('#view [role=alert]')].filter(visible).map(el=>el.innerText)};})()`);
    observations.push(observation);const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});writeFileSync(directory+'/'+name+'-'+width+'-'+theme+'.png',Buffer.from(shot.data,'base64'));
   }
  }
  const interaction=await ev(`(()=>{const el=[...document.querySelectorAll('#view select')].find(el=>el.getClientRects().length&&el.options.length>1);if(!el)return {page:'${name}',skipped:'No select'};const id=el.id,t=performance.now();el.focus();el.dispatchEvent(new Event('change'));return {page:'${name}',id,milliseconds:performance.now()-t};})()`);
  if(interaction.id){await new Promise(r=>setTimeout(r,300));interaction.focusAfter=await ev('document.activeElement.id');interaction.focusPreserved=interaction.id===interaction.focusAfter;}interactions.push(interaction);
 }
 const failures=observations.filter(o=>o.overflow>1||o.unlabelled.length||o.alerts.length||o.css_theme!==o.theme||o.width===390&&(new Set(o.main_buttons.map(b=>b.top)).size!==1||o.main_buttons.some(b=>b.height<44)));
 console.log(JSON.stringify({baseline,screenshots:directory,observations,interactions,exceptions,failures},null,2));
 if(!baseline&&(failures.length||exceptions.length||interactions.some(i=>i.focusPreserved===false)))process.exitCode=1;
}finally{ws.close();await fetch(cdp+'/json/close/'+target.id);}
