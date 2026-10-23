// Fixture populations for the competition evidence charts; reads retained files only.
import {niceTicks} from './workspace.mjs';
import {analysis as clubAnalysis, chartData, aggregate, fixtureDay} from './performance-studio.mjs';

const finite=Number.isFinite;
export const POINTS_METHOD=Object.freeze({maxGoals:12,minimumXg:.01,minimumCorrection:1e-9,rho:Object.freeze({league:-.15,uefa:.05})});
const metrics={nd:'xgd',nf:'xgf',na:'xga',pp:'points'};
const sum=(rows,key)=>rows.reduce((n,r)=>n+r[key],0);
const sideIndex=(row,side)=>row.home===(side!=='against')?0:1;
const number=v=>finite(v)&&v>=0?v:null;

export function stateFor(data,raw={},mode='quality',competition=raw.competition){
 const first=data.fixtures.length?data.fixtures.map(fixtureDay).sort()[0]:data.as_of;
 return {competition:competition||data.competitions[0]?.competition||'',side:raw.side==='against'?'against':'for',measure:raw.measure==='xgot'?'xgot':'xg',
  venue:['home','away'].includes(raw.venue)?raw.venue:'all',window:['5','10'].includes(String(raw.window))?String(raw.window):'all',
  from:raw.from||first,to:raw.to||data.as_of,detail:typeof raw.detail==='string'?raw.detail:'',input_revision:raw.input_revision||'',
  baseline:raw.baseline==='on'?'on':'off',metric:['nd','nf','na','pp','xgd','xgf','xga','points','gd'].includes(raw.metric)?raw.metric:'xgd',through:raw.through||'',mode};
}

// This wrapper deliberately uses the same selector as Club Performance and Compare.
// A missing component stays in the last-N actual matches and leaves the value unavailable.
export function formSeries(data,{teams,competition,metric='nd',window='5',venue='all',from,to,through=''}={}){
 const first=data.fixtures.length?data.fixtures.map(fixtureDay).sort()[0]:data.as_of;
 const kind=data.competitions.find(c=>c.competition===competition)?.kind||'league';
 const scoped=kind==='uefa'?{...data,fixtures:data.fixtures.filter(pointsEligible)}:data;
 const state={clubs:teams||data.competitions.find(c=>c.competition===competition)?.teams||[],competition,chart:'trajectory',metric:metrics[metric]||metric,
  window:String(window),venue,from:from||first,to:to||data.as_of,through,side:'for'};
 const series=chartData(scoped,state);
 if(series.error)return series;
 const selected=clubAnalysis(scoped,state,through||state.to);
 if(kind==='uefa'&&state.metric==='points')for(let k=0;k<series.dates.length;k++){
  const at=clubAnalysis(scoped,state,series.dates[k]);
  for(const c of at.clubs)series.vals.get(c.team)[k]=c.rows.length?c.rows.reduce((n,r)=>n+(r.gf>r.ga?3:r.gf===r.ga?1:0),0)/c.rows.length:null;
 }
 return {...series,selected:selected.clubs,state};
}

// One whole-window aggregation for the optional reference; no second date-by-date series.
export function formReferences(data,state){
 const comp=data.competitions.find(c=>c.competition===state.competition),metric=metrics[state.metric]||state.metric;
 if(!comp)return new Map();
 const scoped=comp.kind==='uefa'?{...data,fixtures:data.fixtures.filter(pointsEligible)}:data;
 const selected=clubAnalysis(scoped,{...state,clubs:comp.teams,chart:'trajectory',window:'all',through:''},state.to);
 if(selected.error)return new Map();
 return new Map(selected.clubs.map(c=>[c.team,!c.rows.length?null:metric==='points'?c.rows.reduce((n,r)=>n+(r.gf>r.ga?3:r.gf===r.ga?1:0),0)/c.rows.length:metric==='gd'?(c.stats.gf-c.stats.ga)/c.rows.length:c.stats[metric]===null?null:c.stats[metric]/c.rows.length]));
}

