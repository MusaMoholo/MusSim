// Stored-only two-date history. Snapshot metadata and numerical bridges come from the read service.
export const CHARTS=[['bridge','Points bridge & trajectory'],['fates','Qualification changes'],['strength','Strength history']];
export const FATES=[['p_win','Title'],['p_ucl','UCL'],['p_uel','UEL'],['p_uecl','UECL'],['p_releg','Relegation']];
const finite=Number.isFinite;
export function stateFor(catalog,raw={}){
 const dates=catalog.dates.map(d=>d.date),b=raw.b||catalog.source.date;
 const base=Number.isFinite(Date.parse(b+'T00:00:00Z'))?b:catalog.source.date,month=new Date(Date.parse(base+'T00:00:00Z')-30*86400000).toISOString().slice(0,10),a=raw.a||dates.filter(d=>d<=month).at(-1)||dates[0];
 const get=date=>catalog.dates.find(d=>d.date===date);
 return {a,ap:raw.ap||get(a)?.projection_sha256||'',b,bp:raw.bp||get(b)?.projection_sha256||'',competition:raw.competition||get(b)?.competitions[0]||'',team:typeof raw.team==='string'?raw.team:'',
 chart:CHARTS.some(([k])=>k===raw.chart)?raw.chart:'bridge',metric:['att','def','net'].includes(raw.metric)?raw.metric:'elo',reference:raw.reference==='five_leagues'?'five_leagues':'competition',
 fate:FATES.some(([k])=>k===raw.fate)?raw.fate:'p_win',ledger:raw.ledger==='all'?'all':'club'};
}
export function seriesFor(data,state){
 const dates=data.timeline.map(t=>t.meta.date),values=new Map();
 if(state.chart==='bridge'){
  for(const [name,key]of[['Banked','banked'],['Expected final','expected_final'],['Expected remaining','expected_remaining']])values.set(name,data.timeline.map(t=>t.teams[state.team]?.[key]??null));
 }else if(state.chart==='fates')values.set(FATES.find(([k])=>k===state.fate)[1],data.timeline.map(t=>{const v=t.teams[state.team]?.[state.fate];return finite(v)?100*v:null;}));
 else values.set(state.metric==='elo'?'Elo':state.metric.toUpperCase(),data.timeline.map(t=>{const s=t.teams[state.team]?.strength;return state.metric==='elo'?s?.elo??null:s?.[state.reference]?.[state.metric]??null;}));
 return {dates,values};
}
export function selectedLedger(data,state){return data.ledger===null?null:data.ledger.filter(f=>state.ledger==='all'||f.home===state.team||f.away===state.team);}

