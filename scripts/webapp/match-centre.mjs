// Match evidence views/selectors. Source normalization and cutoff gates live on the read server.
import {esc,pct,kickoffLabel,followingScope,clubId,fixtureInstant} from './workspace.mjs';
export const SECTIONS=[['preview','Preview'],['timeline','Timeline'],['chances','Chances'],['impact','Season impact']];
export const fixtureKey=f=>[f.home,f.away,f.kickoff.slice(0,10)].join('|');
export const ukDay=(value,competition='')=>new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/London',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(fixtureInstant(value,competition)));
export function agendaRows(result,data,players,badges,following,options={}){
 const {period='week',competition='all',scope='all',date=''}=options,cutoff=result.as_of,follow=followingScope(result,players,following,badges);
 const shift=days=>new Date(Date.parse(cutoff+'T00:00:00Z')+days*86400000).toISOString().slice(0,10);
 return (data?.fixtures||[]).filter(f=>{
  const day=f.kickoff.slice(0,10);
  if(competition!=='all'&&f.competition!==competition)return false;
  if(scope==='following'&&(!follow.active||!(follow.clubs.has(clubId(f.home,badges))||follow.clubs.has(clubId(f.away,badges))||follow.races.some(r=>r.competition===f.competition))))return false;
  if(period==='day')return ukDay(f.kickoff,f.competition)===date;
  if(period==='recent')return Boolean(f.result)&&day<=cutoff&&day>shift(-7);
  return !f.result&&day>cutoff&&(period==='season'||day<=shift(period==='month'?30:7));
 }).sort((a,b)=>fixtureInstant(a.kickoff,a.competition)-fixtureInstant(b.kickoff,b.competition)||a.competition.localeCompare(b.competition)||a.home.localeCompare(b.home)||a.away.localeCompare(b.away));
}
export function replayFrames(facts){
 const times=new Map([[0,{order:0,label:'Start'}]]);
 for(const row of [...(facts?.events||[]),...(facts?.shots||[])])times.set(row.order,{order:row.order,label:row.label});
 return [...times.values()].sort((a,b)=>a.order-b.order);
}
export function atFrame(facts,order=Infinity){
 const events=(facts?.events||[]).filter(e=>e.order<=order),shots=(facts?.shots||[]).filter(s=>s.order<=order),goals=[0,0],xg=[0,0],unknown=[0,0];
 for(const e of events)if(e.type==='Goal'&&e.side)goals[e.side==='home'?0:1]++;
 for(const s of shots)if(!s.own_goal){const i=s.side==='home'?0:1;if(s.xg==null)unknown[i]++;else xg[i]+=s.xg;}
 return {events,shots,goals,xg,unknown};
}
export function eventLabel(e){
 if(e.type==='Substitution')return (e.swap||[]).map(p=>p.name).filter(Boolean).join(' ↔ ')||'Substitution';
 if(e.type==='Card')return [e.player,e.card?e.card+' card':'Card'].filter(Boolean).join(' · ');
 if(e.type==='Goal')return e.player+(e.own_goal?' · own goal':' · goal')+(!e.own_goal&&e.assist?.name?' · assist '+e.assist.name:'');
 return [e.player,e.text||e.type].filter(Boolean).join(' · ');
}
export function headerHtml(data,section,{label=c=>c,badge=()=>'',selected=Infinity}={}){
 const f=data.fixture,coverage=data.facts?.coverage,score=f.result?f.result.join('–'):'v',pens=data.facts?.shootout_score;
 return `<div class="panel centre-header"><div class="home-section-head"><div><div class="eyebrow">MATCH CENTRE</div><h2>${badge(f.home)}<button class="text-button" data-team="${esc(f.home)}">${esc(f.home)}</button> <span class="centre-score">${score}</span> ${badge(f.away)}<button class="text-button" data-team="${esc(f.away)}">${esc(f.away)}</button></h2></div><button class="ghost" id="centre-back">Back to Home</button></div>
 <p class="note"><b>${esc(label(f.competition))}</b> · ${esc(kickoffLabel(f.kickoff,f.competition))} · ${data.mode==='played'?'recorded result'+(f.outcome==='afterextratime'?' after extra time':f.outcome==='penalties'?' before shootout':''):'forecast preview'}${pens?' · shootout '+pens.join('–'):''}</p>
 <p class="note">Snapshot ${esc(data.snapshot)} · data through ${esc(data.as_of)}${data.evidence?' · retained match evidence':''}</p>
 ${data.facts?.issues?.length?`<p class="note zbad" role="alert">${data.facts.issues.map(esc).join(' · ')}</p>`:''}
 <div class="centre-coverage">${[['timeline','Events'],['shotmap','Shots'],['lineup','Lineups'],['players','Players']].map(([key,name])=>`<span class="pill ${coverage?.[key]?'on':''}">${name}: ${coverage?.[key]?'covered':data.mode==='preview'?'after play':'unavailable'}</span>`).join('')}</div>
 <div class="row centre-sections"><div><label for="centre-section">Section</label><select id="centre-section">${SECTIONS.map(([id,name])=>`<option value="${id}"${section===id?' selected':''}${data.mode==='preview'&&!['preview','impact'].includes(id)?' disabled':''}>${name}</option>`).join('')}</select></div></div></div>`;
}
export function shotPosition(shot){
 // Source y rises from the lower touchline; SVG y rises down the page.
 // Convert that axis first, then rotate away shots through 180 degrees.
 return shot.side==='away'?{x:105-shot.x,y:shot.y}:{x:shot.x,y:68-shot.y};
}
export function pitchHtml(data,order,colors){
 const shots=atFrame(data.facts,order).shots,positioned=shots.filter(s=>s.x!=null&&s.y!=null),f=data.fixture;
 const marks=positioned.map(s=>{const p=shotPosition(s),assist=s.goal&&!s.own_goal?(data.facts.events||[]).find(e=>e.type==='Goal'&&!e.own_goal&&e.shot_id===s.id&&e.side===s.side)?.assist:null;return `<g data-pitch-x="${p.x}" data-pitch-y="${p.y}" data-shot-side="${s.side}" data-replay-order="${s.order}" data-shot="${esc(s.id)}" role="button" tabindex="0" data-keyboard-action="shot" data-tip="${esc('<b>'+esc(s.player)+'</b> · '+s.label+'<br>'+esc(s.own_goal?'Own goal':s.outcome||'Shot')+(assist?.name?'<br>Assist · '+esc(assist.name):'')+' · shot xG '+(s.xg==null?'unavailable':s.xg.toFixed(3)))}"><circle cx="${p.x}" cy="${p.y}" r="${s.goal?1.6:1.1}" fill="${colors[s.side==='home'?0:1]}" stroke="${s.goal?'var(--ink)':'var(--panel)'}" stroke-width="${s.goal?.6:.25}"/><circle cx="${p.x}" cy="${p.y}" r="3" fill="transparent"/></g>`;}).join('');
 return `<p class="note"><b>Shot positions</b> · ${positioned.length}/${shots.length} located · goals outlined · goal assists in tooltips · own goals included</p><div class="pitch-key"><span style="color:${colors[1]}">← ${esc(f.away)} <small>attacks left</small></span><span style="color:${colors[0]}">${esc(f.home)} → <small>attacks right</small></span></div>
 <svg class="match-pitch" viewBox="-3 -3 111 74" role="img" aria-label="Shot positions at replay cutoff; home attacks right, away attacks left"><rect width="105" height="68" rx=".4"/><path d="M-1.8 30.34H0M-1.8 30.34V37.66H0M106.8 30.34H105M106.8 30.34V37.66H105M52.5 0V68M0 13.84H16.5V54.16H0M105 13.84H88.5V54.16H105M0 24.84H5.5V43.16H0M105 24.84H99.5V43.16H105"/><circle cx="52.5" cy="34" r="9.15"/>${marks}</svg>`;
}
export function replayHtml(data,index,colors){
 if(!data.facts?.coverage.timeline&&!data.facts?.coverage.shotmap)return '<div class="panel"><p class="note">Replay unavailable: no retained events or shot map.</p></div>';
 const frames=replayFrames(data.facts),at=Math.min(Math.max(index,0),frames.length-1),frame=frames[at],value=atFrame(data.facts,frame.order);
 const facts=data.facts,score=!facts.coverage.timeline?'Goal events unavailable':(facts.coverage.goals_reconcile?'Score at cutoff':'Recorded goal events')+' '+value.goals.join('–');
 return `<div class="panel" data-match-replay="${frame.order}"><div class="home-section-head"><h2>${esc(frame.label)}${frame.label==='Start'?'':"′"}</h2><span class="note">${score} · ${facts.coverage.shotmap?'known shot xG '+value.xg.map(v=>v.toFixed(2)).join('–'):'shot xG unavailable'}</span></div>
 <label for="centre-replay">Replay cutoff · match-minute steps</label><input id="centre-replay" class="replay-slider" type="range" min="0" max="${frames.length-1}" value="${at}" aria-valuetext="${esc(frame.label)} minutes">
 <div class="row"><button class="ghost" data-replay-step="-1"${at===0?' disabled':''}>Previous</button><button class="ghost" data-replay-step="1"${at===frames.length-1?' disabled':''}>Next</button><button class="ghost" data-replay-end${at===frames.length-1?' disabled':''}>Full match</button></div>
 <p class="note">Clock order keeps added time within its half · shootouts excluded · source order within a minute is unknown${value.unknown.some(Boolean)?' · '+value.unknown.join('/')+' home/away shots missing xG':''}</p>
 <div class="centre-replay-grid"><div>${facts.coverage.shotmap?pitchHtml(data,frame.order,colors):'<p class="note">Shot positions unavailable: no retained shot map.</p>'}</div><div class="centre-event-list"><h3>Events</h3>${value.events.map(e=>`<button class="event-row ${e.type==='Goal'?'event-goal':''}" data-replay-order="${e.order}" data-event="${esc(e.id)}"><b>${esc(e.label)}′</b><span>${esc(eventLabel(e))}</span><small>${esc(e.side?data.fixture[e.side]:'')}</small></button>`).join('')||'<p class="note">No recorded events by this cutoff.</p>'}</div></div></div>`;
}
export function timelineHtml(data,index,colors){return replayHtml(data,index,colors)+playersHtml(data);}
export function playersHtml(data){
 if(!data.facts?.coverage.players)return '<div class="panel"><p class="note">Player evidence unavailable for this match.</p></div>';
 const f=data.facts;
 return `<div class="panel centre-players" id="centre-players"><h2>Players & lineups</h2><p class="note"><b>Full-match stats</b> · independent of replay cutoff · xG includes penalties · xA expected assists · — unavailable · bench minutes are not inferred · goals exclude own goals and shootouts</p><div class="centre-player-grid">${['home','away'].map(side=>`<section><h3>${esc(data.fixture[side])}${f.formations[side]?' · '+esc(f.formations[side]):''}</h3><div class="scroll"><table><thead><tr><th class="team">Player</th><th>MIN</th><th>Goals</th><th>xG</th><th>Assists</th><th>xA</th><th>Shots</th></tr></thead><tbody>${f.players.filter(p=>p.side===side).sort((a,b)=>Number(b.starter)-Number(a.starter)||a.name.localeCompare(b.name)||a.id.localeCompare(b.id)).map(p=>`<tr data-match-player="${esc(p.id)}"><td class="team"><button class="text-button" data-player="${esc(p.id)}">${esc(p.name)}</button><small class="note">${p.starter===true?' · Starter':p.starter===false?' · Bench':''}</small></td>${['minutes','goals','xg','assists','xa','shots'].map(k=>`<td data-match-player-stat="${k}" data-value="${p[k]??''}">${p[k]==null?'—':['xg','xa'].includes(k)?p[k].toFixed(2):p[k]}</td>`).join('')}</tr>`).join('')}</tbody></table></div></section>`).join('')}</div></div>`;
}
export function curveData(data,{code=team=>team}={}){
 const facts=data.facts,frames=replayFrames(facts),names=[data.fixture.home,data.fixture.away];
 const goals=(facts?.events||[]).filter(e=>e.type==='Goal'&&['home','away'].includes(e.side)).map(e=>{
  const team=data.fixture[e.side],score=atFrame(facts,e.order).goals.join('–'),scoreLabel=score.replaceAll('–','-')+' · '+names.map(code).join('-'),label=e.label+'′ · '+e.player+(e.own_goal?' · own goal':' · goal')+' · '+team+' · '+scoreLabel;
  return {id:e.id,team,index:frames.findIndex(f=>f.order===e.order),text:score,label,tip:'<b>'+esc(team)+'</b><br>'+esc(e.label)+'′ · '+esc(e.player)+(e.own_goal?' · own goal':' · goal')+(!e.own_goal&&e.assist?.name?'<br>Assist · '+esc(e.assist.name):'')+'<br>'+esc(scoreLabel)};
 });
 return {goals,frames,labels:frames.map((f,i)=>i===0?'Start':i===frames.length-1||i%8===0?f.label:''),
  vals:new Map(names.map((name,i)=>[name,frames.map(f=>atFrame(facts,f.order).xg[i])]))};
}
export function viewingPlan(rows,selected){
 const choices=rows.filter(f=>selected.has(f.id)).sort((a,b)=>fixtureInstant(a.kickoff,a.competition)-fixtureInstant(b.kickoff,b.competition)||a.id.localeCompare(b.id));
 return choices.map((f,i)=>({...f,clash:choices.some((other,j)=>i!==j&&Math.abs(fixtureInstant(f.kickoff,f.competition)-fixtureInstant(other.kickoff,other.competition))<120*60000)}));
}

