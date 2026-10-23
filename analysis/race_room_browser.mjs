// Optional isolated Chrome/CDP review. No model, production data writes, or owner's browser.
// node analysis/race_room_browser.mjs /private/tmp/race-review.json [CDP URL] [review server URL]
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
const args=process.argv.slice(2),published=args.includes('--published');
const [file,cdp='http://127.0.0.1:9231',app='http://127.0.0.1:8766']=args.filter(v=>v!=='--published');
if(!file)throw Error('Pass the review artifact created by race_room_audit.py');
const review=JSON.parse(readFileSync(file,'utf8'));if(!review.review_only)throw Error('Expected a review-only artifact');
const directory='/private/tmp/football-race-browser-'+Date.now();mkdirSync(directory);
const targets=await(await fetch(cdp+'/json')).json(),target=targets.find(t=>t.type==='page');
const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
let sequence=0;const pending=new Map(),exceptions=[];
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')exceptions.push(m.params.exceptionDetails);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}};
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
const wait=async expression=>{for(let i=0;i<200;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Timed out: '+expression);};
let checks=0;const assert=(ok,label)=>{if(!ok)throw Error(label);checks++;console.log('PASS '+label);};
const shot=async name=>{const r=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});writeFileSync(directory+'/'+name+'.png',Buffer.from(r.data,'base64'));};
try{
 await call('Page.enable');await call('Runtime.enable');await call('Page.bringToFront');
 await call('Page.navigate',{url:app+'/?race-review='+Date.now()+'#section=races&tab=English+Premier+League&view=viz&viz=rivals&date=2026-10-21'});
 await wait(`Boolean(document.getElementById('vizbody')?.innerText.includes('no full-world rival evidence'))`);
 assert(await ev(`document.getElementById('chart-select').value==='rivals'&&!document.querySelector('[data-rival-matrix]')`),'old stored snapshot shows missing evidence');
 await call('Page.navigate',{url:app+'/?race-published='+Date.now()+'#section=races&tab=English+Premier+League&view=viz&viz=rivals&date=2026-10-22'});
 await wait(`Boolean(document.querySelector('[data-rival-matrix]'))`);
 assert(await ev(`document.querySelectorAll('[data-rival-pair]').length===380&&RESULT.version>=13&&RESULT.worlds===10000`),'published latest snapshot has20-club10,000-world matrix');
 if(published)assert(await ev(`RESULT.version===14&&JSON.stringify(RESULT.leagues.find(b=>b.competition==='English Premier League').entry_routes)===JSON.stringify(${JSON.stringify(review.block.entry_routes)})`),'payload14 route evidence equals published API bytes');
 await ev(`(async()=>{window.__raceReviewBlock=${JSON.stringify(review.block)};await drawViz(window.__raceReviewBlock,'league');document.getElementById('cview').insertAdjacentHTML('afterbegin','<p class="note" id="race-review-label"><b>${published?'Published Race Room':'Review only'}</b> · ${review.report.worlds.toLocaleString('en-GB')}-world ${published?'published evidence':'accounting experiment'} · ${published?'latest payload 14':'production snapshots unchanged'}</p>');})()`);
 assert(await ev(`document.querySelectorAll('[data-rival-pair]').length===380&&document.querySelectorAll('#chart-select').length===1`),'20-club full-world matrix and one native Chart picker');
 await ev(`document.querySelector('[data-chart-options]').open=true;const el=document.getElementById('chart-opt-rivalTeam');el.value='Arsenal';el.focus();el.dispatchEvent(new Event('change'));`);
 assert(await ev(`document.activeElement.id==='chart-opt-rivalTeam'&&readHash().rival==='Arsenal'`),'native club selector retains focus and URL identity');
 await ev(`(()=>{const el=document.getElementById('chart-opt-rivalOpponent');el.value='Man City';el.focus();el.dispatchEvent(new Event('change'));})()`);
 assert(await ev(`document.activeElement.id==='chart-opt-rivalOpponent'&&readHash().rivalopponent==='Man City'`),'native rival selector retains focus and URL identity');
 assert(await ev(`(()=>{const a=VIZOPT.rivalTeam,b=VIZOPT.rivalOpponent;VIZOPT.rivalTeam='';VIZOPT.rivalOpponent='';applyHash();return VIZOPT.rivalTeam===a&&VIZOPT.rivalOpponent===b;})()`),'saved pair restores from URL');
 const timings=[];
 for(const width of [1440,960,390]){
  await call('Emulation.setDeviceMetricsOverride',{width,height:1100,deviceScaleFactor:1,mobile:false});
  for(const theme of ['light','dark']){
   await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:theme}]});
   await ev(`document.documentElement.dataset.theme='${theme}';document.getElementById('race-review-label')?.remove();document.getElementById('cview').insertAdjacentHTML('afterbegin','<p class="note" id="race-review-label"><b>${published?'Published Race Room':'Review only'}</b> · ${review.report.worlds.toLocaleString('en-GB')}-world ${published?'published evidence':'accounting experiment'} · ${published?'latest payload 14':'production snapshots unchanged'}</p>');window.scrollTo(0,0);`);
   assert(await ev(`document.documentElement.scrollWidth<=innerWidth+1`),`${width} ${theme}:wide matrix stays inside panel`);
   assert(await ev(`getComputedStyle(document.documentElement).colorScheme==='${theme}'`),`${width} ${theme}:actual CSS theme verified`);
   await ev(`document.getElementById('vizbody').scrollIntoView({block:'start'})`);
   await shot(`${width}-${theme}-matrix`);
   timings.push(await ev(`(()=>{const cell=document.getElementById('rival-cell-0-1'),wrap=cell.closest('.scroll');wrap.scrollLeft=200;const before=wrap.scrollLeft,start=performance.now();cell.click();return {width:${width},theme:'${theme}',ms:performance.now()-start,focus:document.activeElement.id,scroll:document.querySelector('[data-rival-matrix]').parentElement.scrollLeft,before};})()`));
   assert(timings.at(-1).focus==='rival-cell-0-1'&&timings.at(-1).scroll===timings.at(-1).before,`${width} ${theme}:matrix pair click retains focus and local scroll`);
   await ev(`document.querySelector('[data-rival-distribution]').open=true;document.querySelector('[data-rival-distribution]').scrollIntoView({block:'start'});`);
   assert(await ev(`document.querySelectorAll('[data-rival-table] tbody tr').length===19&&document.querySelector('[data-rival-distribution]').textContent.includes('Worlds')`),`${width} ${theme}:19 readable rivals and exact gap sample counts`);
   await shot(`${width}-${theme}-detail`);
  }
 }
 if(review.gw){
  await ev(`window.__raceReviewGw=${JSON.stringify(review.gw)};GW={worlds:${review.report.worlds},leagues:{'English Premier League':window.__raceReviewGw},phases:{}};`);
  for(const chart of ['entryroutes','timing']){
   await ev(`(async()=>{VIZSEL='${chart}';await drawViz(window.__raceReviewBlock,'league');})()`);
   const selector=chart==='timing'?'timingRound':'routeTeam';
   assert(await ev(`!document.querySelector('#vizbody [role="alert"]')&&document.getElementById('chart-opt-${selector}')!==null`),`${chart}:real full-world draft renders without source errors`);
   if(chart==='timing'){
    await ev(`(()=>{const el=document.getElementById('chart-opt-timingRound');el.value='35';el.focus();el.dispatchEvent(new Event('change'));})()`);
    assert(await ev(`readHash().timinground==='35'&&document.activeElement.id==='chart-opt-timingRound'&&document.querySelectorAll('[data-title-rounds] tbody tr').length===39`),'Timing:round URL,focus and39 uncertainty rows retained');
   }else{
    await ev(`(()=>{const el=document.getElementById('chart-opt-routeTeam');el.value='Arsenal';el.focus();el.dispatchEvent(new Event('change'));})()`);
    assert(await ev(`readHash().entryclub==='Arsenal'&&document.activeElement.id==='chart-opt-routeTeam'&&document.querySelectorAll('[data-entry-routes] tbody tr').length===8`),'Routes:club URL,focus and7 exclusive routes plus total retained');
   }
   for(const width of [1440,960,390]){
    await call('Emulation.setDeviceMetricsOverride',{width,height:1100,deviceScaleFactor:1,mobile:false});
    for(const theme of ['light','dark']){
     await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:theme}]});
     await ev(`document.documentElement.dataset.theme='${theme}';document.getElementById('vizbody').scrollIntoView({block:'start'});`);
     assert(await ev(`getComputedStyle(document.documentElement).colorScheme==='${theme}'&&document.documentElement.scrollWidth<=innerWidth+1`),`${chart} ${width} ${theme}:theme and local scrolling verified`);
     await shot(`${width}-${theme}-${chart}`);
    }
   }
  }
 }
 assert(exceptions.length===0,'zero browser exceptions');
 assert((await(await fetch(app+'/api/meta')).json()).model_loaded===false,'reviewing Race Room leaves model unloaded');
 console.log(JSON.stringify({checks,screenshots:directory,selector_timings:timings,exceptions},null,2));
}finally{ws.close();}
