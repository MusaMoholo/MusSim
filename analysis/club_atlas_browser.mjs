// Optional isolated browser audit: node analysis/club_atlas_browser.mjs [CDP URL] [review URL]
import {writeFileSync,mkdirSync} from 'node:fs';
const [cdp='http://127.0.0.1:9231',app='http://127.0.0.1:8766']=process.argv.slice(2),directory='/private/tmp/football-club-atlas-browser-'+Date.now();mkdirSync(directory);
const targets=await(await fetch(cdp+'/json')).json(),ws=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);
let sequence=0,checks=0;const pending=new Map(),exceptions=[];
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')exceptions.push(m.params.exceptionDetails);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}};
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
const wait=async expression=>{for(let i=0;i<240;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Timed out '+expression);};
const assert=(ok,label)=>{if(!ok)throw Error(label);checks++;console.log('PASS '+label);};
const navigate=async hash=>{await call('Page.navigate',{url:app+'/?club-atlas='+Date.now()+hash});await wait(`Boolean(document.querySelector('[data-atlas-count]'))`);};
const shot=async name=>{const s=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});writeFileSync(directory+'/'+name+'.png',Buffer.from(s.data,'base64'));};
try{
 await call('Page.enable');await call('Runtime.enable');
 await navigate('#section=explore&tab=Tactical+Atlas&team=Arsenal&at=Chelsea&acomp=English+Premier+League&aside=against&achart=density&against=Arsenal&date=2026-10-22');
 assert(await ev(`WORKSPACE_SECTION==='clubs'&&TEAM_PAGE&&FOCUS==='Chelsea'&&CLUB_SECTION==='atlas'&&ATLAS_SIDE==='against'&&ATLAS_CHART==='density'&&ATLAS_COMPARE==='Arsenal'`),'old Explore Atlas link redirects to exact club and filters');
 assert(await ev(`readHash().section==='clubs'&&readHash().clubsection==='atlas'&&readHash().tab!=='Tactical Atlas'&&!readHash().viz&&!document.getElementById('atlas-team')&&!document.getElementById('atlas-comp')&&document.getElementById('club-scope').value==='English Premier League'`),'canonical club URL and one owner for club/competition controls');
 await ev(`(()=>{const el=document.getElementById('club-scope');el.value='all';el.focus();el.dispatchEvent(new Event('change'));})()`);await wait(`Boolean(document.querySelector('[data-atlas-count]')&&ATLAS_COMP==='all')`);
 assert(await ev(`document.activeElement.id==='club-scope'&&readHash().acomp==='all'&&!readHash().viz`),'competition change keeps focus and does not revive legacy chart scope');
 await ev(`(()=>{const el=document.getElementById('atlas-chart');el.value='atlas';el.focus();el.dispatchEvent(new Event('change'));})()`);await wait(`Boolean(document.querySelector('[data-atlas-count]')&&ATLAS_CHART==='atlas')`);
 assert(await ev(`document.activeElement.id==='atlas-chart'&&readHash().achart==='atlas'`),'native Atlas chart retains focus and saves club route');
 await ev(`(()=>{const el=document.getElementById('atlas-side');el.value='for';el.focus();el.dispatchEvent(new Event('change'));})()`);await wait(`Boolean(document.querySelector('[data-atlas-count]')&&ATLAS_SIDE==='for')`);
 assert(await ev(`document.activeElement.id==='atlas-side'&&readHash().aside==='for'&&document.querySelectorAll('[data-atlas-team]').length===2`),'For/Against control and opposite-side comparison retained');
 const saved=await ev('location.hash');
 await ev(`(()=>{const el=document.getElementById('club-section');el.value='season';el.focus();el.dispatchEvent(new Event('change'));})()`);await wait(`Boolean(document.querySelector('[data-club-competition]'))`);
 await ev(`(async()=>{history.pushState(null,'',${JSON.stringify(saved)});await restoreWorkspaceRoute();})()`);
 await wait(`Boolean(document.querySelector('[data-atlas-count]'))`);
 assert(await ev(`CLUB_SECTION==='atlas'&&FOCUS==='Chelsea'&&ATLAS_SIDE==='for'&&ATLAS_COMPARE==='Arsenal'`),'saved club Atlas route restores section,club and filters');
 await navigate('#section=races&tab=German+Bundesliga&view=viz&viz=density&aside=against&date=2026-10-22');
 assert(await ev(`WORKSPACE_SECTION==='clubs'&&CLUB_SCOPE==='German Bundesliga'&&ATLAS_CHART==='density'&&RESULT.leagues.find(b=>b.competition==='German Bundesliga').teams.some(t=>t.team===FOCUS)&&!readHash().viz`),'old competition chart chooses a covered club and preserves competition/chart');
 await navigate('#section=clubs&tab=English+Premier+League&team=Arsenal&page=1&clubsection=atlas&achart=density&date=2026-10-22');
 for(const width of [1440,960,390]){
  await call('Emulation.setDeviceMetricsOverride',{width,height:1100,deviceScaleFactor:1,mobile:false});
  for(const theme of ['light','dark']){
   await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:theme}]});
   await ev(`document.documentElement.dataset.theme='${theme}';document.querySelector('[data-atlas-root]').closest('.panel').scrollIntoView({block:'start'});`);
   assert(await ev(`getComputedStyle(document.documentElement).colorScheme==='${theme}'&&document.documentElement.scrollWidth<=innerWidth+1&&document.querySelector('[data-atlas-count]').dataset.atlasCount>0`),`${width} ${theme}:club Atlas has nonempty evidence and no page overflow`);
   await shot(`${width}-${theme}-atlas`);
  }
 }
 await ev(`chooseWorkspaceSection('explore')`);await wait(`WORKSPACE_SECTION==='explore'`);
 assert(await ev(`TAB!=='Tactical Atlas'&&!document.querySelector('[data-t="Tactical Atlas"]')&&!document.querySelector('[data-atlas-root]')`),'Explore has no duplicate Atlas destination');
 assert(await ev(`vizGroups('league').every(([,a])=>a.every(([k])=>!['atlas','density'].includes(k)))`),'competition Chart picker has no duplicate Atlas entries');
 assert(!exceptions.length,'zero browser exceptions');
 console.log(JSON.stringify({checks,screenshots:directory,exceptions},null,2));
}finally{ws.close();}