// Read the realised outcome from retained pre-match counts/ladder, never fit a new distribution.
export function realisedForecast(data){
 const actual=data.fixture,pre=data.pre_match,f=pre?.fixture;
 if(!actual.result||!f?.ladder)return null;
 const competition=actual.competition||'',cup=/Cup|Copa|Coppa|Pokal|Coupe/.test(competition),unknownBasis=cup&&pre.payload<11&&f.score_basis!=='90min';
 let score=actual.result;
 if(['afterextratime','penalties'].includes(actual.outcome)){
  if(!data.facts?.coverage.timeline||!data.facts.coverage.goals_reconcile)score=null;
  else{score=[0,0];for(const e of data.facts.events)if(e.type==='Goal'&&['FirstHalf','SecondHalf'].includes(e.period)&&e.side)score[e.side==='home'?0:1]++;}
 }
 if(!score||unknownBasis)return {score:null,reason:unknownBasis?'The historical forecast does not establish a 90-minute score basis.':'The recorded final includes extra time; a reconciled event timeline is needed to recover the 90-minute score.'};
 const [h,a]=score,margin=h-a,index=margin>0?0:margin<0?2:1,L=f.ladder;
 const valid=v=>Number.isFinite(v)&&v>=0&&v<=1;
 const outcomeValue=L[['h1','d','a1'][index]],band=margin===0?'d':(margin>0?'h':'a')+Math.min(Math.abs(margin),3),m=Math.abs(margin);
 const marginValue=margin===0?L.d:m>=3?L[band]:L[band]-L[(margin>0?'h':'a')+(m+1)];
 let exact=null,source='not-retained',bound=null,count=null;
 const cap=f.score_cap,grid=f.score_counts,n=f.n;
 const complete=Number.isInteger(cap)&&cap>0&&Number.isInteger(n)&&n>0&&Array.isArray(grid)&&grid.length===cap+1&&grid.every(r=>Array.isArray(r)&&r.length===cap+1&&r.every(v=>Number.isInteger(v)&&v>=0))&&grid.flat().reduce((a,b)=>a+b,0)===n;
 if(complete){if(h<cap&&a<cap){count=grid[h][a];exact=count/n;source='full-grid';}else source='overflow';}
 else{
  const top=(f.top||[]).filter(([s,p])=>valid(p)),hit=top.find(([s])=>s===score.join('-'));
  if(hit){exact=hit[1];source='retained-score';}
  else if(top.length)bound=Math.min(...top.map(([,p])=>p),...(valid(outcomeValue)?[outcomeValue]:[]),...(valid(marginValue)?[marginValue]:[]));
 }
 return {score,index,exact,exact_source:source,bound,count,n,cap,
  outcome:{label:index===1?'Draw':actual[index===0?'home':'away']+' win',value:valid(outcomeValue)?outcomeValue:null},
  margin:{label:index===1?'Level':actual[index===0?'home':'away']+' by '+(m>=3?'3+':m),value:valid(marginValue)?marginValue:null}};
}
export function realisedHtml(data){
 const r=realisedForecast(data);if(!r)return '';
 if(!r.score)return `<section class="match-section"><h3>How the result was priced</h3><p class="note">${esc(r.reason)} Probabilities unavailable for a comparable actual score.</p></section>`;
 const f=data.fixture,exact=r.exact==null?'—':pct(r.exact),explain=r.exact_source==='full-grid'?`${r.count.toLocaleString()} of ${r.n.toLocaleString()} simulated matches`:r.exact_source==='retained-score'?'Exact score retained in the pre-match forecast':r.exact_source==='overflow'?`${r.cap}+ goals share an overflow bin; an exact score is unavailable`:`Score not retained in this older forecast${r.bound==null?'':' · probability at most '+pct(r.bound)}`;
 return `<section class="match-section" data-realised-score="${r.score.join('-')}"><h3>How the result was priced</h3><p class="note"><b>Actual after 90 minutes</b> · ${esc(f.home)} ${r.score.join('–')} ${esc(f.away)} · probabilities from the saved pre-match forecast · shootout excluded</p><div class="centre-odds realised-odds"><div><span>Exact score · ${r.score.join('–')}</span><strong data-realised-prob="score" data-value="${r.exact??''}">${exact}</strong><small>${esc(explain)}</small></div><div><span>Result · ${esc(r.outcome.label)}</span><strong data-realised-prob="result" data-value="${r.outcome.value??''}">${r.outcome.value==null?'—':pct(r.outcome.value)}</strong></div><div><span>Goal margin · ${esc(r.margin.label)}</span><strong data-realised-prob="margin" data-value="${r.margin.value??''}">${r.margin.value==null?'—':pct(r.margin.value)}</strong><small>${r.index===1?'Level score':Math.abs(r.score[0]-r.score[1])>=3?'Three or more goals':'Exactly this winning margin'}</small></div></div><p class="note">Three views of the same outcome · do not add them together${r.exact===0?' · zero simulated occurrences does not mean impossible':''}</p></section>`;
}

