// Pure workspace selectors and versioned local preferences. No DOM, network or model imports.
export const SECTIONS = [['home','Home'],['races','Comps'],['clubs','Clubs'],['players','Players'],['explore','Explore']];
export const PREF_VERSION = 1;
export const SECTION_IDS = new Set([...SECTIONS.map(([id])=>id),'matches']);
export const canonicalSection = id=>id==='matches'?'home':id==='comps'?'races':id;
const finite = Number.isFinite;
const extraTabs = new Set(['Tactical Atlas','Performance Studio','Time Machine','Forecast Lab','Movers','Track record','Big matches','Trophies','Ratings','Visualisations']);
const cleanString = (value, max=160) => typeof value==='string' && value.length<=max && !/[\u0000-\u001f]/.test(value);
// Stored naive kickoff clocks use the ingestion competition timezone; explicit offsets are instants.
export const FIXTURE_ZONES={'English Premier League':'Europe/London','English FA Cup':'Europe/London','English League Cup':'Europe/London','German Bundesliga':'Europe/Berlin','German DFB Pokal':'Europe/Berlin','Spanish La Liga':'Europe/Madrid','Spanish Copa del Rey':'Europe/Madrid','Italian Serie A':'Europe/Rome','Italian Coppa Italia':'Europe/Rome','French Ligue 1':'Europe/Paris','French Coupe de France':'Europe/Paris','UEFA Champions League':'Europe/Zurich','UEFA Europa League':'Europe/Zurich','UEFA Conference League':'Europe/Zurich'};
const fixtureInstants=new Map(),fixtureZoneFormatters=new Map();
const ukKickoffFormat=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/London',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
const ukFixtureFormat=new Intl.DateTimeFormat('en-GB',{weekday:'short',day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23',timeZone:'Europe/London'});
export function fixtureInstant(value,competition='') {
 const text=String(value||'');if(/(?:Z|[+-]\d{2}:\d{2})$/i.test(text))return Date.parse(text);
 const wall=Date.parse(text.replace(' ','T')+'Z');if(!Number.isFinite(wall))return NaN;
 const zone=FIXTURE_ZONES[competition]||'UTC',key=zone+'|'+text;if(fixtureInstants.has(key))return fixtureInstants.get(key);
 if(!fixtureZoneFormatters.has(zone))fixtureZoneFormatters.set(zone,new Intl.DateTimeFormat('en-GB',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}));
 const formatter=fixtureZoneFormatters.get(zone);
 let instant=wall;
 for(let i=0;i<3;i++){const p=Object.fromEntries(formatter.formatToParts(new Date(instant)).map(p=>[p.type,p.value])),local=Date.UTC(+p.year,+p.month-1,+p.day,+p.hour,+p.minute,+p.second),difference=wall-local;if(!difference){if(fixtureInstants.size>=8192)fixtureInstants.clear();fixtureInstants.set(key,instant);return instant;}instant+=difference;}
 return NaN;
}
export function kickoffLabel(value,competition='') {
 const date=new Date(fixtureInstant(value,competition));
 return Number.isFinite(+date)?ukKickoffFormat.format(date):'Time unavailable';
}
export function contextOf(result) {
  return {season:result?.params?.season??null, snapshot:result?.source?.kind==='snapshot'?result.source.date:null,
    cutoff:result?.as_of??result?.fitted_through??null, model:result?.model??null, payload:result?.version??1,
    projectionRevision:result?.source?.projection_sha256??null,
    mode:result?.source?.kind==='snapshot'?'snapshot':'live'};
}
export function clubId(name,badges={}) {
  const id=String(badges[name]||'').match(/(?:^|\/)(\d+)\.png$/)?.[1];
  return id?'club:fotmob:'+id:'club:name:'+encodeURIComponent(name);
}
export function clubEntities(result,badges={}) {
  const byId=new Map();
  for(const [kind,blocks] of [['league',result?.leagues||[]],['uefa',result?.uefa||[]],['cup',result?.cups||[]]])
    for(const b of blocks) for(const t of b.teams||[]) {
      const id=clubId(t.team,badges), entity=byId.get(id)||{id,name:t.team,aliases:[],competitions:[],provisional:id.startsWith('club:name:')};
      if(!entity.aliases.includes(t.team))entity.aliases.push(t.team);
      if(!entity.competitions.some(c=>c.competition===b.competition))entity.competitions.push({competition:b.competition,kind});
      byId.set(id,entity);
    }
  return [...byId.values()].sort((a,b)=>a.name.localeCompare(b.name)||a.id.localeCompare(b.id));
}
export function resolveFollowing(ids,entities) {
  const aliases=new Map();
  for(const e of entities){aliases.set(e.id,e.id);for(const name of e.aliases)aliases.set('club:name:'+encodeURIComponent(name),e.id);}
  return [...new Set(ids.map(id=>aliases.get(id)||id))];
}
export function isAtlasRoute(hash) {
 const h=new URLSearchParams(String(hash||'').replace(/^#/,''));
 return h.get('tab')==='Tactical Atlas'||h.get('clubsection')==='atlas'||h.get('view')==='viz'&&['atlas','density'].includes(h.get('viz'));
}
export function sectionFromRoute(hash,landing='home') {
  const h=new URLSearchParams(String(hash||'').replace(/^#/,''));
  if(isAtlasRoute(hash))return 'clubs';
  if(h.get('tab')==='Performance Studio'&&(!h.has('section')||['explore','clubs'].includes(h.get('section'))))return 'clubs';
  if(h.get('tab')==='Big matches'&&(!h.has('section')||['explore','home','matches'].includes(h.get('section'))))return 'home';
  if(SECTION_IDS.has(canonicalSection(h.get('section'))))return canonicalSection(h.get('section'));
  // Legacy links retain their original destination rather than opening a new Home page.
  if(h.get('tab')==='Big matches')return 'home';
  if(h.has('tab'))return extraTabs.has(h.get('tab'))?'explore':'races';
  return SECTION_IDS.has(canonicalSection(landing))?canonicalSection(landing):'home';
}
export function emptyPreferences() {return {version:PREF_VERSION,following:[],followLabels:{},savedViews:[],landing:'home'};}
export function preferences(value,{strict=false}={}) {
  const fail=message=>{if(strict)throw new Error(message);return emptyPreferences();};
  if(value==null)return emptyPreferences();
  if(typeof value!=='object'||Array.isArray(value)||value.version!==PREF_VERSION)return fail('Unsupported workspace preferences version.');
  if(!Array.isArray(value.following)||value.following.length>1000||value.following.some(id=>!cleanString(id,400)||!(/^(club:(?:fotmob:|name:)|player:fotmob:|race:\d{4}:)/.test(id))))return fail('Invalid followed entities.');
  if(!Array.isArray(value.savedViews)||value.savedViews.length>30)return fail('At most 30 saved views are supported.');
  const saved=[];
  for(const v of value.savedViews) {
    if(!v||!cleanString(v.id,80)||!cleanString(v.name,100)||!v.name.trim()||!cleanString(v.hash,8000)||!v.hash.startsWith('#'))return fail('Invalid saved view.');
    const h=new URLSearchParams(v.hash.slice(1));
    if(!/^\d{4}-\d{2}-\d{2}$/.test(h.get('date')||'')||!h.get('tab')||!SECTION_IDS.has(h.get('section')))return fail('Saved views require a pinned snapshot and workspace section.');
    if(saved.some(s=>s.id===v.id))return fail('Duplicate saved view identity.');
    saved.push({id:v.id,name:v.name.trim(),hash:'#'+h.toString()});
  }
  const labels=value.followLabels??{};
  if(typeof labels!=='object'||Array.isArray(labels)||Object.entries(labels).some(([id,name])=>!value.following.includes(id)||!cleanString(name,200)))return fail('Invalid saved follow labels.');
  return {version:PREF_VERSION,following:[...new Set(value.following)],followLabels:Object.fromEntries(Object.entries(labels)),savedViews:saved,landing:SECTION_IDS.has(value.landing)?value.landing:'home'};
}
export function loadPreferences(storage) {
  try{return preferences(JSON.parse(storage.getItem('football.workspace.v1')));}catch{return emptyPreferences();}
}
export function persistPreferences(storage,value) {
  try{storage.setItem('football.workspace.v1',JSON.stringify(preferences(value,{strict:true})));return true;}catch{return false;}
}
export function importPreferences(text) {
  if(typeof text!=='string'||text.length>1000000)throw new Error('Preferences file is too large.');
  return preferences(JSON.parse(text),{strict:true});
}
export function snapshotIssues(result) {
  const issues=[];
  for(const b of [...(result?.leagues||[]),...(result?.uefa||[]),...(result?.cups||[])])for(const t of b.teams||[])
    for(const [metric,value] of Object.entries(t))if(metric.startsWith('p_')&&typeof value==='number'&&(!finite(value)||value<0||value>1))
      issues.push({competition:b.competition,team:t.team,metric,value});
  return issues;
}
export function upcomingAgenda(result,matches,following=[],badges={},limit=6,players=null) {
  const context=contextOf(result),scope=followingScope(result,players,following,badges),seen=new Set();
  const end=context.cutoff?new Date(context.cutoff+'T00:00:00Z'):null;
  if(end)end.setUTCDate(end.getUTCDate()+7);
  const rows=(matches?.fixtures||[]).filter(f=>{
    const day=String(f.kickoff||'').slice(0,10);
    if(!/^\d{4}-\d{2}-\d{2}$/.test(day)||f.result||!context.cutoff||day<=context.cutoff||day>end.toISOString().slice(0,10))return false;
    if(finite(f.p_occurs)&&f.p_occurs<1)return false;
    return !scope.active||scope.clubs.has(clubId(f.home,badges))||scope.clubs.has(clubId(f.away,badges))||scope.races.some(r=>r.competition===f.competition);
  }).sort((a,b)=>fixtureInstant(a.kickoff,a.competition)-fixtureInstant(b.kickoff,b.competition)||a.competition.localeCompare(b.competition)||a.home.localeCompare(b.home)||a.away.localeCompare(b.away));
  return rows.filter(f=>{const key=[f.competition,f.home,f.away,f.kickoff].join('|');if(seen.has(key))return false;seen.add(key);return true;}).slice(0,limit);
}
export function comparisonIndex(result,history,window) {
  const dates=history?.dates||[],context=contextOf(result),here=context.snapshot?dates.indexOf(context.snapshot):dates.length;
  if(here<=0)return -1;
  if(!window)return here-1;
  let index=-1;
  for(let i=0;i<here;i++)if((history.meta?.[dates[i]]?.as_of||dates[i])<=window.date)index=i;
  return index<0?0:index;
}
export function briefingChanges(result,history,window,following=[],badges={},players=null) {
  const index=comparisonIndex(result,history,window),scope=followingScope(result,players,following,badges),rows=[];
  if(index<0)return {rows,index,date:null};
  const date=history.dates[index];
  const groups=[...(result.leagues||[]).map(b=>[b,[['p_win','Title'],['p_ucl','UCL'],['p_uel','UEL'],['p_uecl','UECL'],['p_releg','REL']]]),
    ...(result.uefa||[]).map(b=>[b,[['p_win','Win'],['p_top8','Top 8']]]),...(result.cups||[]).map(b=>[b,[['p_win','Win']]])];
  for(const [block,metrics] of groups) {
    const candidates=[];
    for(const t of block.teams) {
      for(const [metric,name] of metrics) {
        if(scope.active&&!scope.clubs.has(clubId(t.team,badges))&&!scope.races.some(r=>r.competition===block.competition&&r.metric===metric))continue;
        const before=history.competitions?.[block.competition]?.[t.team]?.[metric]?.[index],now=t[metric];
        if(!finite(before)||!finite(now)||before<0||before>1||now<0||now>1)continue;
        const delta=100*(now-before);if(Math.abs(delta)<.05)continue;
        candidates.push({competition:block.competition,team:t.team,metric,name,before,now,delta,date,
          cutoff:history.meta?.[date]?.as_of??null,model:history.meta?.[date]?.model??null,
          favourable:metric==='p_releg'?delta<0:delta>0});
      }
    }
    candidates.sort((a,b)=>Math.abs(b.delta)-Math.abs(a.delta)||a.team.localeCompare(b.team)||a.metric.localeCompare(b.metric));
    // One update per competition; phase/league swings never enter a cross-competition ranking.
    if(candidates.length)rows.push(candidates[0]);
  }
  return {rows,index,date};
}

// Football entities are selected from one knowledge state. Player identity is the provider ID;
// competition and club contributions remain separate evidence rows rather than inferred totals.
export function playerEntities(result,players) {
  if(!players||players.season!==result?.params?.season||players.as_of!==result?.as_of)return [];
  const byId=new Map();
  for(const [competition,block] of Object.entries(players.competitions||{}))for(const row of block.players||[]) {
    if(row.id==null||!String(row.id)||!row.name)continue;
    const id='player:fotmob:'+String(row.id),entity=byId.get(id)||{type:'player',id,name:row.name,aliases:[],teams:[],rows:[]};
    if(!entity.aliases.includes(row.name))entity.aliases.push(row.name);
    for(const team of row.teams||[])if(!entity.teams.includes(team))entity.teams.push(team);
    entity.rows.push({competition,source:row,coverage:block.coverage||{}});byId.set(id,entity);
  }
  return [...byId.values()].sort((a,b)=>a.name.localeCompare(b.name)||a.id.localeCompare(b.id));
}
export function raceEntities(result) {
  const season=result?.params?.season,races=[];
  const blocks=[...(result?.leagues||[]).map(b=>[b,[['p_win','Title'],['p_ucl','UCL'],['p_uel','UEL'],['p_uecl','UECL'],['p_releg','Relegation']]]),
    ...(result?.uefa||[]).map(b=>[b,[['p_win','Win'],['p_top8','Top 8'],['p_top24','Top 24']]]),...(result?.cups||[]).map(b=>[b,[['p_win','Win']]])];
  for(const [block,metrics] of blocks)for(const [metric,name] of metrics)
    if(block.teams.some(t=>finite(t[metric])))races.push({type:'race',id:'race:'+season+':'+encodeURIComponent(block.competition)+':'+metric,
      name:block.competition+' · '+name,competition:block.competition,metric,fate:name,season});
  return races;
}
export function matchEntities(result,matches,gw) {
  const byKey=new Map(),rows=[...(matches?.fixtures||[])];
  for(const [competition,block] of [...Object.entries(gw?.leagues||{}),...Object.entries(gw?.phases||{})])
    rows.push(...(block.fixtures||[]).map(f=>({...f,competition})));
  for(const f of rows) {
    if(!f.home||!f.away||!f.competition||!/^\d{4}-\d{2}-\d{2}/.test(f.kickoff||''))continue;
    if(finite(f.p_occurs)&&f.p_occurs<1)continue;
    if(f.result&&f.kickoff.slice(0,10)>result?.as_of)continue;
    // Match cards use a day-based fixture identity; retain competition to disambiguate it.
    const key=[f.home,f.away,f.kickoff.slice(0,10)].join('|'),id='match:'+encodeURIComponent(f.competition)+'|'+key;
    if(!byKey.has(id))byKey.set(id,{type:'match',id,key,name:f.home+' v '+f.away,competition:f.competition,kickoff:f.kickoff,fixture:f});
  }
  return [...byKey.values()].sort((a,b)=>fixtureInstant(a.kickoff,a.competition)-fixtureInstant(b.kickoff,b.competition)||a.id.localeCompare(b.id));
}
export function entityIndex(result,matches,players,badges={},gw=null) {
  return [...clubEntities(result,badges).map(e=>({...e,type:'club'})),...playerEntities(result,players),...raceEntities(result),...matchEntities(result,matches,gw)];
}
const searchLetters={'ø':'o','ł':'l','đ':'d','æ':'ae','œ':'oe','ß':'ss'};
export const normaliseSearch=value=>String(value||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase().replace(/[øłđæœß]/g,c=>searchLetters[c]);
const searchText=normaliseSearch;
export function searchEntities(entities,query,type='all',limit=24) {
  const words=searchText(query).trim().split(/\s+/).filter(Boolean);
  if(!words.length)return [];
  return entities.filter(e=>type==='all'||e.type===type).map(e=>({entity:e,
    name:searchText(e.name),text:searchText([e.name,...(e.aliases||[]),...(e.teams||[]),e.competition||'',...(e.competitions||[]).map(c=>c.competition),e.kickoff?.slice(0,10)||''].join(' '))}))
    .filter(e=>words.every(w=>e.text.includes(w)))
    .sort((a,b)=>Number(b.name===words.join(' '))-Number(a.name===words.join(' '))||Number(b.name.startsWith(words.join(' ')))-Number(a.name.startsWith(words.join(' ')))||words.filter(w=>b.name.split(/[^\p{L}\p{N}]+/u).some(n=>n.startsWith(w))).length-words.filter(w=>a.name.split(/[^\p{L}\p{N}]+/u).some(n=>n.startsWith(w))).length||a.name.localeCompare(b.name)||a.entity.id.localeCompare(b.entity.id))
    .slice(0,limit).map(e=>e.entity);
}
export function followingScope(result,players,following,badges={}) {
  const ids=new Set(following),clubs=new Set(following.filter(id=>id.startsWith('club:'))),races=raceEntities(result).filter(e=>ids.has(e.id));
  for(const p of playerEntities(result,players))if(ids.has(p.id))for(const team of p.teams)clubs.add(clubId(team,badges));
  return {active:ids.size>0,clubs,races};
}

// Existing player accounting selectors, extracted without changing their calculations.
const PLAYER_FIELDS = ["matches", "minutes", "goals", "pen_goals", "assists", "shots", "xg", "xgot"];
export function playerRows(payload,comp, team = "all") {
  return (payload?.competitions?.[comp]?.players || []).flatMap((p) => {
    const source = team === "all" ? p : p.by_team?.[team];
    if (!source) return [];
    // A club filter reads that club's contribution only: no fallback to the pooled total.
    return [{id: p.id, name: p.name, teams: team === "all" ? p.teams || [] : [team],
      ...Object.fromEntries(PLAYER_FIELDS.map((k) => [k, Number.isFinite(source[k]) ? source[k] : null])),
      known: source.known || {}}];
  });
}
export function playerMetric(row, metric) {
  if (metric === "finishing") return Number.isFinite(row.goals) && Number.isFinite(row.xg) ? row.goals - row.xg : null;
  if (metric === "xg90") return Number.isFinite(row.xg) && Number.isFinite(row.minutes) && row.minutes > 0
    ? 90 * row.xg / row.minutes : null;
  return Number.isFinite(row[metric]) ? row[metric] : null;
}
export function playerLeadersData(payload,comp, metric = "goals", team = "all", floor = 180) {
  const source = playerRows(payload,comp, team), known = source.filter((p) => playerMetric(p, metric) != null);
  const eligible = known.filter((p) => metric !== "xg90" || p.minutes >= floor);
  eligible.sort((a, b) => playerMetric(b, metric) - playerMetric(a, metric)
    || (b.goals ?? -1) - (a.goals ?? -1) || (b.minutes ?? -1) - (a.minutes ?? -1)
    || a.name.localeCompare(b.name) || String(a.id).localeCompare(String(b.id)));
  return {rows: eligible.slice(0, 50), total: source.length, eligible: eligible.length,
    unknown: source.length - known.length, belowFloor: known.length - eligible.length,
    omitted: Math.max(0, eligible.length - 50)};
}

// Shared scalar formatters; keep the original precision and unavailable conventions.
export const pct = (x) => x == null ? "" : (x * 100).toFixed(1) + "%";
export const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
export const fx1 = (v) => v == null ? "—" : Number(v).toFixed(1);
export function signedFx(v, dp) {
  const x = Number(Number(v).toFixed(dp));
  return x > 0 ? `+${x.toFixed(dp)}` : x < 0 ? `−${(-x).toFixed(dp)}` : (0).toFixed(dp);
}

export const PLAYER_METRICS = [["goals", "Goals"], ["xg", "xG"], ["finishing", "G − xG"],
  ["xg90", "xG / 90"], ["assists", "Assists"], ["shots", "Shots"]];

// Shared charts: rendering stays pure; current highlights/badges and crosshair registry
// are explicit dependencies supplied by the shell.
export const span = (v, pad = 0.07) => {
  const lo = Math.min(...v), hi = Math.max(...v), p = ((hi - lo) || 1) * pad;
  return [lo - p, hi + p];
};

export function niceTicks(lo, hi, want = 5, integer = false) {
  const raw = (hi - lo) / Math.max(want - 1, 1) || 1;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag)
    .find((c) => c >= raw && (!integer || c >= 1)) ?? 10 * mag;
  const a = Math.floor(lo / step) * step, b = Math.ceil(hi / step) * step;
  const out = [];
  for (let v = a; v <= b + step / 1e6; v += step) out.push(Math.round(v * 1e6) / 1e6);
  return {ticks: out, lo: a, hi: b, step};
}

// Equal attack/defence improvements from an explicit same-unit reference.
export function attackDefenceProfile(x,y,reference) {
  const attack=x-reference.x, defence=reference.y-y;
  const balance=attack-defence;
  const lean=Math.abs(balance)<1e-9?'Balanced profile':balance>0?'Attack-led profile':'Defence-led profile';
  const category=attack>=0&&defence>=0?'Stronger on both':attack<0&&defence<0?'Weaker on both':attack>=0?'Stronger attack, weaker defence':'Stronger defence, weaker attack';
  return {attack,defence,balance,lean,category};
}

export function quantile(values,p) {
  const sorted=values.filter(Number.isFinite).slice().sort((a,b)=>a-b);
  if(!sorted.length||!Number.isFinite(p)||p<0||p>1)return null;
  const at=(sorted.length-1)*p,lo=Math.floor(at);return sorted[lo]+(sorted[Math.ceil(at)]-sorted[lo])*(at-lo);
}
export function pointsTarget(points,target) {
  if(!Number.isInteger(target)||!Number.isInteger(points?.offset)||!Array.isArray(points.dist)||!points.dist.length||points.dist.some(v=>!Number.isFinite(v)||v<0||v>1))return null;
  const mass=points.dist.reduce((n,v)=>n+v,0),tolerance=points.dist.length*.00005+1e-9;
  if(!(mass>0)||Math.abs(mass-1)>tolerance)return null;
  return points.dist.reduce((n,v,i)=>n+(points.offset+i>=target?v:0),0)/mass;
}
export function toughestStretch(fixtures,team,competition,size=3) {
  const rows=fixtures.filter(f=>!f.result&&!f.tbd&&!f.conditional&&(f.p_occurs==null||f.p_occurs===1)&&(f.home===team||f.away===team))
    .map(f=>{const odds=f.ladder?[f.ladder.h1,f.ladder.d,f.ladder.a1]:[null,null,null];return {fixture:f,odds,instant:fixtureInstant(f.kickoff,competition),expected:3*odds[team===f.home?0:2]+odds[1]};})
    .sort((a,b)=>a.instant-b.instant||String(a.fixture.id||a.fixture.home+'|'+a.fixture.away).localeCompare(String(b.fixture.id||b.fixture.home+'|'+b.fixture.away)));
  if(!Number.isInteger(size)||size<1||rows.length<size||rows.some(({odds,instant,expected})=>!Number.isFinite(instant)||![...odds,expected].every(Number.isFinite)||odds.some(v=>v<0||v>1)||Math.abs(odds.reduce((n,v)=>n+v,0)-1)>.001))return null;
  let best=null;
  for(let i=0;i<=rows.length-size;i++) {
    const window=rows.slice(i,i+size);
    const expected=window.reduce((n,r)=>n+r.expected,0);
    if(!best||expected<best.expected-1e-12)best={fixtures:window.map(r=>r.fixture),expected};
  }
  return best;
}
export function knockoutSteps(values) {
  // No derived ratios from a broken/missing reach ladder, including historical Coppa defects.
  if(values.some(v=>v!==null&&(!Number.isFinite(v)||v<0||v>1)))return {invalid:true,steps:[],largest:null};
  const steps=[];
  for(let k=1;k<values.length;k++){
    const before=values[k-1],after=values[k];
    if(before===null||after===null)continue;
    if(after>before+1e-9)return {invalid:true,steps:[],largest:null};
    if(before>0)steps.push({index:k,reach:before,next:after,through:after/before,loss:before-after});
  }
  const largest=steps.reduce((best,s)=>!best||s.loss>best.loss+1e-12?s:best,null);
  return {invalid:false,steps,largest};
}

export function createChartPrimitives(services) {
  const {useBadges,badgeOf,toneFill,shortName,hlOf,HLCOL,PALETTE,LC,chartHighlightsHtml,getFocus}=services;
function scatter(pts, o) {
  const FOCUS=getFocus();
  const reference=o.balance&&pts.length?{x:pts.reduce((n,p)=>n+p.x,0)/pts.length,y:pts.reduce((n,p)=>n+p.y,0)/pts.length}:null;
  // Population spread of signed profile tilt, in football units rather than screen pixels.
  // Dividing both tilt and its SD by sqrt(2) gives identical perpendicular-distance thresholds.
  const spread=reference?Math.sqrt(pts.reduce((n,p)=>n+(p.x+p.y-reference.x-reference.y)**2,0)/pts.length):0;
  if(reference) {
    o={...o,quad:reference};
    pts=pts.map(p=>{const profile=attackDefenceProfile(p.x,p.y,reference),signed=v=>(v>=0?'+':'')+v.toFixed(2);
      return {...p,tip:p.tip+`<br><b>${profile.lean}</b> · ${profile.category.toLowerCase()}<br>vs plotted clubs’ mean: attack ${signed(profile.attack)} · defence ${signed(profile.defence)}<br>Positive = better · same units as axes${spread>1e-9?`<br>Profile tilt ${signed(profile.balance/spread)}σ · plotted-club spread`:""}`};});
  }
  const W = o.W || 1100, H = o.H || 620, m = {l: 64, r: 28, t: 18, b: 52};
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const xv = pts.flatMap((p) => p.from ? [p.x, p.from[0]] : [p.x]);
  const yv = pts.flatMap((p) => p.from ? [p.y, p.from[1]] : [p.y]);
  let [x0, x1] = span(xv), [y0, y1] = span(yv);
  if (o.same) { const lo = Math.min(x0, y0), hi = Math.max(x1, y1); x0 = y0 = lo; x1 = y1 = hi; }
  if (o.domain) { x0 = y0 = o.domain[0]; x1 = y1 = o.domain[1]; }
  const X = (v) => m.l + (v - x0) / (x1 - x0) * iw;
  const Y = (v) => o.invertY ? m.t + (v - y0) / (y1 - y0) * ih : m.t + ih - (v - y0) / (y1 - y0) * ih;
  const tx = niceTicks(x0, x1, 6).ticks.filter((t) => t >= x0 && t <= x1);
  const ty = niceTicks(y0, y1, 6).ticks.filter((t) => t >= y0 && t <= y1);
  const dp = (ts) => ts.some((t) => Math.abs(t - Math.round(t)) > 1e-9)
    ? (ts.some((t) => Math.abs(t * 10 - Math.round(t * 10)) > 1e-9) ? 2 : 1) : 0;
  const grid = tx.map((t) => `<line x1="${X(t)}" x2="${X(t)}" y1="${m.t}" y2="${m.t + ih}" stroke="var(--line)"/>
      <text x="${X(t)}" y="${m.t + ih + 16}" text-anchor="middle">${t.toFixed(dp(tx))}</text>`).join("")
    + ty.map((t) => `<line x1="${m.l}" x2="${m.l + iw}" y1="${Y(t)}" y2="${Y(t)}" stroke="var(--line)"/>
      <text x="${m.l - 8}" y="${Y(t) + 4}" text-anchor="end">${t.toFixed(dp(ty))}</text>`).join("");
  // lines of y = x + c, clipped to the plot, each labelled along itself near its right-hand end,
  // haloed in the panel colour so it reads over the grid
  const diag = (o.diag || []).map(([c, lab]) => {
    const a = Math.max(x0, y0 - c), b = Math.min(x1, y1 - c);
    if (!(b > a)) return "";
    const [ax, ay, bx, by] = [X(a), Y(a + c), X(b), Y(b + c)];
    const len = Math.hypot(bx - ax, by - ay), ang = Math.atan2(by - ay, bx - ax) * 180 / Math.PI;
    const k = Math.max(0, 1 - 34 / Math.max(len, 1));
    const lx = ax + (bx - ax) * k, ly = ay + (by - ay) * k;
    return `<line x1="${ax}" y1="${ay}" x2="${bx}" y2="${by}" stroke="var(--dim)"
        stroke-opacity="${c === 0 ? 0.55 : 0.25}"/>${lab && len > 80 ? `<text x="${lx.toFixed(1)}"
        y="${(ly - 4).toFixed(1)}" text-anchor="end" transform="rotate(${ang.toFixed(1)} ${lx.toFixed(1)} ${ly.toFixed(1)})"
        style="font-size:10px;paint-order:stroke;stroke:var(--panel);stroke-width:3px">${lab}</text>` : ""}`;
  }).join("");
  // x+y = reference ATT+DEF: equal improvement in attack and defence.
  // With conceded goals increasing downwards, this rises from bottom left to top right.
  let balance="";
  if(reference) {
    balance=(spread>1e-9?[0,-1,1]:[0]).map(sigma=>{
      const sum=reference.x+reference.y+sigma*spread,a=Math.max(x0,sum-y1),b=Math.min(x1,sum-y0);
      if(!(b>a))return "";
      const ax=X(a),ay=Y(sum-a),bx=X(b),by=Y(sum-b),angle=Math.atan2(by-ay,bx-ax)*180/Math.PI;
      const label=sigma===0?'balanced profile':sigma<0?'defence-led · −1σ':'attack-led · +1σ';
      return `<g class="profile-guide" pointer-events="none"><line data-profile-sum="${sum}" x1="${ax}" y1="${ay}" x2="${bx}" y2="${by}" data-profile-sigma="${sigma}" stroke="var(--accent)" stroke-width="${sigma===0?1.8:1.2}" stroke-dasharray="${sigma===0?'7 5':'3 5'}" stroke-opacity="${sigma===0?.8:.55}"/>
        <text x="${ax+(bx-ax)*.52}" y="${ay+(by-ay)*.52-6}" text-anchor="middle" transform="rotate(${angle} ${ax+(bx-ax)*.52} ${ay+(by-ay)*.52-6})" style="font-size:11px;fill:var(--accent);paint-order:stroke;stroke:var(--panel);stroke-width:4px">${label}</text></g>`;
    }).join("");
  }
  // Equal products: attempts/match × xG/attempt = xG/match, on matched fixtures.
  const products=o.product?[.5,1,1.5,2,3,4,5,6].map(value=>{
    const a=Math.max(x0,1e-9,y1>0?value/y1:Infinity),b=Math.min(x1,y0>0?value/y0:Infinity);
    if(!(b>a))return "";
    const coords=Array.from({length:65},(_,i)=>{const x=a+(b-a)*i/64;return [x,value/x];});
    const path=coords.map(([x,y],i)=>(i?'L':'M')+X(x).toFixed(2)+','+Y(y).toFixed(2)).join(' '),at=coords[48];
    return `<g data-product-guide="${value}" pointer-events="none"><path d="${path}" fill="none" stroke="var(--accent)" stroke-opacity=".45" stroke-dasharray="5 5"/><text x="${X(at[0])}" y="${Y(at[1])-5}" text-anchor="middle" style="font-size:10px;fill:var(--accent);paint-order:stroke;stroke:var(--panel);stroke-width:3px">${value} xG/match</text></g>`;
  }).join(''):'';
  const quad = o.quad ? `<line x1="${X(o.quad.x)}" x2="${X(o.quad.x)}" y1="${m.t}" y2="${m.t + ih}"
      stroke="var(--dim)" stroke-opacity=".5"/><line x1="${m.l}" x2="${m.l + iw}" y1="${Y(o.quad.y)}"
      y2="${Y(o.quad.y)}" stroke="var(--dim)" stroke-opacity=".5"/>` : "";
  const c = o.corners || {};
  const corners = [["tl", m.l + 8, m.t + 14, "start"], ["tr", m.l + iw - 8, m.t + 14, "end"],
                   ["bl", m.l + 8, m.t + ih - 8, "start"], ["br", m.l + iw - 8, m.t + ih - 8, "end"]]
    .filter(([k]) => c[k]).map(([k, x, y, a]) =>
      `<text class="vcap" x="${x}" y="${y}" text-anchor="${a}">${c[k]}</text>`).join("");
  const tails = pts.filter((p) => p.from).map((p) =>
    `<line x1="${X(p.from[0])}" y1="${Y(p.from[1])}" x2="${X(p.x)}" y2="${Y(p.y)}" stroke="var(--dim)"
      stroke-width="1.25" stroke-opacity=".55"/><circle cx="${X(p.from[0])}" cy="${Y(p.from[1])}" r="2"
      fill="var(--dim)" fill-opacity=".7"/>`).join("");
  const badges = !o.noTeams && useBadges();
  // the open card's side last, so it sits on top
  const order = pts.slice().sort((a, b) => (a.team === FOCUS) - (b.team === FOCUS));
  const marks = order.map((p) => {
    const cx = X(p.x), cy = Y(p.y), url = badges ? badgeOf(p.team) : null, big = p.team === FOCUS;
    if (url) {
      const s = big ? 34 : 26;
      return (big ? `<circle cx="${cx}" cy="${cy}" r="${s / 2 + 3}" fill="none" stroke="var(--accent)" stroke-width="2"/>` : "")
        + `<image href="${url}" x="${(cx - s / 2).toFixed(1)}" y="${(cy - s / 2).toFixed(1)}" width="${s}" height="${s}" preserveAspectRatio="xMidYMid meet"/>`;
    }
    return `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${big ? 7 : 5}" fill="${p.color || toneFill(p.tone)}"
      stroke="${big ? "var(--accent)" : "var(--panel)"}" stroke-width="2"/>`;
  }).join("");
  // names beside dots where they fit: the open card's side first, then outward from the middle,
  // each tried right, left, above and below, kept only clear of every dot and earlier name
  let labels = "";
  if (!badges || pts.some((p) => !badgeOf(p.team))) {
    const midx = (x0 + x1) / 2, midy = (y0 + y1) / 2;
    const dots = pts.map((p) => ({x: X(p.x) - 6, y: Y(p.y) - 6, w: 12, h: 12, team: p.team}));
    const placed = [];
    const hit = (b) => b.x < m.l || b.y < m.t || b.x + b.w > m.l + iw || b.y + b.h > m.t + ih
      || placed.some((q) => b.x < q.x + q.w && q.x < b.x + b.w && b.y < q.y + q.h && q.y < b.y + b.h)
      || dots.some((q) => q.team !== b.team && b.x < q.x + q.w && q.x < b.x + b.w && b.y < q.y + q.h
                          && q.y < b.y + b.h);
    const want = pts.filter((p) => !badges || !badgeOf(p.team)).sort((a, b) =>
      (b.team === FOCUS) - (a.team === FOCUS)
      || (Math.abs(b.x - midx) / (x1 - x0) + Math.abs(b.y - midy) / (y1 - y0))
       - (Math.abs(a.x - midx) / (x1 - x0) + Math.abs(a.y - midy) / (y1 - y0)));
    for (const p of want) {
      const t = shortName(p.team), w = t.length * 6.1 + 2, h = 12, cx = X(p.x), cy = Y(p.y);
      const at = [[cx + 8, cy - 6, "start"], [cx - 8 - w, cy - 6, "start"], [cx - w / 2, cy - 19, "start"],
                  [cx - w / 2, cy + 7, "start"]].map(([x, y]) => ({x, y, w, h, team: p.team}))
        .find((b) => !hit(b));
      if (!at) continue;
      placed.push(at);
      labels += `<text class="vlab" x="${at.x.toFixed(1)}" y="${(at.y + 10).toFixed(1)}"${p.team === FOCUS
        ? ` style="font-weight:600"` : ""}>${esc(t)}</text>`;
    }
  }
  const hits = pts.map((p) => `<circle class="hit" cx="${X(p.x).toFixed(1)}" cy="${Y(p.y).toFixed(1)}"
      r="15" fill="transparent" style="cursor:${o.noTeams ? "default" : "pointer"}"${o.noTeams ? "" : ` data-team="${esc(p.team)}"`} data-tip="${esc(p.tip)}"/>`).join("");
  return `<div class="scroll"><svg class="vchart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.title || "")}"
      style="max-width:${W}px">
    ${grid}${quad}${diag}${products}${balance}${corners}${tails}${marks}${labels}
    <text x="${m.l + iw / 2}" y="${H - 10}" text-anchor="middle" class="vlab">${o.xlab}</text>
    <text transform="translate(16,${m.t + ih / 2}) rotate(-90)" text-anchor="middle" class="vlab">${o.ylab}</text>
    ${hits}</svg></div>`;
}

function lineChart(o) {
  const {block, id, vals, labels, realUpTo = labels.length - 1, fmt = (v) => v.toFixed(1),
         invert = false, rank, ylab = "", tick = fmt} = o;
  const comp = block.competition, teams = [...vals.keys()];
  const lit = hlOf(block, rank).filter((t) => vals.has(t)), col = HLCOL[comp];
  const n = labels.length, W = 1100, H = 420, m = {l: 58, r: 120, t: 18, b: 40};
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const references=o.references||new Map();
  const all = teams.flatMap((t) => vals.get(t).filter((v) => v != null)).concat(lit.map(t=>references.get(t)).filter(Number.isFinite));
  if (!all.length) return `<p class="note">Nothing to draw yet.</p>`;
  const [y0, y1] = span(all, 0.05);
  const positions=o.positions;
  if(positions&&(!Array.isArray(positions)||positions.length!==n||positions.some((v,i)=>!Number.isFinite(v)||i>0&&v<=positions[i-1])))throw Error('Line positions must be finite and strictly increasing.');
  const X = (k) => m.l + (n === 1 ? iw / 2 : positions?(positions[k]-positions[0])*iw/(positions[n-1]-positions[0]):k * iw / (n - 1));
  const Y = (v) => invert ? m.t + (v - y0) / (y1 - y0) * ih : m.t + ih - (v - y0) / (y1 - y0) * ih;
  const ticks = niceTicks(y0, y1, 6).ticks.filter((t) => t >= y0 && t <= y1);
  const grid = ticks.map((t) => `<line x1="${m.l}" x2="${m.l + iw}" y1="${Y(t)}" y2="${Y(t)}" stroke="var(--line)"/>
      <text x="${m.l - 8}" y="${Y(t) + 4}" text-anchor="end">${tick(t)}</text>`).join("")
    + labels.map((t, k) => t ? `<text x="${X(k)}" y="${H - m.b + 16}" text-anchor="middle">${t}</text>` : "").join("")
    + (ylab ? `<text transform="translate(14,${m.t + ih / 2}) rotate(-90)" text-anchor="middle" class="vlab">${ylab}</text>` : "");
  const path = (v, a, b) => {
    let d = "", open = false;
    for (let k = a; k <= b; k++) {
      if (v[k] == null) { open = false; continue; }
      d += (open ? "L" : "M") + X(k).toFixed(1) + "," + Y(v[k]).toFixed(1) + " ";
      open = true;
    }
    return d;
  };
  const baselines=lit.filter(t=>Number.isFinite(references.get(t))).map(t=>`<line data-line-baseline="${esc(t)}" data-baseline-value="${references.get(t)}" x1="${m.l}" x2="${m.l+iw}" y1="${Y(references.get(t))}" y2="${Y(references.get(t))}" stroke="${PALETTE[col[t]??0]}" stroke-opacity=".5" stroke-dasharray="3 5"/>`).join('');
  const rest = teams.filter((t) => !lit.includes(t));
  const faint = rest.map((t) => `<path d="${path(vals.get(t), 0, n - 1)}" fill="none" stroke="var(--dim)"
      stroke-opacity=".25" stroke-width="1.25"/>`).join("");
  const hit = rest.map((t) => `<path d="${path(vals.get(t), 0, n - 1)}" fill="none" stroke="transparent"
      stroke-width="8" style="cursor:pointer" data-hl="${esc(t)}" data-tip="${esc(`<b>${esc(t)}</b> — click to light it`)}"/>`).join("");
  const bright = lit.map((t) => {
    const c = PALETTE[col[t] ?? 0], v = vals.get(t);
    const solid = path(v, 0, Math.min(realUpTo, n - 1));
    const dashed = realUpTo < n - 1 ? path(v, Math.max(realUpTo, 0), n - 1) : "";
    // A path with only one point has no segment to paint. Keep a lone observation visible.
    const known = v.map((value, k) => value == null ? null : k).filter((k) => k != null);
    const dot = known.length === 1 ? `<circle data-line-single="${esc(t)}" cx="${X(known[0])}"
      cy="${Y(v[known[0]]).toFixed(1)}" r="4" fill="${c}" stroke="var(--panel)" stroke-width="2"/>` : "";
    return `<path d="${solid}" fill="none" stroke="${c}" stroke-width="2.25" stroke-linejoin="round"/>${dashed
      ? `<path d="${dashed}" fill="none" stroke="${c}" stroke-width="2.25" stroke-dasharray="5 4"/>` : ""}${dot}`;
  }).join("");
  const lastOf = (v) => { for (let k = v.length - 1; k >= 0; k--) if (v[k] != null) return [k, v[k]]; return [0, 0]; };
  const ends = lit.map((t) => { const [k, v] = lastOf(vals.get(t)); return {t, x: X(k), y: Y(v), y0: Y(v)}; })
    .sort((a, b) => a.y - b.y);
  for (let k = 1; k < ends.length; k++) ends[k].y = Math.max(ends[k].y, ends[k - 1].y + 13);
  const labs = ends.map((e) => `<text class="vlab" x="${e.x + 10}" y="${e.y + 4}">${esc(o.shortLabel?o.shortLabel(e.t):shortName(e.t))}</text>`).join("");
  const today = realUpTo >= 0 && realUpTo < n - 1 ? `<line x1="${(X(realUpTo) + X(realUpTo + 1)) / 2}"
      x2="${(X(realUpTo) + X(realUpTo + 1)) / 2}" y1="${m.t}" y2="${m.t + ih}" stroke="var(--ink)" stroke-opacity=".3"/>` : "";
  // a marked index: where the change window picked starts, dashed, with its name
  const mark = o.mark != null && o.mark >= 0 && o.mark < n ? `<line x1="${X(o.mark)}" x2="${X(o.mark)}"
      y1="${m.t}" y2="${m.t + ih}" stroke="var(--accent)" stroke-opacity=".55" stroke-dasharray="4 4"/>
      <text x="${X(o.mark) + 5}" y="${m.t + 11}" class="vcap" style="fill:var(--accent)">${esc(o.markLabel || "")}</text>` : "";
  const annotations=(o.annotations||[]).filter(a=>vals.has(a.team)&&Number.isInteger(a.index)&&a.index>=0&&a.index<n&&Number.isFinite(vals.get(a.team)[a.index])).map(a=>{
    const value=vals.get(a.team)[a.index],colour=PALETTE[col[a.team]??0];
    return `<g data-line-event="${esc(a.id)}" data-line-team="${esc(a.team)}" data-line-index="${a.index}" data-line-value="${value}" data-line-score="${esc(a.text||'')}" tabindex="0" role="img" aria-label="${esc(a.label)}" data-tip="${esc(a.tip)}" opacity="${lit.includes(a.team)?1:.35}"><circle cx="${X(a.index)}" cy="${Y(value)}" r="${a.text?12:7}" fill="var(--panel)" stroke="${colour}" stroke-width="2.5"/><text x="${X(a.index)}" y="${Y(value)+3}" text-anchor="middle" style="fill:${colour};font-size:8px;font-weight:800;pointer-events:none">${esc(a.text||'G')}</text><circle cx="${X(a.index)}" cy="${Y(value)}" r="16" fill="transparent"/></g>`;
  }).join('');
  LC[id] = {n, X, Y, W, vals, lit, col, references, labels: o.readout || labels, fmt, what: o.what || "a round"};
  const chips = (o.order || teams).map((t) => `<button data-hl="${esc(t)}" aria-pressed="${lit.includes(t)}">${lit.includes(t)
    ? `<i style="background:${PALETTE[col[t] ?? 0]}"></i>` : ""}${esc(t)}</button>`).join("");
  return `<div class="scroll"><svg id="${id}" class="vchart" viewBox="0 0 ${W} ${H}" role="img"
      style="max-width:${W}px;min-width:620px;cursor:crosshair">${grid}${baselines}${today}${mark}${faint}${bright}${labs}
      <line id="${id}x" x1="0" x2="0" y1="${m.t}" y2="${m.t + ih}" stroke="var(--ink)" stroke-opacity="0"/>
      <g id="${id}d"></g>${hit}${annotations}</svg></div>
    <div id="${id}o" class="keys" style="min-height:24px;margin-top:6px"></div>
    ${chartHighlightsHtml(chips, lit.length)}`;
}
  return {scatter,lineChart};
}

export function entityFollowButtonHtml(entity,following=[]) {
  const followed=following.includes(entity.id);
  return `<button class="ghost follow-button" data-follow-entity="${esc(entity.id)}" aria-label="${followed?'Unfollow':'Follow'} ${esc(entity.name)}" aria-pressed="${followed}">${followed?'Following':'Follow'}</button>`;
}

export function playerCardHtml(result,players,id,{competition,competitionOrder=[],label=c=>c,following=[],settled=true}={}) {
  const entity=playerEntities(result,players).find(e=>e.id===id);
  if(!entity)return `<div class="card"><div class="head"><h2>Player unavailable</h2><button class="x" data-player-close>Close</button></div><p class="note">${settled?'No player evidence at this cutoff. Your follow is retained.':'Loading player evidence…'}</p></div>`;
  const fields=[['matches','PL'],['minutes','MIN'],['goals','Goals'],['xg','xG'],['assists','Assists'],['shots','Shots']];
  const stats=(source,competition,club='')=>`<dl class="player-facts">${fields.map(([metric,name])=>{const value=Number.isFinite(source[metric])?source[metric]:null;return `<div data-player-evidence="${esc([id,competition,club,metric].join('|'))}" data-value="${value??''}"><dt>${name}</dt><dd>${value==null?'—':metric==='xg'?value.toFixed(2):value}</dd></div>`;}).join('')}</dl>`;
  const rows=entity.rows.slice().sort((a,b)=>Number(b.competition===competition)-Number(a.competition===competition)||competitionOrder.indexOf(a.competition)-competitionOrder.indexOf(b.competition)||a.competition.localeCompare(b.competition));
  return `<div class="card" data-player-inspector="${esc(id)}"><div class="head"><h2>${esc(entity.name)}</h2>${entityFollowButtonHtml(entity,following)}<button class="ghost" data-player-profile="${esc(id)}">Full profile</button><button class="x" id="player-close" data-player-close>Close</button></div>
    <p class="note">${esc(entity.teams.join(' / '))} · season ${result.params.season}/${String(result.params.season+1).slice(-2)} · data through ${esc(result.as_of)}</p>
    <p class="note"><b>Covered appearances</b> · xG includes penalties · — unavailable · competitions kept separate</p>
    ${rows.map(r=>`<section class="comp"><div class="home-section-head"><h3>${esc(label(r.competition))}</h3><button class="text-button" data-player-leaders="${esc(r.competition)}">Leaders</button></div>${stats(r.source,r.competition)}<p class="note">Competition coverage ${r.coverage.covered??'—'} / ${r.coverage.played??'—'} played matches${r.coverage.xg_accounting?.outside_rounding?' · player and team xG may differ':''}</p>${Object.keys(r.source.by_team||{}).length>1?`<details><summary>Club contributions</summary>${Object.entries(r.source.by_team).map(([team,source])=>`<h4>${esc(team)}</h4>${stats(source,r.competition,team)}`).join('')}</details>`:''}</section>`).join('')}</div>`;
}

export function routeHash(state) {
  const {TAB,WORKSPACE,WORKSPACE_SECTION,RESULT,COLUMN_PROFILE,VIZSEL,RATSEL,RATINGS,DWIN,DWIN_DEFAULT,GWSEL,DISTMODE,PATHSEL,FXMODE,HUBSEL,PLAYER_METRIC,PLAYER_TEAM,PLAYER_MINUTES,BIG,BIGMODE,MOVERS,MOVERSEL,FOCUS,TEAM_PAGE,MATCH_FOCUS,MATCH_COMP,PLAYER_FOCUS,selectedView,kind,extra}=state;
  const h = new URLSearchParams({tab: TAB});
  if(WORKSPACE)h.set('section',canonicalSection(WORKSPACE_SECTION));
  if(WORKSPACE && RESULT?.source?.kind==='snapshot')h.set('date',RESULT.source.date);
  if(WORKSPACE && RESULT?.source?.projection_sha256)h.set('pr',RESULT.source.projection_sha256);
  const v = selectedView;
  if (v !== "overview") h.set("view", v);
  // Always include the selected profile on Overview: pasted links override local preferences.
  if (v === "overview" && !extra && kind !== "cup") h.set("cols", COLUMN_PROFILE);
  if (v === "viz" || TAB === "Visualisations") h.set("viz", VIZSEL);
  if ((TAB === RATINGS || TAB === "Visualisations" && VIZSEL === "ratings") && RATSEL !== "all") h.set("of", RATSEL);
  if (DWIN !== DWIN_DEFAULT) h.set("dw", DWIN);
  if ((v === "gw" || v === "phase") && GWSEL[TAB]) h.set("round", GWSEL[TAB]);
  if ((v === "position" || v === "points") && DISTMODE !== "exact") h.set("dist", DISTMODE);
  if (v === "paths" && PATHSEL[TAB]) h.set("path", PATHSEL[TAB]);
  if ((v === "gw" || v === "phase" || v === "fx") && GWSEL[TAB] && !h.has("round")) h.set("round", GWSEL[TAB]);
  if (v === "fx" && FXMODE !== "round") h.set("fx", FXMODE);
  if (v === "stats" && HUBSEL !== "team") h.set("hub", HUBSEL);
  if (v === "stats" && HUBSEL === "players") {
    if (PLAYER_METRIC !== "goals") h.set("pm", PLAYER_METRIC);
    if (PLAYER_TEAM !== "all") h.set("pt", PLAYER_TEAM);
    if (PLAYER_METRIC === "xg90" && PLAYER_MINUTES !== 180) h.set("min", PLAYER_MINUTES);
  }
  if (TAB === BIG && BIGMODE !== "week") h.set("big", BIGMODE);
  if ((TAB === MOVERS || TAB === "Visualisations" && VIZSEL === "changes") && MOVERSEL !== "title") h.set("category", MOVERSEL);
  if (FOCUS) h.set("team", FOCUS);
  if (FOCUS && TEAM_PAGE) h.set("page", "1");
  if (MATCH_FOCUS) h.set("match", MATCH_FOCUS);
  if (MATCH_FOCUS && MATCH_COMP) h.set("mc", MATCH_COMP);
  if(WORKSPACE&&['home','matches'].includes(WORKSPACE_SECTION)){
    h.set('mv',state.MATCHES_VIEW||'agenda');
    if(state.MATCH_PAGE){h.set('centre','1');h.set('mt',state.MATCH_TAB||'preview');if(state.MATCH_REPLAY>=0)h.set('replay',state.MATCH_REPLAY);}
    if(state.AGENDA_PERIOD&&state.AGENDA_PERIOD!=='week')h.set('ap',state.AGENDA_PERIOD);
    if(state.AGENDA_COMP&&state.AGENDA_COMP!=='all')h.set('ac',state.AGENDA_COMP);
    if(state.AGENDA_SCOPE==='following')h.set('scope','following');
    if(state.AGENDA_DATE)h.set('ad',state.AGENDA_DATE);
    if(state.HOME_MATCH)h.set('hm',state.HOME_MATCH);
    if(state.WATCH_PLAN?.size)h.set('watch',JSON.stringify([...state.WATCH_PLAN]));
  }
  if(WORKSPACE&&(TEAM_PAGE||WORKSPACE_SECTION==='clubs')){
    h.set('clubsection',state.CLUB_SECTION||'season');
    if(state.CLUB_SCOPE&&state.CLUB_SCOPE!=='all')h.set('clubcomp',state.CLUB_SCOPE);
    if(state.CLUB_VIEW==='compare')h.set('clubview','compare');
    if(state.CLUB_COMPARE?.length)h.set('clubs',JSON.stringify(state.CLUB_COMPARE));
    if(state.CLUB_COMPARE_SCOPE&&state.CLUB_COMPARE_SCOPE!=='all')h.set('comparecomp',state.CLUB_COMPARE_SCOPE);
    if(state.CLUB_VENUE&&state.CLUB_VENUE!=='all')h.set('clubvenue',state.CLUB_VENUE);
    if(state.CLUB_PERIOD==='window')h.set('clubperiod','window');
    if(state.CLUB_CHART&&state.CLUB_CHART!=='trajectory')h.set('clubchart',state.CLUB_CHART);
    if(state.CLUB_HISTORY&&state.CLUB_HISTORY!=='fates')h.set('clubhist',state.CLUB_HISTORY);
    if(state.CLUB_PEER_COHORT==='scope')h.set('clubpeer','scope');
    if(state.CLUB_CHART_SOURCE==='real')h.set('clubsrc','real');
    if(state.CLUB_MARKS==='dots')h.set('clubmarks','dots');
    if(state.CLUB_TAILS===false)h.set('clubtails','0');
    if(Array.isArray(state.CLUB_HIGHLIGHTS))h.set('clubhl',JSON.stringify(state.CLUB_HIGHLIGHTS));
  }
  if(WORKSPACE && WORKSPACE_SECTION==='players'){
    h.set('pview',state.PLAYER_WORKSPACE_VIEW||'overview');
    if(state.PLAYER_EVIDENCE_TEAM&&state.PLAYER_EVIDENCE_TEAM!=='all')h.set('pclub',state.PLAYER_EVIDENCE_TEAM);
    if(state.PLAYER_SCOPE&&state.PLAYER_SCOPE!=='all')h.set('pscope',state.PLAYER_SCOPE);
    if(state.PLAYER_PROFILE_ID)h.set('profile',state.PLAYER_PROFILE_ID);
    if(state.PLAYER_COMPARE?.length)h.set('pc',JSON.stringify(state.PLAYER_COMPARE));
    if(state.PLAYER_COMPARE_UNIT==='rate')h.set('pcunit','rate');
    if(state.PLAYER_DISCOVERY_STAT&&state.PLAYER_DISCOVERY_STAT!=='xa')h.set('pmetric',state.PLAYER_DISCOVERY_STAT);
    if(state.PLAYER_DISCOVERY_UNIT==='rate')h.set('punit','rate');
    if(state.PLAYER_DISCOVERY_MIN!=null&&state.PLAYER_DISCOVERY_MIN!==180)h.set('pfloor',state.PLAYER_DISCOVERY_MIN);
    if(state.PLAYER_OVERVIEW_SORT&&state.PLAYER_OVERVIEW_SORT!=='goals')h.set('psort',state.PLAYER_OVERVIEW_SORT);
    if(state.PLAYER_QUERY)h.set('pquery',state.PLAYER_QUERY);
    if(state.PLAYER_SQUAD_TEAM)h.set('squad',state.PLAYER_SQUAD_TEAM);
    if(state.PLAYER_SQUAD_METRIC&&state.PLAYER_SQUAD_METRIC!=='xa')h.set('smetric',state.PLAYER_SQUAD_METRIC);
  }
  if(WORKSPACE&&WORKSPACE_SECTION==='clubs'&&state.CLUB_SECTION==='atlas'){
    for(const [key,value] of [['at',state.ATLAS_TEAM],['acomp',state.ATLAS_COMP],['aside',state.ATLAS_SIDE],['atype',state.ATLAS_TYPE],['avenue',state.ATLAS_VENUE],['aperiod',state.ATLAS_PERIOD],['achart',state.ATLAS_CHART],['against',state.ATLAS_COMPARE],['abin',state.ATLAS_BIN]])if(value)h.set(key,value);
  }
  if (WORKSPACE && PLAYER_FOCUS) h.set("player", PLAYER_FOCUS);
  return "#"+h.toString();
}

// Club command centre: selectors share one cutoff and never combine overlapping aggregates.
export const CLUB_SECTIONS=[['season','Season'],['performance','Performance'],['atlas','Tactical Atlas'],['squad','Squad'],['schedule','Schedule'],['history','History']];
export const clubFixtureId=f=>[f.competition,f.home,f.away,String(f.kickoff).slice(0,10)].join('|');
const clubDayFormat=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/London',year:'numeric',month:'2-digit',day:'2-digit'});
export const clubDay=f=>clubDayFormat.format(new Date(fixtureInstant(f.kickoff,f.competition)));
export function clubScopeIncludes(result,competition,scope='all'){
 return scope==='all'||scope==='leagues'&&(result.leagues||[]).some(b=>b.competition===competition)||scope===competition;
}
export function clubFixturePool(result,gw=null,agenda=null,extras=[]){
 const raw=[];for(const category of ['leagues','phases'])for(const [competition,b] of Object.entries(gw?.[category]||{}))raw.push(...(b.fixtures||[]).map(f=>({...f,competition,stakes_of:f.stakes_of||b.stakes_of})));
 raw.push(...(agenda?.fixtures||[]),...extras);
 const found=new Map(),conditional=[],conflicts=[];let duplicates=0;
 for(const f of raw){
  if(!f.competition||!f.home||!f.away||!Number.isFinite(fixtureInstant(f.kickoff||'',f.competition)))continue;
  const day=f.kickoff.slice(0,10);if(f.result&&day>result.as_of)continue;
  if(f.result&&(!Array.isArray(f.result)||f.result.length!==2||f.result.some(v=>!Number.isInteger(v)||v<0)))continue;
  if(f.tbd===true||(finite(f.p_occurs)&&f.p_occurs<1)){conditional.push(f);continue;}
  const id=clubFixtureId(f),prior=found.get(id);
  if(prior){duplicates++;if(prior.result&&f.result&&prior.result.join('-')!==f.result.join('-'))conflicts.push(id);
   found.set(id,{...f,...prior,result:prior.result||f.result,xg:prior.xg||f.xg,minutes:prior.minutes??f.minutes,outcome:prior.outcome||f.outcome});
  }else found.set(id,{...f,id});
 }
 const order=(a,b)=>fixtureInstant(a.kickoff,a.competition)-fixtureInstant(b.kickoff,b.competition)||a.competition.localeCompare(b.competition)||a.home.localeCompare(b.home)||a.away.localeCompare(b.away);
 return {fixtures:[...found.values()].sort(order),conditional:[...new Map(conditional.map(f=>[clubFixtureId(f),f])).values()].sort(order),duplicates,conflicts:[...new Set(conflicts)]};
}
export function clubMatches(result,pool,team,{competition='all',venue='all',since=null}={}){
 return (pool?.fixtures||[]).filter(f=>f.result&&clubDay(f)<=result.as_of&&(!since||clubDay(f)>since)&&clubScopeIncludes(result,f.competition,competition)&&(venue==='home'?f.home===team:venue==='away'?f.away===team:f.home===team||f.away===team)).sort((a,b)=>fixtureInstant(a.kickoff,a.competition)-fixtureInstant(b.kickoff,b.competition)||clubFixtureId(a).localeCompare(clubFixtureId(b)));
}
export function clubPerformance(result,pool,team,options={}){
 const matches=clubMatches(result,pool,team,options),out={team,pl:matches.length,w:0,d:0,l:0,gf:0,ga:0,n_xg:0,known_xg:0,known_xga:0,minutes:0,n_minutes:0,matches};
 for(const f of matches){const home=f.home===team,[gf,ga]=home?f.result:[f.result[1],f.result[0]];out.gf+=gf;out.ga+=ga;out[gf>ga?'w':gf<ga?'l':'d']++;
  if(Array.isArray(f.xg)&&f.xg.length===2&&f.xg.every(v=>finite(v)&&v>=0)){out.n_xg++;out.known_xg+=f.xg[home?0:1];out.known_xga+=f.xg[home?1:0];}
  if(finite(f.minutes)&&f.minutes>0){out.minutes+=f.minutes;out.n_minutes++;}
 }
 out.gd=out.gf-out.ga;out.xg=out.n_xg===out.pl&&out.pl?out.known_xg:null;out.xga=out.n_xg===out.pl&&out.pl?out.known_xga:null;
 out.xgf_rate=out.n_xg?out.known_xg/out.n_xg:null;out.xga_rate=out.n_xg?out.known_xga/out.n_xg:null;out.xgd_rate=out.n_xg?(out.known_xg-out.known_xga)/out.n_xg:null;
 return out;
}
export function clubStrength(result,team,competition='all'){
 if(competition==='leagues')competition='all';
 const raw=result?.ratings?.teams?.find(r=>r.team===team);if(!raw)return {supported:false,scale:competition,reason:'No rating at this cutoff.'};
 const factor=result.ratings.rel?.[competition]?.now;
 if(competition!=='all'&&(!factor||factor.length!==2||factor.some(v=>!finite(v)||v<=0)))return {supported:false,scale:competition,elo:raw.elo,reason:'Competition strength scale unavailable.'};
 const att=finite(raw.att)?raw.att*(competition==='all'?1:factor[0]):null,def=finite(raw.def)?raw.def*(competition==='all'?1:factor[1]):null;
 return {supported:att!=null&&def!=null,scale:competition,elo:raw.elo,att,def,net:att==null||def==null?null:att-def,raw};
}
export function clubSchedule(result,pool,team){
 const fixtures=pool.fixtures.filter(f=>f.home===team||f.away===team),conditional=pool.conditional.filter(f=>f.home===team||f.away===team);
 return fixtures.map((f,i)=>{const previous=fixtures[i-1],between=previous&&conditional.some(c=>c.kickoff>previous.kickoff&&c.kickoff<f.kickoff);
  return {...f,venue:f.home===team?'Home':'Away',opponent:f.home===team?f.away:f.home,gap:previous&&!between?(fixtureInstant(f.kickoff,f.competition)-fixtureInstant(previous.kickoff,previous.competition))/86400000:null,gap_blocked:Boolean(between),previous:previous?.id||null};});
}
export function clubWorkload(result,pool,team,days=14){
 const cutoff=Date.parse(result.as_of+'T00:00:00Z'),since=new Date(cutoff-days*86400000).toISOString().slice(0,10),p=clubPerformance(result,pool,team,{since});
 return {days,matches:p.pl,minutes:p.n_minutes===p.pl&&p.pl?p.minutes:null,known_minutes:p.minutes,n_minutes:p.n_minutes};
}
export function clubPlayerContributions(result,players,team,competition='all'){
 if(!players||players.season!==result.params.season||players.as_of!==result.as_of)return {available:false,rows:[],competitions:[]};
 const rows=new Map(),covered=[];
 for(const [comp,block] of Object.entries(players.competitions||{})){
  if(!clubScopeIncludes(result,comp,competition))continue;let has=false;
  for(const player of block.players||[]){const source=player.by_team?.[team];if(!source)continue;has=true;
   const id=String(player.id),row=rows.get(id)||{id,name:player.name,parts:[]};row.parts.push({competition:comp,source});rows.set(id,row);
  }if(has)covered.push(comp);
 }
 for(const row of rows.values())for(const key of ['matches','minutes','goals','xg','assists','shots'])row[key]=row.parts.every(p=>finite(p.source[key]))?row.parts.reduce((sum,p)=>sum+p.source[key],0):null;
 return {available:true,competitions:covered,rows:[...rows.values()].sort((a,b)=>(b.minutes??-1)-(a.minutes??-1)||a.name.localeCompare(b.name)||a.id.localeCompare(b.id))};
}
export function clubComparison(result,pool,names,options={}){
 const unique=[...new Set(names)].slice(0,4),scope=options.competition||'all';
 const member=team=>[...(result.leagues||[]),...(result.uefa||[]),...(result.cups||[])].some(b=>clubScopeIncludes(result,b.competition,scope)&&b.teams.some(t=>t.team===team))||pool.fixtures.some(f=>clubScopeIncludes(result,f.competition,scope)&&(f.home===team||f.away===team));
 const unsupported=scope==='all'?[]:unique.filter(t=>!member(t));
 const rows=unique.map(team=>({team,performance:clubPerformance(result,pool,team,options),strength:clubStrength(result,team,scope)}));
 return {rows,scale:scope,unsupported,valid:unique.length>=2&&unique.length<=4&&unsupported.length===0,reason:unsupported.length?'Selected competition does not cover: '+unsupported.join(', '):unique.length<2?'Choose two to four clubs.':''};
}
export function clubFormComparison(result,pool,names,options={}){
 const series=new Map();for(const team of names){const rows=clubMatches(result,pool,team,options);
  series.set(team,rows.map((f,i)=>{const last=rows.slice(Math.max(0,i-4),i+1),value=last.every(x=>Array.isArray(x.xg)&&x.xg.length===2&&x.xg.every(v=>finite(v)&&v>=0))?last.reduce((sum,x)=>sum+(x.home===team?x.xg[0]-x.xg[1]:x.xg[1]-x.xg[0]),0)/last.length:null;return {date:clubDay(f),value};}));}
 const dates=[...new Set([...series.values()].flatMap(rows=>rows.map(f=>f.date)))].sort();
 const vals=new Map([...series].map(([team,rows])=>[team,dates.map(day=>{const available=rows.filter(r=>r.date<=day);return available.at(-1)?.value??null;})]));
 return {dates,vals,source:series};
}
export function clubPeers(result,pool,anchor,{competition='all',venue='all',since=null,minimum=3,limit=8}={}){
 const blocks=['all','leagues'].includes(competition)?result.leagues||[]:[...(result.leagues||[]),...(result.uefa||[]),...(result.cups||[])].filter(b=>b.competition===competition);
 const names=[...new Set(blocks.flatMap(b=>b.teams.map(t=>t.team)))].sort(),features=['ATT','DEF','xG for / match','xG against / match'];
 const vectors=names.map(team=>{const r=clubStrength(result,team,competition),p=clubPerformance(result,pool,team,{competition,venue,since});return {team,covered:p.n_xg,played:p.pl,values:[r.att,r.def,p.n_xg>=minimum?p.xgf_rate:null,p.n_xg>=minimum?p.xga_rate:null]};});
 const target=vectors.find(r=>r.team===anchor),complete=vectors.filter(r=>r.values.every(finite));
 if(!target||!target.values.every(finite)||complete.length<3)return {rows:[],features,population:names.length,covered:complete.length,minimum,reason:'Peer discovery needs a covered rating and at least '+minimum+' xG matches for the anchor and three clubs in the selected cohort.'};
 const means=features.map((_,i)=>complete.reduce((a,r)=>a+r.values[i],0)/complete.length),sd=features.map((_,i)=>Math.sqrt(complete.reduce((a,r)=>a+(r.values[i]-means[i])**2,0)/complete.length)),used=sd.map((s,i)=>s>1e-12?i:-1).filter(i=>i>=0);
 if(!used.length)return {rows:[],features,population:names.length,covered:complete.length,minimum,reason:'The covered features do not vary in this cohort.'};
 const rows=complete.filter(r=>r.team!==anchor).map(r=>({...r,distance:Math.sqrt(used.reduce((sum,i)=>sum+((r.values[i]-target.values[i])/sd[i])**2,0)/used.length)})).sort((a,b)=>a.distance-b.distance||a.team.localeCompare(b.team)).slice(0,limit);
 return {rows,features,means,sd,used,target,population:names.length,covered:complete.length,minimum};
}
export function fixtureParts(f,competitionLabel=f.competition){
 const instant=fixtureInstant(f.kickoff,f.competition),time=new Date(instant),stamp=Number.isNaN(+time)?'Kickoff unavailable':ukFixtureFormat.format(time);
 const raw=Array.isArray(f.result)?f.result:[f.home_goals,f.away_goals],played=f.result!==null&&f.played!==false&&f.played!=='false'&&(Array.isArray(f.result)||raw.every(v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v))));
 const score=played?raw.map(v=>Number.isFinite(Number(v))?String(Number(v)):'—'):null;
 return {instant,stamp,competition:competitionLabel,home:f.home,away:f.away,score,qualifier:f.outcome==='afterextratime'?'AET':f.outcome==='penalties'?'before shootout':''};
}
export function fixtureSentence(f,competitionLabel=f.competition){
 const p=fixtureParts(f,competitionLabel);return p.stamp+' · '+p.competition+' · '+p.home+(p.score?' '+p.score[0]:'')+' - '+p.away+(p.score?' '+p.score[1]:'')+(p.qualifier?' ('+p.qualifier+')':'');
}
export function fixtureHtml(f,competitionLabel=f.competition,{badge=()=>'',metadata=[]}={}){
 const p=fixtureParts(f,competitionLabel),score=p.score?p.score.join('–'):'v',compact=teamCode(p.home)!==teamCode(p.away),name=team=>compact?`<span class="fixture-team-name">${esc(team)}</span><abbr class="fixture-team-code" title="${esc(team)}" aria-label="${esc(team)}">${esc(teamCode(team))}</abbr>`:`<span>${esc(team)}</span>`;
 return `<span class="fixture-summary" data-fixture-home="${esc(p.home)}" data-fixture-away="${esc(p.away)}" data-fixture-score="${p.score?esc(p.score.join('-')):''}"><span class="fixture-main"><span class="fixture-side">${badge(p.home)}${name(p.home)}</span><strong class="fixture-score">${esc(score)}</strong><span class="fixture-side fixture-away">${badge(p.away)}${name(p.away)}</span></span><span class="fixture-meta"><time${Number.isFinite(p.instant)?` datetime="${new Date(p.instant).toISOString()}"`:''}>${esc(p.stamp)}</time><span>${esc(p.competition)}</span>${[p.qualifier,...metadata].filter(Boolean).map(s=>`<span>${esc(s)}</span>`).join('')}</span></span>`;
}
export function clubConditionalStages(result,team,competition='all'){
 const rows=[];
 for(const b of [...(result.uefa||[]),...(result.cups||[])]){
  if(!clubScopeIncludes(result,b.competition,competition))continue;
  const side=b.teams.find(t=>t.team===team);if(!side)continue;
  for(const stage of ['PO','R64','R32','R16','QF','SF','F']){const probability=side['p_'+stage.toLowerCase()];if(finite(probability)&&probability>0&&probability<1)rows.push({competition:b.competition,stage,probability,date:null,opponent:null});}
 }
 return rows;
}

// Player discovery: one identity, disjoint competition/club contributions, explicit coverage.
export const SCOUT_METRICS=[['xa','xA'],['chances_created','Chances created'],['assists','Assists']];
export const PROFILE_METRICS=[['minutes','MIN'],['goals','Goals'],['xg','xG'],...SCOUT_METRICS,['shots','Shots']];
const playerEvidenceCaches=new WeakMap();
export function playerEvidenceIndex(result,players){
 if(!result||!players||players.season!==result?.params?.season||players.as_of!==result?.as_of)return {available:false,entities:[],byId:new Map(),clubs:[],competitions:[]};
 let cache=playerEvidenceCaches.get(result);if(cache?.players===players)return cache.index;
 const entities=playerEntities(result,players).map(entity=>({...entity,parts:entity.rows.flatMap(row=>{
  const allocated=Object.entries(row.source.by_team||{});
  return allocated.length?allocated.map(([team,source])=>({competition:row.competition,team,source})): [{competition:row.competition,team:null,source:row.source}];
 })}));
 const index={available:true,entities,byId:new Map(entities.map(e=>[e.id,e])),clubs:[...new Set(entities.flatMap(e=>e.parts.map(p=>p.team)).filter(Boolean))].sort((a,b)=>a.localeCompare(b)),competitions:Object.keys(players.competitions||{}).sort()};
 playerEvidenceCaches.set(result,{players,index});return index;
}
export function playerEvidenceParts(entity,{competition='all',team='all'}={}){return (entity?.parts||[]).filter(p=>(competition==='all'||p.competition===competition)&&(team==='all'||p.team===team));}
export function contributionEvidence(parts,metric){
 if(!parts.length)return {total:null,observed:null,known:0,unknown:0,appearances:0,complete:false};
 let appearances=0,known=0,observed=0,hasObserved=false,complete=true,total=0;
 for(const {source:s} of parts){
  const n=finite(s.matches)?s.matches:0,k=finite(s.known?.[metric])?s.known[metric]:finite(s[metric])?n:0;
  appearances+=n;known+=k;
  if(finite(s[metric])&&k===n){total+=s[metric];observed+=s[metric];hasObserved=true;}
  else{complete=false;if(finite(s.observed?.[metric])&&k>0){observed+=s.observed[metric];hasObserved=true;}}
 }
 return {total:complete?total:null,observed:hasObserved?observed:null,known,unknown:appearances-known,appearances,complete};
}
export function contributionRate(parts,metric){
 const value=contributionEvidence(parts,metric),minutes=contributionEvidence(parts,'minutes');
 return {value:value.complete&&minutes.complete&&minutes.total>0?90*value.total/minutes.total:null,numerator:value.total,minutes:minutes.total,appearances:value.appearances};
}
export function creatorDiscovery(result,players,{competition='all',team='all',metric='xa',unit='total',minimum=180,query='',limit=50}={}){
 const index=playerEvidenceIndex(result,players),valid=SCOUT_METRICS.some(([key])=>key===metric);if(!index.available||!valid)return {available:index.available,rows:[],total:0,eligible:0,unknown:0,belowFloor:0,omitted:0};
 const q=searchText(query).trim(),source=index.entities.flatMap(entity=>{
  const parts=playerEvidenceParts(entity,{competition,team});if(!parts.length||q&&!searchText([entity.name,...entity.aliases,...parts.map(p=>p.team||'')].join(' ')).includes(q))return [];
  const evidence=contributionEvidence(parts,metric),minutes=contributionEvidence(parts,'minutes'),rate=contributionRate(parts,metric);
  return [{id:entity.id,name:entity.name,teams:[...new Set(parts.map(p=>p.team).filter(Boolean))],parts,evidence,minutes,rate,value:unit==='rate'?rate.value:evidence.total}];
 });
 const known=source.filter(r=>finite(r.value)),eligible=known.filter(r=>minimum===0||finite(r.minutes.total)&&r.minutes.total>=minimum).sort((a,b)=>b.value-a.value||(b.minutes.total??-1)-(a.minutes.total??-1)||a.name.localeCompare(b.name)||a.id.localeCompare(b.id));
 return {available:true,rows:eligible.slice(0,limit),total:source.length,eligible:eligible.length,unknown:source.length-known.length,belowFloor:known.length-eligible.length,omitted:Math.max(0,eligible.length-limit)};
}
export function playerProfileEvidence(result,players,id,options={}){
 const index=playerEvidenceIndex(result,players),entity=index.byId.get(id),parts=playerEvidenceParts(entity,options);
 return {available:index.available,entity,parts,metrics:Object.fromEntries(PROFILE_METRICS.map(([key])=>[key,contributionEvidence(parts,key)])),stints:parts.map(p=>({...p,metrics:Object.fromEntries(PROFILE_METRICS.map(([key])=>[key,contributionEvidence([p],key)]))}))};
}
export function squadContributionEvidence(result,players,team,{competition='all',metric='xa'}={}){
 const index=playerEvidenceIndex(result,players);if(!index.available)return {available:false,rows:[],evidence:contributionEvidence([],metric),denominator:null,top3:null,teams:[],coveredMatches:0,playedMatches:0};
 const rows=index.entities.flatMap(e=>{const parts=playerEvidenceParts(e,{competition,team});if(!parts.length)return [];return [{id:e.id,name:e.name,parts,evidence:contributionEvidence(parts,metric),minutes:contributionEvidence(parts,'minutes')}];});
 const allParts=rows.flatMap(r=>r.parts),evidence=contributionEvidence(allParts,metric),denominator=evidence.observed;
 const ordered=rows.map(r=>({...r,share:finite(denominator)&&denominator>0&&finite(r.evidence.observed)?r.evidence.observed/denominator:null})).sort((a,b)=>(b.evidence.observed??-1)-(a.evidence.observed??-1)||a.name.localeCompare(b.name)||a.id.localeCompare(b.id));
 const teams=Object.entries(players?.competitions||{}).filter(([c])=>competition==='all'||c===competition).flatMap(([c,b])=>b.teams?.[team]?[{competition:c,...b.teams[team]}]:[]);
 return {available:index.available,rows:ordered,evidence,denominator,top3:denominator>0?ordered.slice(0,3).reduce((sum,r)=>sum+(r.share||0),0):null,teams,coveredMatches:teams.reduce((sum,t)=>sum+(t.covered||0),0),playedMatches:teams.reduce((sum,t)=>sum+(t.played||0),0)};
}

// Overview keeps every scoped player; an unavailable statistic never removes their row.
export const OVERVIEW_METRICS=[['goals','Goals'],['xg','xG'],['assists','Assists'],['xa','xA'],['ga','G/A'],['xga','xG/A']];
export function playerOverview(result,players,{competition='all',team='all',sort='goals',query='',limit=50}={}){
 const index=playerEvidenceIndex(result,players),q=searchText(query).trim(),metric=OVERVIEW_METRICS.some(([k])=>k===sort)||sort==='minutes'?sort:'goals';
 const rows=index.entities.flatMap(e=>{
  const parts=playerEvidenceParts(e,{competition,team});
  if(!parts.length||q&&!searchText([e.name,...e.aliases,...parts.map(p=>p.team||'')].join(' ')).includes(q))return [];
  const metrics=Object.fromEntries(['minutes','goals','xg','assists','xa'].map(k=>[k,contributionEvidence(parts,k).total]));
  metrics.ga=finite(metrics.goals)&&finite(metrics.assists)?metrics.goals+metrics.assists:null;
  metrics.xga=finite(metrics.xg)&&finite(metrics.xa)?metrics.xg+metrics.xa:null;
  return [{id:e.id,name:e.name,teams:[...new Set(parts.map(p=>p.team).filter(Boolean))],parts,metrics,appearances:contributionEvidence(parts,'minutes').appearances}];
 }).sort((a,b)=>Number(b.metrics[metric]!=null)-Number(a.metrics[metric]!=null)||(b.metrics[metric]??0)-(a.metrics[metric]??0)||(b.metrics.minutes??-1)-(a.metrics.minutes??-1)||a.name.localeCompare(b.name)||a.id.localeCompare(b.id));
 return {available:index.available,rows:rows.slice(0,limit),total:rows.length,sort:metric};
}

export const COMPARISON_METRICS=[...OVERVIEW_METRICS,['shots','Shots'],['chances_created','Chances created']];
const playerComparisonCaches=new WeakMap();
export function playerComparison(result,players,ids,{competition='all',team='all',unit='total',minimum=180}={}){
 const index=playerEvidenceIndex(result,players),keys=COMPARISON_METRICS.map(([k])=>k);
 const cacheKey=JSON.stringify([competition,team,unit,minimum,[...new Set(ids)].slice(0,4)]);let cache=playerComparisonCaches.get(index);if(!cache){cache=new Map();playerComparisonCaches.set(index,cache);}if(cache.has(cacheKey))return cache.get(cacheKey);
 const build=entity=>{
  const parts=playerEvidenceParts(entity,{competition,team}),minutes=contributionEvidence(parts,'minutes'),metrics={};
  for(const k of keys){const components=k==='ga'?['goals','assists']:k==='xga'?['xg','xa']:[k],evidence=components.map(c=>contributionEvidence(parts,c)),complete=parts.length>0&&evidence.every(e=>e.complete),total=complete?evidence.reduce((s,e)=>s+e.total,0):null,rate=complete&&minutes.complete&&minutes.total>0&&minutes.total>=minimum?90*total/minutes.total:null;
   metrics[k]={total,value:unit==='rate'?rate:total,known:components.length===1?evidence[0].known:complete?minutes.appearances:null,coverage:components.map((key,i)=>({key,known:evidence[i].known})),appearances:minutes.appearances,complete,percentile:null};}
  return {id:entity?.id,name:entity?.name,parts,minutes,metrics};
 };
 const cohort=index.entities.map(build).filter(r=>r.parts.length&&r.minutes.complete&&r.minutes.total>=minimum),populations=Object.fromEntries(keys.map(k=>[k,cohort.map(r=>r.metrics[k].value).filter(finite).sort((a,b)=>a-b)]));
 const rows=[...new Set(ids)].slice(0,4).map(id=>{const entity=index.byId.get(id),row=build(entity);row.id=id;row.name=entity?.name||'Player unavailable';for(const k of keys){const values=populations[k],v=row.metrics[k].value;if(values.length>=3&&finite(v)&&row.minutes.complete&&row.minutes.total>=minimum)row.metrics[k].percentile=100*(values.filter(x=>x<v).length+.5*values.filter(x=>x===v).length)/values.length;}return row;});
 const answer={available:index.available,rows,populations,minimum,unit,valid:rows.length>=2&&rows.every(r=>r.parts.length>0)};if(cache.size>=32)cache.clear();cache.set(cacheKey,answer);return answer;
}

export const TEAM_SHORT_NAMES = {"RCD Espanyol de Barcelona": "Espanyol", "Borussia Mönchengladbach": "M'gladbach",
  "Olympique de Marseille": "Marseille", "RC Strasbourg Alsace": "Strasbourg",
  "Havre Athletic Club": "Le Havre", "Sport-Club Freiburg": "Freiburg", "Paris Saint-Germain": "PSG",
  "Eintracht Frankfurt": "Frankfurt", "Bayer 04 Leverkusen": "Leverkusen",
  "Olympique Lyonnais": "Lyon", "Atlético de Madrid": "Atlético", "1. FC Union Berlin": "Union Berlin",
  "Borussia Dortmund": "Dortmund", "Stade Brestois 29": "Brest", "FC Bayern München": "Bayern",
  "Stade Rennais FC": "Rennes", "Deportivo Alavés": "Alavés", "SV Werder Bremen": "Bremen",
  "SC Paderborn 07": "Paderborn", "1. FSV Mainz 05": "Mainz", "TSG Hoffenheim": "Hoffenheim",
  "Internazionale": "Inter", "Union Saint-Gilloise": "Union SG", "Olympiakos Piraeus": "Olympiakos"};
export const shortTeamName = (t) => TEAM_SHORT_NAMES[t] || t.replace(/^(1\. )?(FC|AC|AS|SS|SSC|US|RC|RCD|CA|CD|UD|SD|VfL|VfB|SV|TSG|FSV|OGC|AFC|SC|FK|GNK|NK|HNK) /, "")
  .replace(/ (FC|CF|AC|SC|\d\d)$/, "");
export function teamCode(team){
 const words=shortTeamName(team).replace(/[^\p{L}\s]/gu,'').split(/\s+/).filter(Boolean);
 return (words.length>1?words[0][0]+words.at(-1).slice(0,2):(words[0]||'').slice(0,3)).toUpperCase();
}
