// Optional browser audit: node analysis/dashboard_interaction_audit.mjs [--players] [CDP URL] [dashboard URL]
// Requires a separate Chromium debugging session; reads existing data, never runs a model.
const args=process.argv.slice(2),playerMode=args.includes('--players'),urls=args.filter(a=>a!=='--players'),cdp=urls[0]||'http://127.0.0.1:9229',app=urls[1]||'http://127.0.0.1:8765';
const targets=await(await fetch(cdp+'/json')).json(),target=targets.find(t=>t.type==='page');
if(!target)throw Error('Open a page in the separate debugging browser first.');
const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
let sequence=0;const pending=new Map(),exceptions=[];
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')exceptions.push(m.params.exceptionDetails);if(m.id){const p=pending.get(m.id);if(!p)return;pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}};
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
const evaluate=async expression=>{const value=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(value.exceptionDetails)throw Error(JSON.stringify(value.exceptionDetails));return value.result.value;};
try{
 await call('Page.enable');await call('Page.bringToFront');await call('Runtime.enable');await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url:app+'/?interaction-audit='+Date.now()+(playerMode?'#section=players&pview=creators&date=2026-10-22':'#section=clubs&tab=English+Premier+League&team=Arsenal&page=1&clubsection=schedule&date=2026-10-22')});
 let ready=false;for(let i=0;i<240;i++){ready=await evaluate(`Boolean(document.querySelector('${playerMode?'[data-creator]':'[data-club-schedule]'}'))`);if(ready)break;await new Promise(r=>setTimeout(r,100));}if(!ready)throw Error('Club schedule did not load.');
 const methods=playerMode?"[['creatorDiscovery',()=>WORKSPACE.creatorDiscovery(RESULT,playersPayload())],['playerDiscoveryHtml',()=>playerDiscoveryHtml()]]":"[['clubPool',()=>clubPool()],['clubCompetitions',()=>clubCompetitions('Arsenal')],['clubScheduleHtml',()=>clubScheduleHtml('Arsenal',clubPool())],['clubCentreHtml',()=>clubCentreHtml('Arsenal')]]";
 const selectors=await evaluate(`(()=>{const out={};for(const [name,fn] of ${methods}){out[name]=[];for(let i=0;i<5;i++){const t=performance.now();fn();out[name].push(performance.now()-t);}}return out;})()`);
 const changes=[];
 const control=playerMode?'player-discovery-stat':'club-section',values=playerMode?['xa','chances_created','assists','xa','chances_created','assists']:['season','schedule','performance','schedule','season','schedule'];
 for(const value of values)changes.push(await evaluate(`(async()=>{const input=document.getElementById('${control}'),t=performance.now();input.value='${value}';input.dispatchEvent(new Event('change'));const sync=performance.now()-t;const frame=await Promise.race([new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r('frames')))),new Promise(r=>setTimeout(()=>r('timeout'),2000))]);return {selection:'${value}',synchronous_milliseconds:sync,milliseconds:performance.now()-t,frame,visibility:document.visibilityState,focus:document.activeElement.id};})()`));
 const errors=[...exceptions];if(changes.some(c=>c.focus!==control||c.frame!=='frames'))errors.push('Native selector lost focus.');
 console.log(JSON.stringify({view:playerMode?'players':'clubs',units:'milliseconds',width:1440,samples:5,selector_times:selectors,native_changes_after_two_animation_frames:changes,errors},null,2));if(errors.length)process.exitCode=1;
}finally{ws.close();}