// Atlas normalizes each attempt toward the right-hand goal, for both For and Against.
export const ATLAS_COLUMNS=7,ATLAS_ROWS=4;
export function atlasSelection(data,{competition='all',side='for',venue='all',since=null,period='season',type='all',bin=''}={}){
 const matches=(data?.matches||[]).filter(m=>{
  const f=m.fixture;return Boolean(f.result)&&f.kickoff.slice(0,10)<=data.as_of&&(competition==='all'||f.competition===competition)&&(venue==='all'||(f.home===data.team?'home':'away')===venue)&&(period==='season'||since&&(period==='before'?f.kickoff.slice(0,10)<=since:f.kickoff.slice(0,10)>since));
 }),covered=matches.filter(m=>m.coverage?.shotmap),universe=covered.flatMap(m=>m.shots.filter(s=>!s.own_goal&&(side==='for'?(m.fixture[s.side]===data.team):(m.fixture[s.side]!==data.team))&&(type==='all'||s.situation===type)).map(s=>{
  const located=Number.isFinite(s.x)&&Number.isFinite(s.y),x=located?s.x:null,y=located?68-s.y:null,col=located?Math.min(ATLAS_COLUMNS-1,Math.floor(x/105*ATLAS_COLUMNS)):null,row=located?Math.min(ATLAS_ROWS-1,Math.floor(y/68*ATLAS_ROWS)):null;
  return {...s,uid:m.fixture.id+'|'+s.id,fixture:m.fixture,px:x,py:y,bin:located?col+'-'+row:null};
 })),bins=Array.from({length:ATLAS_ROWS*ATLAS_COLUMNS},(_,i)=>{const col=i%ATLAS_COLUMNS,row=Math.floor(i/ATLAS_COLUMNS),id=col+'-'+row,shots=universe.filter(s=>s.bin===id);return {id,col,row,count:shots.length,xg:shots.reduce((n,s)=>n+(s.xg??0),0),unknown:shots.filter(s=>s.xg==null).length};}),shots=bin?universe.filter(s=>s.bin===bin):universe;
 return {team:data?.team,side,matches,covered:covered.length,unavailable:matches.length-covered.length,universe,shots,bins,located:shots.filter(s=>s.px!=null).length,knownXg:shots.reduce((sum,s)=>sum+(s.xg??0),0),unknownXg:shots.filter(s=>s.xg==null).length,goals:shots.filter(s=>s.goal).length,selectedMatches:new Set(shots.map(s=>s.fixture.id)).size};
}
export function atlasPitchHtml(selection,{chart='atlas',bin='',color='#d49356',maxXg=null}={}){
 const max=maxXg??Math.max(0,...selection.bins.map(b=>b.xg));
 const cells=chart==='density'?selection.bins.map(b=>`<g role="button" tabindex="0" data-atlas-bin="${b.id}" data-bin-count="${b.count}" data-bin-xg="${b.xg}" aria-label="Region ${b.id}: ${b.count} shots, known xG ${b.xg.toFixed(2)}" data-tip="${esc('<b>'+b.count+' shots</b><br>Known shot xG '+b.xg.toFixed(2)+' · '+b.unknown+' missing xG')}"><rect x="${b.col*15}" y="${b.row*17}" width="15" height="17" fill="${color}" fill-opacity="${b.count?.12+(max?b.xg/max:0)*.65:.02}" stroke="${b.id===bin?'var(--ink)':'var(--line)'}" stroke-width="${b.id===bin?.8:.15}"/>${b.count?`<text x="${b.col*15+7.5}" y="${b.row*17+9}" text-anchor="middle" fill="var(--ink)" font-size="3">${b.count}</text>`:''}</g>`).join(''):selection.shots.filter(s=>s.px!=null).map(s=>{
 const tip=esc('<b>'+esc(s.player)+'</b> · '+esc(s.label)+'′<br>'+esc(s.fixture.home)+' '+s.fixture.result.join('–')+' '+esc(s.fixture.away)+'<br>'+esc(kickoffLabel(s.fixture.kickoff,s.fixture.competition))+' · '+esc(s.situation||'Type unavailable')+'<br>Shot xG '+(s.xg==null?'unavailable':s.xg.toFixed(3)));
 return `<g role="button" tabindex="0" data-atlas-shot="${esc(s.uid)}" data-atlas-x="${s.px}" data-atlas-y="${s.py}" data-tip="${tip}" aria-label="${esc(s.player+' '+s.label+' minutes, '+(s.goal?'goal':'shot'))}">${s.goal?`<path d="M${s.px} ${s.py-1.5}l1.5 1.5l-1.5 1.5l-1.5-1.5Z" fill="${color}" stroke="var(--ink)" stroke-width=".5"/>`:`<circle cx="${s.px}" cy="${s.py}" r="${s.xg==null?.8:.6+Math.sqrt(s.xg)*1.8}" fill="${color}" fill-opacity=".75"/>`}<circle cx="${s.px}" cy="${s.py}" r="2.3" fill="transparent"/></g>`;
 }).join('');
 return `<svg class="match-pitch atlas-pitch" viewBox="-3 -3 111 74" role="img" aria-label="${esc(selection.team+' '+selection.side+' shot map; every attempt attacks right')}"><rect width="105" height="68"/>${cells}<g fill="none" stroke="var(--dim)" stroke-width=".3" pointer-events="none"><path d="M52.5 0V68M0 13.84H16.5V54.16H0M105 13.84H88.5V54.16H105M0 24.84H5.5V43.16H0M105 24.84H99.5V43.16H105M105 30.34H106.8V37.66H105"/><circle cx="52.5" cy="34" r="9.15"/></g></svg>`;
}