export function goalsStats(rows,{side='for',measure='xg'}={}){
 const known=rows.map(r=>({id:r.fixture.id,goals:side==='against'?r.ga:r.gf,value:number(r.fixture[measure]?.[sideIndex(r,side)])})).filter(r=>r.value!==null);
 const complete=rows.length>0&&known.length===rows.length;
 return {n:rows.length,known:known.length,ids:rows.map(r=>r.fixture.id),covered_ids:known.map(r=>r.id),complete,
  goals:complete?sum(known,'goals'):null,value:complete?sum(known,'value'):null,
  known_goals:sum(known,'goals'),known_value:sum(known,'value')};
}

// Exact retained xG-points definition: independent Poisson 0..12, the existing
// kind-specific Dixon-Coles correction, renormalised after truncation. This is
// descriptive chance-based points, separate from a pre-match or final forecast.
export function chancePoints(fixture){
 const rho=POINTS_METHOD.rho[fixture.kind||'league'];
 if(!finite(rho))return null;
 const values=[0,1].map(i=>number(fixture.xg?.[i])??number(fixture.npxg?.[i]));
 if(values.some(v=>v===null))return null;
 const [h,a]=values.map(v=>Math.max(POINTS_METHOD.minimumXg,v));
 const poisson=lam=>{const out=[Math.exp(-lam)];for(let i=1;i<=POINTS_METHOD.maxGoals;i++)out.push(out.at(-1)*lam/i);return out;};
 const hp=poisson(h),ap=poisson(a);let home=0,draw=0,away=0,total=0;
 for(let i=0;i<hp.length;i++)for(let j=0;j<ap.length;j++){
  const correction=i===0&&j===0?1-h*a*rho:i===0&&j===1?1+h*rho:i===1&&j===0?1+a*rho:i===1&&j===1?1-rho:1;
  const p=hp[i]*ap[j]*Math.max(POINTS_METHOD.minimumCorrection,correction);total+=p;
  if(i>j)home+=p;else if(i===j)draw+=p;else away+=p;
 }
 if(!(total>0))return null;
 const wdl=[home,draw,away].map(p=>Math.min(1,Math.max(1e-12,p/total)));
 return {values:[3*wdl[0]+wdl[1],3*wdl[2]+wdl[1]],wdl,npxg_fallback:values.some((_,i)=>number(fixture.xg?.[i])===null)};
}

export function pointsEligible(f){return ['league','uefa'].includes(f.kind||'league')&&finite(f.round)&&(f.minutes==null||f.minutes===90)&&(!f.outcome||f.outcome==='fulltime');}
export function pointsStats(rows){
 const known=rows.map(r=>({row:r,chance:chancePoints(r.fixture)})).filter(r=>r.chance);
 const actual=known.reduce((n,{row:r})=>n+(r.gf>r.ga?3:r.gf===r.ga?1:0),0),expected=known.reduce((n,{row:r,chance:c})=>n+c.values[r.home?0:1],0);
 return {n:rows.length,known:known.length,ids:rows.map(r=>r.fixture.id),covered_ids:known.map(r=>r.row.fixture.id),points:known.length?actual:null,
  expected:known.length?expected:null,gap:known.length?actual-expected:null,npxg_fallback:known.filter(r=>r.chance.npxg_fallback).length};
}

