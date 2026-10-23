// Read-only navigation/saved-route and responsive acceptance. Separate CDP profile/server only.
import {mkdirSync,writeFileSync} from 'node:fs';
const [cdp='http://127.0.0.1:9231',app='http://127.0.0.1:8766',snapshot='2026-10-22']=process.argv.slice(2),dir='/private/tmp/football-consolidation-browser-'+Date.now();mkdirSync(dir);
const target=await(await fetch(cdp+'/json/new?'+encodeURIComponent(app),{method:'PUT'})).json(),ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);let seq=0,checks=0;const pending=new Map(),exceptions=[],timings=[],observations=[];
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')exceptions.push(m.params.exceptionDetails);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}};
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
const assert=(ok,m)=>{checks++;if(!ok)throw Error(m);};
const wait=async expression=>{for(let i=0;i<300;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Timed out '+expression+' '+await ev('document.body.innerText.slice(-1200)'));};
const ready=()=>wait(`Boolean(typeof RESULT!=='undefined'&&RESULT&&document.querySelector('#view .panel')&&!/loading/i.test(document.querySelector('#view').innerText))`);
const nav=async params=>{await call('Page.navigate',{url:app+'/#'+new URLSearchParams({date:snapshot,...params})});await ready();};
const change=async(id,value)=>{const ms=await ev(`(()=>{const e=document.getElementById(${JSON.stringify(id)});e.focus();e.value=${JSON.stringify(value)};const t=performance.now();e.dispatchEvent(new Event('change'));return performance.now()-t;})()`);await ready();assert(await ev(`document.activeElement.id===${JSON.stringify(id)}`),'native focus '+id);return ms;};
const shot=async name=>{const s=await call('Page.captureScreenshot',{format:'png'});writeFileSync(dir+'/'+name+'.png',Buffer.from(s.data,'base64'));};
try{
 await call('Page.enable');await call('Runtime.enable');await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
 await nav({section:'explore',tab:'Visualisations',viz:'xa'});
 assert(await ev(`JSON.stringify([...document.querySelectorAll('#tabs [data-t]')].map(e=>e.dataset.t))===JSON.stringify(['Visualisations','Time Machine','Forecast Lab'])`),'three Explore desktop destinations');
 assert(await ev(`document.querySelectorAll('#mobile-nav option').length===3`),'three Explore phone destinations');
 assert(await ev(`!document.querySelector('#run-data').open&&document.querySelector('#run-data #livetoggle')&&document.querySelector('#run-data #pipeline-info')&&document.querySelector('#snapinfo').textContent.includes('Data through')`),'closed Run & data, visible cutoff');
 // Migrate complete legacy state, then reload the canonical link and compare pins/control state.
 for(const [tab,viz,extra] of [['Ratings','ratings',{of:'English Premier League',dw:'1m'}],['Movers','changes',{category:'survival',dw:'1m'}],['Trophies','trophies',{}]]){
  await nav({section:'explore',tab,...extra});
  assert(await ev(`TAB==='Visualisations'&&VIZSEL===${JSON.stringify(viz)}&&WORKSPACE_SECTION==='explore'&&document.querySelector('#all-chart-select').value===${JSON.stringify(viz)}`),'legacy migration '+tab);
  const route=await ev('location.hash');assert(new URLSearchParams(route.slice(1)).get('pr')?.length===64,'revision pin '+tab);
  for(const [key,value]of Object.entries(extra))assert(new URLSearchParams(route.slice(1)).get(key)===value,'legacy filter '+key);
  if(tab==='Ratings')assert(await ev(`document.querySelectorAll('#all-analysis tbody tr').length===20&&document.querySelector('#ratsel').value==='English Premier League'`),'complete sortable ratings population');
  if(tab==='Movers'){assert(await ev(`document.querySelector('[data-movers="survival"]')`),'mover category table');await ev(`document.querySelector('[data-opt=movers][data-val=cups]').click()`);await ready();assert(await ev(`document.querySelector('[data-movers="cups"]')&&new URLSearchParams(location.hash.slice(1)).get('category')==='cups'`),'embedded mover redraw');await ev('history.back()');await wait(`MOVERSEL==='survival'&&Boolean(document.querySelector('[data-movers=survival]'))`);assert(await ev(`MOVERSEL==='survival'`),'changes category Back');}
  if(tab==='Trophies')assert(await ev(`document.querySelectorAll('#all-analysis table').length===2&&!document.querySelector('#all-analysis details').open&&document.querySelector('#all-analysis details table tbody tr')`),'joint hauls retained on demand');
  await call('Page.reload');await ready();assert(await ev('location.hash')===route,'canonical route reload '+tab);
 }
 const studio={clubs:['Chelsea','Arsenal'],competition:'English Premier League',venue:'away',from:'2026-09-01',to:'2026-10-21',chart:'quality',window:'5',detail:'Chelsea'};
 await nav({section:'explore',tab:'Performance Studio',studio:JSON.stringify(studio)});await wait(`Boolean(document.querySelector('#club-chart')&&document.querySelector('#studio-detail'))`);
 assert(await ev(`WORKSPACE_SECTION==='clubs'&&document.querySelector('[data-workspace=clubs]').getAttribute('aria-current')==='page'&&CLUB_VIEW==='compare'&&CLUB_COMPARE.join('|')==='Chelsea|Arsenal'&&CLUB_VENUE==='away'&&CLUB_CHART==='quality'&&document.querySelector('#club-chart').value==='quality'&&document.querySelectorAll('[data-chart-picker]').length===1&&!document.querySelector('#studio-chart')&&!document.querySelector('#studio-venue')&&document.querySelector('#club-compare-scope').value==='English Premier League'`),'Studio legacy state in Clubs');
 await ev(`document.querySelector('[data-workspace=home]').click()`);await ready();await call('Page.reload');await ready();assert(await ev(`WORKSPACE_SECTION==='home'&&MATCHES_VIEW==='agenda'`),'Home after Studio survives reload');
 await nav({section:'explore',tab:'Performance Studio',studio:JSON.stringify(studio)});await wait(`Boolean(document.querySelector('#club-chart')&&document.querySelector('#studio-detail'))`);
 const studioRoute=await ev('location.hash');await ev(`document.querySelector('#club-back-directory').click()`);await ready();await ev('history.back()');await wait(`Boolean(document.querySelector('#club-chart')&&document.querySelector('#studio-detail'))`);assert(await ev('location.hash')===studioRoute,'Clubs Back exact analysis');
 await nav({section:'explore',tab:'Big matches',big:'season'});assert(await ev(`WORKSPACE_SECTION==='home'&&MATCHES_VIEW==='stakes'&&BIGMODE==='season'`),'legacy Big matches Home');
 await ev(`document.querySelector('[data-workspace=clubs]').click()`);await ready();await call('Page.reload');await ready();assert(await ev(`WORKSPACE_SECTION==='clubs'&&Boolean(document.querySelector('#workspace-club-search'))`),'Clubs after Big matches survives reload');
 await nav({section:'races',tab:'English Premier League',view:'gw',round:'10'});assert(await ev(`viewOf(TAB)==='gw'&&GWSEL[TAB]===10&&document.querySelectorAll('#vsel optgroup').length===5`),'grouped competition picker retains Gameweek round');
 await change('vsel','fx');assert(await ev(`viewOf(TAB)==='fx'`),'Fixtures distinct from Gameweek');
 await nav({section:'explore',tab:'Visualisations',viz:'ratings',of:'English Premier League',dw:'1m'});
 await ev(`document.querySelector('#workspace-saved').open=true;document.querySelector('#workspace-view-name').value='Consolidation route check';document.querySelector('#workspace-save').click()`);
 await wait(`Boolean([...document.querySelectorAll('[data-saved-view]')].find(e=>e.textContent==='Consolidation route check'))`);
 await ev(`document.querySelector('[data-workspace=home]').click();[...document.querySelectorAll('[data-saved-view]')].find(e=>e.textContent==='Consolidation route check').click()`);await ready();assert(await ev(`VIZSEL==='ratings'&&RATSEL==='English Premier League'&&DWIN==='1m'`),'saved analysis restore');
 await ev(`const e=[...document.querySelectorAll('[data-saved-view]')].find(e=>e.textContent==='Consolidation route check');document.querySelector('[data-remove-view="'+e.dataset.savedView+'"]').click()`);await ready();
 for(const viz of ['xa','ls','depth','ratings','tr','concentration','trophies','changes','congestion']){
  timings.push({viz,ms:await change('all-chart-select',viz)});
  for(const width of [1440,960,390])for(const theme of ['light','dark']){
   await call('Emulation.setDeviceMetricsOverride',{width,height:1100,deviceScaleFactor:1,mobile:false});await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:theme}]});await ev(`document.documentElement.dataset.theme='${theme}';scrollTo(0,0)`);
   const d=await ev(`(()=>{const visible=e=>Boolean(e.getClientRects().length);return {overflow:document.documentElement.scrollWidth-innerWidth,theme:getComputedStyle(document.documentElement).colorScheme,choices:document.querySelectorAll('#mobile-nav option').length,pickers:document.querySelectorAll('[data-chart-picker]').length,unlabelled:[...document.querySelectorAll('#view select,#view input')].filter(visible).filter(e=>!e.labels?.length&&!e.getAttribute('aria-label')).map(e=>e.id),tables:[...document.querySelectorAll('#view table')].map(t=>({head:t.tHead.rows[0].cells.length,rows:[...t.tBodies[0].rows].map(r=>r.cells.length)}))};})()`);
   assert(d.overflow<=1&&d.theme===theme&&d.choices===3&&d.pickers===1&&!d.unlabelled.length,'layout/picker/labels '+viz+' '+width+' '+theme);assert(d.tables.every(t=>t.rows.every(n=>n===t.head)),'table shape '+viz);await shot(viz+'-'+width+'-'+theme);observations.push({viz,width,theme,...d});
  }
 }
 // Missing fields must keep the bookmarked question and explain its unavailability.
 await ev(`window.savedRatings=RESULT.ratings;window.savedTrophies=RESULT.trophies;delete RESULT.ratings;delete RESULT.trophies;VIZSEL='ratings';drawAllViz()`);assert(await ev(`document.querySelector('#all-chart-select').value==='ratings'&&document.querySelector('#all-analysis').textContent.includes('unavailable')`),'missing historical ratings retains question');
 await ev(`VIZSEL='trophies';drawAllViz()`);assert(await ev(`document.querySelector('#all-chart-select').value==='trophies'&&document.querySelector('#all-analysis').textContent.includes('unavailable')`),'missing historical trophy field retains question');await ev(`RESULT.ratings=window.savedRatings;RESULT.trophies=window.savedTrophies;drawAllViz()`);
 // A visible source/pipeline failure must stay outside the closed operations disclosure.
 await ev(`META.pipeline={date:'2026-10-22',ok:0,steps:[{step:'fixture-check',status:'failed',detail:'Deliberate review fault'}]};renderHealth()`);
 assert(await ev(`document.querySelector('#health [role=alert]').textContent.includes('Deliberate review fault')&&!document.querySelector('#run-data').open`),'visible deliberate pipeline failure');
 // Deliberately re-add a retired destination: the navigation acceptance predicate must fail.
 assert(await ev(`(()=>{const p=()=>document.querySelectorAll('#tabs [data-t]').length===3,b=document.createElement('button');b.dataset.t='Ratings';document.querySelector('#tabs').append(b);const detected=!p();b.remove();return detected&&p();})()`),'deliberate duplicate destination rejected');
 assert(!exceptions.length,'browser exceptions');assert(!(await(await fetch(app+'/api/meta')).json()).model_loaded,'read navigation loaded model');
 console.log(JSON.stringify({checks,dir,timings,observations,exceptions},null,2));
}finally{ws.close();await fetch(cdp+'/json/close/'+target.id);}
