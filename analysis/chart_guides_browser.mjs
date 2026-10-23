// Read-only chart-guide checks on an agent-owned review server and browser profile.
import {mkdirSync,writeFileSync} from 'node:fs';
const [cdp='http://127.0.0.1:9234',app='http://127.0.0.1:8768',date='2026-10-22']=process.argv.slice(2);
const dir='/private/tmp/football-chart-guides-browser-'+Date.now();mkdirSync(dir);
const target=await(await fetch(cdp+'/json/new?'+encodeURIComponent(app),{method:'PUT'})).json();
const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);
let seq=0,checks=0;const pending=new Map(),exceptions=[],observations=[];
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')exceptions.push(m.params.exceptionDetails);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}};
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
const assert=(ok,m)=>{checks++;if(!ok)throw Error(m);};
const wait=async expression=>{for(let i=0;i<300;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Timeout '+expression);};
try{
 await call('Page.enable');await call('Runtime.enable');
 const cases=[['all',{section:'explore',tab:'Visualisations',viz:'xa'},true],['league',{section:'races',tab:'English Premier League',view:'viz',viz:'ad'},true],['uefa',{section:'races',tab:'UEFA Champions League',view:'viz',viz:'ad'},true],['quality',{section:'races',tab:'English Premier League',view:'viz',viz:'sq'}],['goals',{section:'races',tab:'English Premier League',view:'viz',viz:'gx'}],['points',{section:'races',tab:'English Premier League',view:'viz',viz:'xp'}],['elo',{section:'races',tab:'English Premier League',view:'viz',viz:'ev'}],['trophy',{section:'races',tab:'UEFA Champions League',view:'viz',viz:'sw'}]];
 for(const [name,params,profile] of cases){
  await call('Page.navigate',{url:app+'/?chart-guide='+name+'#'+new URLSearchParams({date,...params})});
  await wait(`Boolean(document.querySelector('#vizbody svg,#competition-evidence-plot svg'))`);
  if(profile){
   const data=await ev(`(()=>{const line=document.querySelector('.profile-guide line'),tips=[...document.querySelectorAll('#view .hit')].map(e=>e.dataset.tip);return {sum:Number(line?.dataset.profileSum),x1:Number(line?.getAttribute('x1')),x2:Number(line?.getAttribute('x2')),y1:Number(line?.getAttribute('y1')),y2:Number(line?.getAttribute('y2')),tips:tips.length,all:tips.every(t=>t.includes('profile')&&t.includes('vs plotted clubs')),expected:${name==='all'?`RESULT.ratings.teams.filter(r=>r.league).reduce((n,r)=>n+r.att+r.def,0)/RESULT.ratings.teams.filter(r=>r.league).length`:`(()=>{const b=[...RESULT.leagues,...RESULT.uefa].find(b=>b.competition===TAB),r=b.teams.map(t=>onScale(ratingIdx()[t.team],TAB)).filter(Boolean);return r.reduce((n,t)=>n+t.att+t.def,0)/r.length})()`}}})()`);
   assert(data.tips>0&&data.all&&Math.abs(data.sum-data.expected)<1e-10&&data.x2>data.x1&&data.y2<data.y1,'independent source mean / rising guide / every tooltip '+name);
   const thresholds=await ev(`(()=>{const rows=${name==='all'?`RESULT.ratings.teams.filter(r=>r.league)`:`[...RESULT.leagues,...RESULT.uefa].find(b=>b.competition===TAB).teams.map(t=>onScale(ratingIdx()[t.team],TAB)).filter(Boolean)`},sums=rows.map(r=>r.att+r.def),mean=sums.reduce((n,v)=>n+v,0)/sums.length,sd=Math.sqrt(sums.reduce((n,v)=>n+(v-mean)**2,0)/sums.length);return {mean,sd,guides:[...document.querySelectorAll('.profile-guide line')].map(e=>({sum:+e.dataset.profileSum,sigma:+e.dataset.profileSigma})),hasTilt:[...document.querySelectorAll('#view .hit')].every(e=>e.dataset.tip.includes('Profile tilt')&&!e.dataset.tip.includes('NaN'))}})()`);
   assert(thresholds.sd>0&&thresholds.guides.length===3&&thresholds.hasTilt&&new Set(thresholds.guides.map(g=>g.sigma)).size===3&&thresholds.guides.every(g=>Math.abs(g.sum-thresholds.mean-g.sigma*thresholds.sd)<1e-10),'independent outer SD thresholds '+name);
   observations.push({name,...data,thresholds});
  }
  for(const width of [1440,960,390])for(const theme of ['light','dark']){
   await call('Emulation.setDeviceMetricsOverride',{width,height:1100,deviceScaleFactor:1,mobile:false});await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:theme}]});await ev(`document.documentElement.dataset.theme='${theme}';scrollTo(0,0)`);
   const layout=await ev(`new Promise(resolve=>requestAnimationFrame(()=>resolve({overflow:document.documentElement.scrollWidth-innerWidth,theme:getComputedStyle(document.documentElement).colorScheme})))`);
   assert(layout.overflow<=1&&layout.theme===theme,'layout '+name+' '+width+' '+theme+' '+JSON.stringify(layout));
   const shot=await call('Page.captureScreenshot',{format:'png'});writeFileSync(dir+'/'+name+'-'+width+'-'+theme+'.png',Buffer.from(shot.data,'base64'));
  }
 }
 // Observed xG uses xGD guides, keeping the model-only NET label out of this chart.
 await ev(`VIZSEL='ad';VIZOPT.src='real';TAB='English Premier League';drawViz(RESULT.leagues.find(b=>b.competition===TAB),'league')`);
 await wait(`Boolean(document.querySelector('.profile-guide'))`);
 assert(await ev(`document.querySelector('#vizbody').textContent.includes('xGD')&&!document.querySelector('#vizbody').textContent.includes('NET')`),'observed xG guide units');
 assert(exceptions.length===0,'no browser exceptions');
 console.log(JSON.stringify({checks,dir,observations,exceptions},null,2));
}finally{await call('Page.close').catch(()=>{});ws.close();}