export function competitionAnalysis(data,state){
 const comp=data.competitions.find(c=>c.competition===state.competition);
 if(!comp)return {error:'This competition is unavailable in the pinned snapshot.',clubs:[]};
 if(state.mode==='form'){
  if(!['league','uefa'].includes(comp.kind||'league'))return {error:'Form is available for domestic leagues and the UEFA league phase.',clubs:[]};
  const series=formSeries(data,{...state,teams:comp.teams});if(series.error)return series;
  const metric=metrics[state.metric]||state.metric;
  const clubs=series.selected.map(c=>({...c,coverage:metric==='points'?c.rows.length:c.stats.xg_n,ids:c.stats.ids,
   value:!c.rows.length?null:metric==='points'?c.rows.reduce((n,r)=>n+(r.gf>r.ga?3:r.gf===r.ga?1:0),0)/c.rows.length:metric==='gd'?(c.stats.gf-c.stats.ga)/c.rows.length:c.stats[metric]===null?null:c.stats[metric]/c.rows.length,
   covered_ids:c.rows.filter(r=>metric==='points'||finite(r.xgf)&&finite(r.xga)).map(r=>r.fixture.id)}));
  return {...series,clubs,competition:comp,plotted:[]};
 }
 if(state.mode==='points'&&!['league','uefa'].includes(comp.kind||'league'))return {error:'Chance-based points apply to domestic leagues and the UEFA league phase. Cup tie winners are a separate question.',clubs:[]};
 const scoped=state.mode==='points'?{...data,fixtures:data.fixtures.filter(pointsEligible)}:data;
 const base=clubAnalysis(scoped,{...state,clubs:comp.teams,chart:'trajectory',metric:'xgd',through:''},state.to);
 if(base.error)return base;
 const clubs=base.clubs.map(c=>{
  if(state.mode==='quality'){
   const s=aggregate(c.rows,state.side);
   return {...c,coverage:s.quality_n,x:s.volume??(s.quality===null?null:s.quality_shots/s.n),y:s.quality,ids:s.ids,covered_ids:s.quality_ids||[],invalid:s.invalid_quality};
  }
  if(state.mode==='points'){const s=pointsStats(c.rows);return {...c,coverage:s.known,x:s.expected,y:s.points,ids:s.ids,covered_ids:s.covered_ids,pointStats:s};}
  const s=goalsStats(c.rows,state);return {...c,coverage:s.known,x:s.value,y:s.goals,ids:s.ids,covered_ids:s.covered_ids,goalStats:s};
 });
 return {...base,competition:comp,clubs,plotted:clubs.filter(c=>finite(c.x)&&finite(c.y))};
}