export async function mount(root,ctx){
 const {esc}=ctx;let catalog,state,data=null,error='',loading=false,sequence=0,dead=false,optionsOpen=false;
 const q=s=>root.querySelector(s),format=(v,precision=1,sign=false)=>{if(!finite(v))return'—';const n=Number(v.toFixed(precision));return(sign&&n>0?'+':'')+n.toFixed(precision);};
 const options=(rows,value)=>(value&&!rows.some(([k])=>k===value)?[[value,'Unavailable · '+value],...rows]:rows).map(([key,label])=>`<option value="${esc(key)}"${key===value?' selected':''}>${esc(label)}</option>`).join('');
 const select=(id,label,rows,value)=>`<div><label for="${id}">${label}</label><select id="${id}">${options(rows,value)}</select></div>`;
 const request=async(path,query)=>{const response=await fetch(path+'?'+new URLSearchParams(query));const out=await response.json();if(!response.ok)throw Error(out.error||'Stored history unavailable');return out;};
 const anchor={date:ctx.source?.date||'',pr:ctx.source?.projection_sha256||''};
 root.innerHTML='<div class="panel"><h2>Time Machine</h2><p role="status">Loading stored date catalogue…</p></div>';
 try{catalog=await request('/api/time-machine/catalog',anchor);}catch(e){if(root.isConnected)root.innerHTML=`<div class="panel"><h2>Time Machine</h2><p role="alert">${esc(e.message)}. Restart scripts/serve.py if it predates the Time Machine update, then refresh.</p></div>`;return()=>{dead=true;};}
 if(!root.isConnected||dead)return()=>{};state=stateFor(catalog,ctx.state);if(ctx.chart)state.chart=ctx.chart;
 const persist=()=>ctx.onState({...state});
 async function load(focus=null){
  const token=++sequence;loading=true;data=null;error='';persist();render(focus);
  try{const definition={...state},out=await request('/api/time-machine',{...anchor,a:definition.a,ap:definition.ap,b:definition.b,bp:definition.bp,competition:definition.competition});
   if(dead||!root.isConnected||token!==sequence)return;
   if(out.source.projection_sha256!==anchor.pr||out.before.projection_sha256!==definition.ap||out.after.projection_sha256!==definition.bp||out.competition!==definition.competition)throw Error('Comparison source pins do not match the selected dates.');
   data=out;if(!state.team)state.team=data.rows.some(r=>r.team==='Arsenal')?'Arsenal':data.rows[0]?.team||'';
  }catch(e){if(token===sequence)error=e.message;}finally{if(token===sequence&&!dead&&root.isConnected){loading=false;const active=root.contains(document.activeElement)?document.activeElement.id:null;persist();render(active);}}
 }
 function metadataHtml(meta,name){return `<div class="tm-source"><b>${name} · ${esc(meta.date)}</b><span>Data through ${esc(meta.as_of)}</span><span>${meta.timing==='rebuilt_later'?'Rebuilt later':meta.timing==='same_day'?'Generated on snapshot date':'Generation timing unclear'} · ${esc(meta.model||'model unknown')}</span><small>Generated ${esc(meta.generated||'unknown')} · payload ${meta.payload} · ${Number(meta.worlds||0).toLocaleString()} worlds</small></div>`;}
 function render(focus=null){
  if(dead||!root.isConnected)return;optionsOpen=q('.tm-options')?.open??optionsOpen;
  const scrolls=new Map([...root.querySelectorAll('[data-tm-scroll]')].map(e=>[e.dataset.tmScroll,e.scrollLeft]));
  const dateOptions=catalog.dates.map(d=>[d.date,d.date+' · data through '+d.as_of]),ad=catalog.dates.find(d=>d.date===state.a),bd=catalog.dates.find(d=>d.date===state.b),comps=[...new Set([...(ad?.competitions||[]),...(bd?.competitions||[])])];
  root.innerHTML=`<div class="panel time-machine"><h2>Time Machine</h2><p class="note">Compare two stored snapshots · every change is B minus A · snapshot dates and data cutoffs are shown separately</p>
  <div class="row tm-controls">${select('tm-a','Snapshot A',dateOptions,state.a)}${select('tm-b','Snapshot B',dateOptions,state.b)}<button class="ghost" id="tm-swap">Swap dates</button><button class="ghost" id="tm-reset">Reset pair</button></div>
  <div class="row tm-controls">${select('tm-competition','Competition',comps.map(c=>[c,ctx.label(c)]),state.competition)}${data?select('tm-team','Club',data.rows.map(r=>[r.team,r.team]),state.team):''}</div>
  ${ctx.embedded?'':`<div class="chart-toolbar">${ctx.chartPicker([['History',CHARTS]],state.chart,'tm-chart')}</div>`}
  <details class="tm-options"${optionsOpen?' open':''}><summary>Chart options</summary><div class="row tm-controls">${state.chart==='strength'?select('tm-metric','Measure',[['elo','Elo'],['att','ATT'],['def','DEF'],['net','NET']],state.metric)+(state.metric!=='elo'?select('tm-reference','Strength reference',[['competition','League average on each date'],['five_leagues','Five-league average']],state.reference):''):state.chart==='fates'?select('tm-fate','Club history',FATES,state.fate):'<p class="note">Banked, expected final and expected remaining points share one axis.</p>'}</div></details>
  <div id="tm-status" role="status" aria-live="polite">${loading?'Loading stored comparison…':''}</div>${error?`<p role="alert">${esc(error)} Choose the dates again or reset the pair to use current revisions.</p>`:''}<div id="tm-comparison"></div></div>`;
  for(const [id,key]of[['tm-a','a'],['tm-b','b'],['tm-competition','competition'],['tm-team','team'],['tm-chart','chart'],['tm-metric','metric'],['tm-reference','reference'],['tm-fate','fate']]){
   const el=q('#'+id);if(!el)continue;el.onchange=()=>{state[key]=el.value;if(key==='a'||key==='b')state[key+'p']=catalog.dates.find(d=>d.date===state[key])?.projection_sha256||'';
    if(['a','b','competition'].includes(key)){if(key==='competition')state.team='';load(id);}else{persist();render(id);}};
  }
  q('#tm-swap').onclick=()=>{[state.a,state.b]=[state.b,state.a];[state.ap,state.bp]=[state.bp,state.ap];load('tm-swap');};
  q('#tm-reset').onclick=async()=>{q('#tm-reset').disabled=true;try{const fresh=await request('/api/time-machine/catalog',anchor);if(dead||!root.isConnected)return;catalog=fresh;const reset=stateFor(catalog);state={...reset,competition:state.competition,team:state.team,chart:state.chart};load('tm-a');}catch(e){error=e.message;render('tm-reset');}};
  if(data&&!loading&&!error){
   const selected=data.rows.find(r=>r.team===state.team),valid=Boolean(selected?.before&&selected?.after),changed=data.changes;
   q('#tm-comparison').innerHTML=`<div class="tm-sources">${metadataHtml(data.before,'A')}${metadataHtml(data.after,'B')}</div>
   <p class="note"><b>Historical reconstruction</b> · generation time does not establish original publication · no causal attribution to an individual match${data.before.date>data.after.date?' · reversed pair; charts run in calendar order':''}</p>
   ${changed.model?'<p class="zbad" role="alert">Different model generations: the comparison includes model changes.</p>':''}
   ${data.issues.length?`<p class="zbad" role="alert">${data.issues.length} invalid stored cells in this date range are excluded. ${[...new Set(data.issues.map(i=>i.team+' · '+ctx.label(i.competition)))].map(esc).join(' · ')}. Source values are retained in the evidence details.</p>`:''}
   ${!valid?'<p role="status">Choose a club covered on both dates to see its bridge and history.</p>':''}
   <div id="tm-analysis"></div><div id="tm-ledger-panel"></div>
   <details><summary>Source evidence & limitations</summary><p class="note">${esc(data.notice)} Match Centre can show revised retained provider facts; this comparison keeps the original stored GW scores.</p><p class="note">${changed.payload?'Payload changed · ':''}${changed.params.length?'Changed saved options: '+esc(changed.params.join(', ')):'Saved options unchanged'} · ${data.timeline.length} dated snapshots</p><p class="note evidence-id">A ${esc(data.before.projection_sha256)}<br>B ${esc(data.after.projection_sha256)}<br>Evidence ${esc(data.input_revision)}</p>${data.issues.length?`<ul>${data.issues.map(i=>`<li>${esc(i.date+' · '+i.competition+' · '+i.team+' · '+i.field+' = '+JSON.stringify(i.value)+' · '+i.reason)}</li>`).join('')}</ul>`:''}</details>`;
   if(state.chart==='bridge')bridgeHtml(selected);else if(state.chart==='fates')fatesHtml(selected);else strengthHtml(selected);
   ledgerHtml();root.querySelectorAll('[data-tm-team]').forEach(b=>b.onclick=()=>{state.team=b.dataset.tmTeam;persist();render(b.id);});
   const target=q('#tm-plot');if(target&&valid){const series=seriesFor(data,state),available=[...series.values.values()].some(v=>v.some(finite));
    target.innerHTML=available?ctx.line({values:series.values,dates:series.dates,unit:state.chart==='bridge'?'Points':state.chart==='fates'?'Chance (%)':state.metric==='elo'?'Elo':(state.reference==='competition'?'League-relative ':'Five-league ')+state.metric.toUpperCase()+' (npxG / match)',format:v=>format(v,state.chart==='strength'&&state.metric!=='elo'?3:1)}):'<p class="note" role="status">Stored values are unavailable for this selection.</p>';
    ctx.wireLine(root,()=>render());const wrap=target.querySelector('.scroll');if(wrap)wrap.dataset.tmScroll='plot';
   }
  }
  root.querySelectorAll('[data-tm-scroll]').forEach(e=>{if(scrolls.has(e.dataset.tmScroll))e.scrollLeft=scrolls.get(e.dataset.tmScroll);});
  if(focus)q('#'+focus)?.focus({preventScroll:true});ctx.tips(root);
 }
 function teamCell(r,i){return `<td class="team">${ctx.badge(r.team)}<button id="tm-row-${i}" class="text-button" data-tm-team="${esc(r.team)}" aria-pressed="${r.team===state.team}">${esc(r.team)}</button></td>`;}
 function bridgeHtml(row){
  q('#tm-analysis').innerHTML=`<h3>${esc(state.team)} · expected final points bridge</h3>${row?.bridge?`<div class="tm-bridge" data-tm-bridge="${esc(JSON.stringify(row.bridge))}">${[['expected_final','Expected final'],['banked','Banked'],['expected_remaining','Expected remaining']].map(([key,name])=>`<div><span>${name}</span><strong>${format(row.bridge[key],1,true)}</strong><small>${format(row.before[key])} → ${format(row.after[key])}</small></div>`).join('')}</div><p class="note"><b>Δ expected final ${format(row.bridge.expected_final,1,true)} = Δ banked ${format(row.bridge.banked,1,true)} + Δ remaining (${format(row.bridge.expected_remaining,1,true)})</b> · stored precision · remaining means expected points still to be earned</p>`:'<p class="note" role="status">A complete stored points bridge is unavailable for this club.</p>'}<div id="tm-plot"></div>
  <h3>Aligned league points</h3><div class="scroll" data-tm-scroll="points" tabindex="0" role="region" aria-label="Two-date league points comparison"><table><thead><tr><th>Team</th><th>A banked</th><th>B banked</th><th>Δ banked</th><th>A expected final</th><th>B expected final</th><th>Δ expected final</th><th>Δ remaining</th></tr></thead><tbody>${data.rows.map((r,i)=>`<tr data-tm-points="${esc(r.team)}">${teamCell(r,i)}${[r.before?.banked,r.after?.banked,r.delta.banked,r.before?.expected_final,r.after?.expected_final,r.delta.expected_final,r.delta.expected_remaining].map((v,j)=>`<td data-tm-number="${v??''}">${format(v,1,[2,5,6].includes(j))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
 }
 function fatesHtml(){
  const maximum=Math.max(...data.rows.flatMap(r=>FATES.map(([key])=>Math.abs(r.delta[key]||0))),.0001);
  q('#tm-analysis').innerHTML=`<h3>Qualification probability change · B minus A</h3><p class="note"><b>Shade</b> · change magnitude · signed percentage points · hover/focus for A → B · higher relegation means more risk · invalid/missing values stay —</p><div class="scroll" data-tm-scroll="fates" tabindex="0" role="region" aria-label="Probability change heatmap"><table class="tm-fates-table"><thead><tr><th>Team</th>${FATES.map(([,name])=>`<th>${name}</th>`).join('')}</tr></thead><tbody>${data.rows.map((r,i)=>`<tr>${teamCell(r,i)}${FATES.map(([key,name])=>{const value=r.delta[key],label=finite(value)?`${r.team} ${name}: ${(100*r.before[key]).toFixed(1)}% → ${(100*r.after[key]).toFixed(1)}%, change ${format(100*value,1,true)} percentage points`:`${r.team} ${name}: unavailable`;return `<td class="heat" data-tm-probability="${esc(r.team+'|'+key)}" data-tm-delta="${value??''}"${finite(value)?` style="${ctx.heatStyle(.07+.93*(Math.abs(value)/maximum)**.55)}"`:''}><span tabindex="0" role="img" aria-label="${esc(label)}" title="${esc(label)}">${finite(value)?format(100*value,1,true):'—'}</span></td>`;}).join('')}</tr>`).join('')}</tbody></table></div><h3>${esc(state.team)} · ${esc(FATES.find(([k])=>k===state.fate)[1])} history</h3><div id="tm-plot"></div>`;
 }
 function strengthHtml(row){
  const value=(r,key)=>key==='elo'?r?.strength?.elo:r?.strength?.[state.reference]?.[key];
  q('#tm-analysis').innerHTML=`<h3>${esc(state.team)} · strength history</h3><p class="note"><b>${state.metric==='elo'?'Elo':state.reference==='competition'?'Relative to each date’s league average':'Five-league scale'}</b> · ${state.metric==='elo'?'result-based rating':'model npxG ratings, separate from observed goals/xG'} · source scales are applied separately on each date</p><div id="tm-plot"></div><div class="scroll" data-tm-scroll="strength" tabindex="0" role="region" aria-label="Two-date strength comparison"><table><thead><tr><th>Measure</th><th>A</th><th>B</th><th>Change</th></tr></thead><tbody>${['elo','att','def','net'].map(key=>{const a=value(row?.before,key),b=value(row?.after,key);return `<tr data-tm-strength="${key}"><td>${key.toUpperCase()}</td><td>${format(a,key==='elo'?1:3)}</td><td>${format(b,key==='elo'?1:3)}</td><td>${format(finite(a)&&finite(b)?b-a:null,key==='elo'?1:3,true)}</td></tr>`;}).join('')}</tbody></table></div>`;
 }
 function ledgerHtml(){
  const rows=selectedLedger(data,state),rec=data.reconciliation.filter(r=>state.ledger==='all'||r.team===state.team),bad=rec.filter(r=>!r.valid);
  q('#tm-ledger-panel').innerHTML=`<h3>Recorded fixture changes</h3><div class="row tm-controls">${select('tm-ledger','Fixtures',[['club','Selected club'],['all','Whole league']],state.ledger)}</div><p class="note">Differences between the two stored result ledgers · additions, removals and revisions · no causal forecast attribution</p>${rows===null?'<p role="status" class="note">Stored GW fixture evidence is missing on an endpoint. No current-data replacement is used.</p>':`${bad.length?`<p class="zbad" role="alert">${bad.length} club point/appearance totals do not reconcile to stored GW evidence. The discrepancy is retained.</p>`:`<p class="note"><b>Reconciled</b> · ${rec.length} club point totals agree with stored fixtures on both dates</p>`}${rows.length?`<div class="scroll" data-tm-scroll="ledger" tabindex="0" role="region" aria-label="Stored fixture changes"><table><thead><tr><th class="tie">Fixture</th><th>A score</th><th>B score</th><th>Change</th><th>${state.ledger==='club'?'Club points Δ':'Home / away points Δ'}</th><th>Match evidence</th></tr></thead><tbody>${rows.map(f=>`<tr data-tm-fixture="${f.id}" data-tm-points-delta="${state.ledger==='club'?f.points_delta[state.team]??0:JSON.stringify(f.points_delta)}"><td class="tie">${ctx.fixtureHtml(f.after||f.before)}</td><td>${f.before?f.before.result.join('–'):'—'}</td><td>${f.after?f.after.result.join('–'):'—'}</td><td>${esc(f.change)}</td><td>${state.ledger==='club'?format(f.points_delta[state.team]??0,0,true):format(f.points_delta[f.home],0,true)+' / '+format(f.points_delta[f.away],0,true)}</td><td><button class="ghost" data-tm-match="${f.id}">Open Match Centre</button></td></tr>`).join('')}</tbody></table></div>`:'<p class="note" role="status">No changed recorded fixtures in this selection.</p>'}`}`;
  q('#tm-ledger').onchange=e=>{state.ledger=e.target.value;persist();render('tm-ledger');};root.querySelectorAll('[data-tm-match]').forEach(b=>b.onclick=()=>ctx.openMatch(data.ledger.find(f=>f.id===b.dataset.tmMatch)));
 }
 await load();return()=>{dead=true;sequence++;};
}