export async function mount(root,ctx){
 const {esc}=ctx,mode=['goals','points','form'].includes(ctx.mode)?ctx.mode:'quality';let data,state,dead=false,optionsOpen=false,tableOpen=false,ledgerOpen=false;
 const q=s=>root.querySelector(s),fmt=(v,dp=2)=>finite(v)?v.toFixed(dp):'—';
 const options=(rows,value)=>rows.map(([v,label])=>`<option value="${esc(v)}"${v===value?' selected':''}>${esc(label)}</option>`).join('');
 const select=(id,label,rows,value)=>`<div class="chart-setting"><label for="${id}">${label}</label><select id="${id}">${options(rows,value)}</select></div>`;
 const save=()=>ctx.onState?.({...state});
 root.innerHTML='<p class="note" role="status">Loading retained fixture evidence…</p>';
 try{
  const response=await fetch('/api/performance?'+new URLSearchParams({date:ctx.source?.date||'',pr:ctx.source?.projection_sha256||'',scope:'all'}));data=await response.json();
  if(!response.ok)throw Error(data.error||'Fixture evidence unavailable.');
  if(!data.all_competitions)throw Error('Restart scripts/serve.py to enable the complete competition evidence scope.');
  if(data.source?.projection_sha256!==ctx.source?.projection_sha256)throw Error('Fixture evidence does not match the pinned snapshot.');
 }catch(error){if(root.isConnected)root.innerHTML=`<p class="zbad" role="alert">${esc(error.message)}</p>`;return()=>{dead=true;};}
 if(dead||!root.isConnected)return()=>{};
 state=stateFor(data,ctx.state,mode,ctx.competition);
 if(mode==='form'&&!ctx.state?.window)state.window='5';
 ledgerOpen=Boolean(state.through);
 if(state.input_revision&&state.input_revision!==data.input_revision){
  root.innerHTML=`<p class="zbad" role="alert">Retained fixture inputs changed. Reset evidence to adopt the current revision.</p><button id="competition-evidence-reset">Reset evidence</button>`;
  q('#competition-evidence-reset').onclick=()=>{state.input_revision=data.input_revision;save();render();};
 }else {state.input_revision=data.input_revision;render();save();}

 function render(focus){
  if(dead||!root.isConnected)return;
  const scrolls=[...root.querySelectorAll('.scroll')].map(e=>e.scrollLeft);
  optionsOpen=q('#competition-evidence-options')?.open??optionsOpen;tableOpen=q('#competition-evidence-table')?.open??tableOpen;ledgerOpen=q('#competition-evidence-ledger')?.open??ledgerOpen;
  const result=competitionAnalysis(data,state);
  if(result.error){root.innerHTML=`<p class="note" role="status">${esc(result.error)}</p>`;return;}
  const side=state.side==='against'?'against':'for',measure=state.measure==='xgot'?'xGOT':'xG';
  const metric=metrics[state.metric]||state.metric,formLabel={xgd:'xG difference / match',xgf:'xG for / match',xga:'xG against / match',points:'Match points / match',gd:'Goal difference / match'}[metric];
  const title=mode==='form'?'Form':mode==='quality'?'Shot volume & quality':mode==='points'?'Points v chance-based points':`Goals v ${measure}`;
  const labels=mode==='form'?['xG for','xG against']:mode==='quality'?[`Attempts ${side} / match`,'xG / attempt']:mode==='points'?['xG points','Covered match points']:[`${measure} ${side}`,`Goals ${side}`];
  const window=state.window==='all'?'season through cutoff':`last ${state.window} actual matches`;
  const detail=result.clubs.find(c=>c.team===state.detail)||result.plotted[0]||result.clubs[0];if(detail)state.detail=detail.team;
  const definitions=mode==='form'?'Rolling means use actual matches in kickoff order, including postponed fixtures when played. Missing xG stays in the selected window; no older match is substituted.':mode==='quality'?'Both axes use the same complete selected fixtures. Quality is total xG divided by total attempts.':mode==='points'?'Actual and chance-based points use exactly the same covered fixtures. No administrative deductions.':'Official goals and the selected shot metric use exactly the same selected fixtures.';
  root.innerHTML=`<section class="competition-evidence" aria-label="${esc(title)}"><details id="competition-evidence-options" class="chart-options"${optionsOpen?' open':''}><summary>Chart options</summary><div class="chart-settings">${!['points','form'].includes(mode)?select('competition-evidence-side','Side',[['for','For'],['against','Against']],state.side):''}${mode==='form'?select('competition-evidence-metric','Measure',[['xgd','xG difference / match'],['xgf','xG for / match'],['xga','xG against / match'],['points','Match points / match']],metric):''}${mode==='form'?select('competition-evidence-baseline','Reference',[['off','No reference'],['on','Selected-date average']],state.baseline):''}${mode==='goals'?select('competition-evidence-measure','Compare with',[['xg','xG'],['xgot','xG on target']],state.measure):''}${select('competition-evidence-window','Match window',[['all','Season to cutoff'],['5','Last 5 actual matches'],['10','Last 10 actual matches']],state.window)}</div></details>
   <div class="legend"><span><b>${esc(title)}</b> · ${esc(window)} · through ${esc(data.as_of)}${mode==='points'?' · league / league-phase points; covered fixtures only':''}</span></div>
   <p class="note">${esc(definitions)} ${mode==='form'?esc(formLabel)+' · shared UK dates; values hold between fixtures'+(state.baseline==='on'?' · dotted references: each highlighted club’s average over the selected dates':''):result.plotted.length+'/'+result.clubs.length+' clubs have plotted evidence.'}${mode!=='points'?' Incomplete windows stay unavailable.':''}</p>
   ${mode==='form'?'':`<p class="note">${mode==='quality'?'<b>Curves</b> · equal xG '+esc(side)+' per match · <b>Cross</b> · unweighted mean of plotted clubs':'<b>Diagonal</b> · equal values · above: more '+(mode==='points'?'points':'goals')+' than '+esc(mode==='points'?'xG points':measure)+' · below: fewer · parallel guides: total surplus/shortfall'}</p>`}<div id="competition-evidence-plot"></div>
   <div class="row">${mode==='form'?select('competition-evidence-through','Inspect chart date',[['','Latest in selected dates'],...result.dates.map(d=>[d,d])],state.through):''}${select('competition-evidence-team','Inspect club fixtures',result.clubs.map(c=>[c.team,c.team]),state.detail)}</div>
   <details id="competition-evidence-table"${tableOpen?' open':''}><summary>Aligned values &amp; coverage</summary><div class="scroll" tabindex="0" role="region" aria-label="Competition chart values"><table><thead><tr><th>Club</th><th>Played</th><th>Coverage</th>${mode==='form'?`<th>${esc(formLabel)}</th>`:`<th>${esc(labels[0])}</th><th>${esc(labels[1])}</th>`}</tr></thead><tbody>${result.clubs.map(c=>`<tr data-evidence-team="${esc(c.team)}" data-evidence-ids="${esc(JSON.stringify(c.ids))}"><td><button class="ghost" data-evidence-inspect="${esc(c.team)}">${ctx.badge?.(c.team)||''}${esc(c.team)}</button></td><td>${c.rows.length}</td><td>${c.coverage}/${c.rows.length}</td>${mode==='form'?`<td data-evidence-value="${c.value??''}">${fmt(c.value)}</td>`:`<td data-evidence-x="${c.x??''}">${fmt(c.x,mode==='quality'?1:2)}</td><td data-evidence-y="${c.y??''}">${fmt(c.y,mode==='quality'?3:0)}</td>`}</tr>`).join('')}</tbody></table></div></details>
   <details id="competition-evidence-ledger"${ledgerOpen?' open':''}><summary>Contributing fixtures${detail?' · '+esc(detail.team):''}</summary><div id="competition-evidence-fixtures"></div></details>
   ${result.clubs.some(c=>c.invalid)?'<p class="zbad" role="alert">Positive xG with zero attempts is inconsistent; affected windows are unavailable.</p>':''}
   ${data.issues?.length?`<p class="zbad" role="alert">${data.issues.length} retained source issues. Invalid components stay unavailable in actual-match windows; invalid result rows are excluded. ${data.issues.map(i=>esc(i.reason)).join(' · ')}</p>`:''}
   <details><summary>Definitions &amp; source evidence</summary><p class="note">${esc(definitions)} ${mode==='points'?`Chance-based points use independent Poisson goals at each side's retained xG, Dixon–Coles rho ${POINTS_METHOD.rho[result.competition.kind||'league']}, score support 0–${POINTS_METHOD.maxGoals} and a ${POINTS_METHOD.minimumXg} xG floor. Missing xG uses retained npxG only where available, preserving the existing definition. This is separate from pre-match expected points and forecast final XPTS.`:mode==='form'?'Provider xG includes penalties; these observed match metrics are separate from the model’s npxG ratings. UEFA Form uses numbered, 90-minute league-phase fixtures; its match points follow 3 for a win and 1 for a draw.':'Provider xG includes penalties. Official goals include own goals, while xG/xGOT describe shots; these differences are descriptive, without keeper or finishing attribution. Stored cup/UEFA totals can include extra time; shootouts are excluded. No shot-sum reconciliation is claimed.'}</p><p class="note">Snapshot ${esc(data.source.date)} · ${esc(ctx.label?.(state.competition)||state.competition)} · evidence <span class="evidence-id">${esc(data.input_revision)}</span></p></details></section>`;
  const pts=result.plotted.map(c=>({team:c.team,x:c.x,y:c.y,tone:ctx.tone?.(c.team),tip:`<b>${esc(c.team)}</b><br>${esc(labels[0])} ${fmt(c.x,2)} · ${esc(labels[1])} ${fmt(c.y,mode==='quality'?3:2)}<br>${c.coverage}/${c.rows.length} selected fixtures${mode==='quality'?`<br>Combined threat ${fmt(c.x*c.y)} xG ${side} / match`:`<br>Gap ${fmt(c.y-c.x)} ${mode==='points'?'points':'goals'} · ${fmt((c.y-c.x)/c.coverage)} / covered match`}`}));
  const references=mode==='form'&&state.baseline==='on'?formReferences(data,state):new Map();
  if(mode==='form'){
   q('#competition-evidence-plot').innerHTML=result.dates.length&&[...result.vals.values()].some(v=>v.some(finite))?ctx.line({names:result.clubs.map(c=>c.team),vals:result.vals,dates:result.dates,ylabel:formLabel,fmt:v=>fmt(v),mark:state.through?result.dates.indexOf(state.through):null,invert:metric==='xga',references}):'<p class="note" role="status">No complete evidence in this selected window.</p>';
   ctx.wireLine?.(root,()=>render());
   const svg=q('#competition-evidence-plot svg');if(svg&&ctx.lineInfo)svg.addEventListener('click',event=>{
    if(event.target.closest('[data-hl]'))return;const info=ctx.lineInfo(),box=svg.getBoundingClientRect();if(!info?.X||!box.width)return;
    const x=(event.clientX-box.left)/box.width*info.W;let closest=0;for(let i=1;i<result.dates.length;i++)if(Math.abs(info.X(i)-x)<Math.abs(info.X(closest)-x))closest=i;
    state.through=result.dates[closest];ledgerOpen=true;q('#competition-evidence-ledger').open=true;save();render('competition-evidence-through');
   });
  }else q('#competition-evidence-plot').innerHTML=pts.length?ctx.scatter(pts,{title,xlab:labels[0]+' →',ylab:labels[1]+' →',same:mode!=='quality',...(mode==='quality'?{product:true,quad:{x:pts.reduce((n,p)=>n+p.x,0)/pts.length,y:pts.reduce((n,p)=>n+p.y,0)/pts.length},corners:{tl:'fewer attempts · higher quality',tr:'more attempts · higher quality',bl:'fewer attempts · lower quality',br:'more attempts · lower quality'}}:{diag:niceTicks(-Math.max(1,...pts.map(p=>Math.abs(p.y-p.x))),Math.max(1,...pts.map(p=>Math.abs(p.y-p.x))),4).ticks.map(v=>[v,v===0?'equal values':(v>0?'+':'')+v+' '+(mode==='points'?'pts':'goals')]),corners:{tl:mode==='points'?'points above xG points':'goals above '+measure,br:mode==='points'?'points below xG points':'goals below '+measure}})}):'<p class="note" role="status">No complete evidence in this selected window.</p>';
  const inspect=team=>{state.detail=team;ledgerOpen=true;q('#competition-evidence-ledger').open=true;ctx.selectTeam?.(team);save();render('competition-evidence-team');};
  root.querySelectorAll('#competition-evidence-plot [data-team]').forEach(el=>{
   el.setAttribute('tabindex','0');el.setAttribute('role','button');el.setAttribute('aria-label',`Inspect ${el.dataset.team} contributing fixtures`);
   el.onclick=e=>{e.stopPropagation();inspect(el.dataset.team);};el.onkeydown=e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();e.stopPropagation();inspect(el.dataset.team);}};
  });
  root.querySelectorAll('[data-evidence-inspect]').forEach(el=>el.onclick=()=>inspect(el.dataset.evidenceInspect));
  for(const [id,key] of [['competition-evidence-baseline','baseline'],['competition-evidence-side','side'],['competition-evidence-measure','measure'],['competition-evidence-window','window'],['competition-evidence-team','detail'],['competition-evidence-through','through'],['competition-evidence-metric','metric']]){
   const el=q('#'+id);if(el)el.onchange=()=>{state[key]=el.value;if(['detail','through'].includes(key)){ledgerOpen=true;q('#competition-evidence-ledger').open=true;}save();render(id);};
  }
  ledger(detail,labels);
  root.querySelectorAll('.scroll').forEach((el,i)=>{if(scrolls[i]!=null)el.scrollLeft=scrolls[i];});
  ctx.tips?.(root);if(focus)q('#'+focus)?.focus({preventScroll:true});
 }

 function ledger(club,labels){
  if(!club)return;
  const included=new Set(club.covered_ids),rows=club.rows;
  q('#competition-evidence-fixtures').innerHTML=`<p class="note"><b>${esc(club.team)}</b> · ${club.coverage}/${rows.length} fixtures with matched evidence${mode==='points'&&club.pointStats.npxg_fallback?' · '+club.pointStats.npxg_fallback+' use npxG fallback':''} · last-match selection retains missing evidence${state.through?' · through '+esc(state.through):''}</p><div class="scroll" tabindex="0" role="region" aria-label="Selected club contributing fixtures"><table><thead><tr><th class="tie">Fixture</th><th>Minutes</th>${mode==='form'?'<th>Match points</th>':''}<th>${esc(mode==='quality'?'Attempts '+state.side:labels[0])}</th><th>${esc(mode==='quality'?'xG '+state.side:labels[1])}</th><th>Coverage</th></tr></thead><tbody>${rows.map(r=>{
   const i=sideIndex(r,state.side),f=r.fixture,p=mode==='points'?chancePoints(f):null;
   const x=mode==='form'?r.xgf:mode==='quality'?f.shots?.[i]:mode==='points'?p?.values[r.home?0:1]:f[state.measure]?.[i];
   const y=mode==='form'?r.xga:mode==='quality'?f.xg?.[i]:mode==='points'?(r.gf>r.ga?3:r.gf===r.ga?1:0):state.side==='against'?r.ga:r.gf;
   return `<tr data-evidence-fixture="${esc(f.id)}"><td class="tie"><button class="fixture-link" data-evidence-match="${esc(f.id)}">${ctx.fixtureHtml(f)}</button></td><td>${f.minutes??'—'}</td>${mode==='form'?`<td>${r.gf>r.ga?3:r.gf===r.ga?1:0}</td>`:''}<td>${fmt(x,mode==='quality'?0:2)}</td><td>${fmt(y,['quality','form'].includes(mode)?2:0)}</td><td>${included.has(f.id)?'Matched'+(p?.npxg_fallback?' · npxG fallback':''):'Missing component'}</td></tr>`;
  }).join('')}</tbody></table></div><p class="note">Open a fixture for its retained match evidence. Tactical Atlas opens season shot evidence for this club.</p><div class="row">${ctx.openAtlas?'<button id="competition-evidence-atlas" class="ghost">Season Tactical Atlas</button>':''}${ctx.openClub?'<button id="competition-evidence-club" class="ghost">Club performance</button>':''}</div>`;
  root.querySelectorAll('[data-evidence-match]').forEach(el=>el.onclick=()=>ctx.openMatch?.(data.fixtures.find(f=>f.id===el.dataset.evidenceMatch)));
  if(q('#competition-evidence-atlas'))q('#competition-evidence-atlas').onclick=()=>ctx.openAtlas(club.team,state.competition);
  if(q('#competition-evidence-club'))q('#competition-evidence-club').onclick=()=>ctx.openClub(club.team,state.competition);
 }
 return()=>{dead=true;};
}
