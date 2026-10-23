// Stored-only adapters. These read exported evidence; they never generate forecasts.
import {stored,recordResponse,read} from './pwa-storage.mjs';
const probabilities=['p_win','p_ucl','p_uel','p_uecl','p_releg'];
const numeric=v=>typeof v==='number'&&Number.isFinite(v);
const key=f=>[f.competition,f.home,f.away,String(f.kickoff).slice(0,10)].join('|');
const json=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});
const fail=(message,status=409)=>Object.assign(Error(message),{status});
// Decimal subtraction through integer coefficients preserves the Python bridge's accounting.
function decimal(value){const [base,exponent='0']=String(value).toLowerCase().split('e');const [whole,fraction='']=base.split('.');return [BigInt(whole+fraction),fraction.length-Number(exponent)];}
export function difference(a,b){if(!numeric(a)||!numeric(b))return null;const [x,sx]=decimal(a),[y,sy]=decimal(b),scale=Math.max(sx,sy,0);const value=y*10n**BigInt(scale-sy)-x*10n**BigInt(scale-sx);return Number(value)/10**scale;}
function exactString(v){return String(v);}
export function pointsBridge(a,b){if(!a||!b||[a,b].some(r=>['banked','expected_final','expected_remaining'].some(k=>!numeric(r[k]))))return null;for(const r of[a,b])if(Math.abs(difference(r.banked,r.expected_final)-r.expected_remaining)>1e-10)throw fail('Stored points bridge does not reconcile.');const banked=difference(a.banked,b.banked),final=difference(a.expected_final,b.expected_final),remaining=difference(difference(a.banked,a.expected_final),difference(b.banked,b.expected_final));return{banked,expected_final:final,expected_remaining:remaining,exact:{banked:exactString(banked),expected_final:exactString(final),expected_remaining:exactString(remaining)},residual:0};}
export async function staticRequest(url,options={}){
 try{
  const active=await read('meta','active');if(!active)throw fail('Import a MusSim data bundle from Files to start.',404);
  const get=async path=>{const r=await stored(path,active);if(!r)throw fail('This evidence is not in the imported bundle.',404);const value=JSON.parse(r.body);if(r.status!==200)throw fail(value.error||'Evidence unavailable.',r.status);return value;};
  const u=new URL(url,location.origin),q=u.searchParams,meta=await get('/api/meta'),day=q.get('date')||meta.snapshots.at(-1)?.date;
  if((options.method||'GET').toUpperCase()!=='GET'||u.pathname.startsWith('/api/job'))throw fail('This computation runs on your laptop. Imported forecasts remain available here.',422);
  if(u.pathname==='/api/meta')return json(meta);
  if(u.pathname==='/api/badges')return recordResponse(await stored('/api/badges',active));
  if(u.pathname==='/api/seasons')throw fail('Live forecasts run on your laptop.',422);
  if(u.pathname==='/api/history'||u.pathname==='/api/track'){const season=q.get('season')||(await get('/material/projection/'+day)).params.season;return recordResponse(await stored(u.pathname+'?season='+season,active));}
  const projection=await get('/material/projection/'+day),source=projection.source;
  if(q.get('pr')&&q.get('pr')!==source.projection_sha256)throw fail('This forecast revision changed. Reload the selected snapshot to use its current evidence.');
  if(u.pathname==='/api/scenario/catalog')return json({available:false,source,reason:'Scenario experiments run on your laptop. All stored forecasts can be browsed in MusSim.'});
  if(u.pathname==='/api/time-machine/catalog'||u.pathname==='/api/time-machine')return json(await timeMachine({day,source,q,get,projection}));
  if(u.pathname==='/api/match-centre'||u.pathname==='/api/atlas')return json(await matchEvidence({day,source,q,get,projection,atlas:u.pathname==='/api/atlas'}));
  const params=new URLSearchParams({date:day});
  if(u.pathname==='/api/performance'&&q.get('scope')==='all')params.set('scope','all');
  if(u.pathname==='/api/team-fixtures')params.set('team',q.get('team')||'');
  const record=await stored(u.pathname+'?'+params,active);
  if(record?.status===200&&q.get('ir')){const value=JSON.parse(record.body);if(value.input_revision!==q.get('ir'))throw fail('Stored evidence changed. Reset evidence to adopt the imported revision.');}
  return recordResponse(record);
 }catch(e){return json({error:e.message},e.status||500);}
}

async function timeMachine({day,source,q,get,projection}){
 const listed=await get('/material/index'),snapshots={};
 for(const row of listed.filter(r=>r.date<=day)){const item=await get('/material/compact/'+row.date);if(item.meta.season===projection.params.season)snapshots[row.date]=item;}
 const anchor=snapshots[day];if(!anchor)throw fail('Choose an available dashboard snapshot.',404);
 if(!q.get('pr'))throw fail('A pinned dashboard revision is required.');
 if(!q.has('a'))return {schema:1,source:anchor.meta,dates:Object.values(snapshots).map(s=>({...s.meta,competitions:Object.keys(s.leagues),invalid_cells:s.issues.length})),notice:'Stored snapshot evidence only. Folder date and data cutoff are different. Later rebuilds do not establish what was published at the time.'};
 const a=q.get('a'),b=q.get('b'),comp=q.get('competition');
 for(const [date,pin]of [[a,q.get('ap')],[b,q.get('bp')]]){if(!snapshots[date])throw fail('Both dates must be available in this season at or before the dashboard snapshot.',400);if(snapshots[date].meta.projection_sha256!==pin)throw fail('An endpoint revision changed. Reload the date catalogue.');if(!snapshots[date].leagues[comp])throw fail('Choose a league covered on both dates.',400);}
 const before=snapshots[a],after=snapshots[b],left=before.leagues[comp],right=after.leagues[comp];
 const rows=[...new Set([...Object.keys(left),...Object.keys(right)])].sort().map(team=>{const x=left[team]||null,y=right[team]||null,delta={};for(const metric of ['banked','expected_final','expected_remaining','mean_position',...probabilities])delta[metric]=x&&y?difference(x[metric],y[metric]):null;const bridge=pointsBridge(x,y);if(bridge)for(const k of ['banked','expected_final','expected_remaining'])delta[k]=bridge[k];return {team,before:x,after:y,delta,bridge};}).sort((x,y)=>(numeric(y.after?.banked)?y.after.banked:-Infinity)-(numeric(x.after?.banked)?x.after.banked:-Infinity)||x.team.localeCompare(y.team));
 const fixtures=async date=>{let gw;try{gw=await get('/material/gw/'+date);}catch{return null;}const block=gw?.leagues?.[comp];if(!block)return null;const out={};for(const f of block.fixtures||[]){if(!f.result)continue;if(f.result.length!==2||f.result.some(v=>!Number.isInteger(v)||v<0)||f.kickoff.slice(0,10)>snapshots[date].meta.as_of)throw fail('Invalid stored league fixture score/cutoff.');const item={home:f.home,away:f.away,kickoff:f.kickoff,competition:comp,result:f.result,xg:f.xg??null,round:f.round??null},id=key(item);if(out[id])throw fail('Duplicate stored fixture identity.');out[id]=item;}return out;};
 const ga=await fixtures(a),gb=await fixtures(b);let ledger=null;const reconciliation=[];
 const points=(f,team)=>!f||!f.result?0:f.result[0]===f.result[1]?1:(f.result[0]>f.result[1])===(f.home===team)?3:0;
 if(ga&&gb){ledger=[];for(const id of [...new Set([...Object.keys(ga),...Object.keys(gb)])].sort()){const x=ga[id]||null,y=gb[id]||null;if(JSON.stringify(x)===JSON.stringify(y))continue;const f=y||x;const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(id))),v=>v.toString(16).padStart(2,'0')).join('');ledger.push({id:digest.slice(0,24),fixture:id,home:f.home,away:f.away,competition:comp,kickoff:f.kickoff,before:x,after:y,points_delta:Object.fromEntries([f.home,f.away].map(t=>[t,points(y,t)-points(x,t)])),change:!x?'added':!y?'removed':'revised',evidence_date:y?b:a,evidence_revision:y?q.get('bp'):q.get('ap')});}ledger.sort((x,y)=>x.kickoff.localeCompare(y.kickoff)||x.home.localeCompare(y.home)||x.away.localeCompare(y.away)||x.id.localeCompare(y.id));
  for(const row of rows){const counts={};for(const [label,fixtures,source]of [['before',ga,row.before],['after',gb,row.after]]){const played=Object.values(fixtures).filter(f=>[f.home,f.away].includes(row.team)),total=played.reduce((n,f)=>n+points(f,row.team),0);counts[label]={fixtures:played.length,match_points:total,stored_banked:source?.banked??null,points_difference:source?difference(total,source.banked):null,played_difference:source?difference(played.length,source.played):null};}const total=ledger.reduce((n,f)=>n+(f.points_delta[row.team]||0),0),gap=difference(total,row.delta.banked);reconciliation.push({team:row.team,...counts,ledger_points_delta:total,banked_delta:row.delta.banked,delta_gap:gap,valid:['before','after'].every(k=>counts[k].points_difference===0&&counts[k].played_difference===0)&&gap===0});}}
 const [lo,hi]=[a,b].sort(),range=Object.entries(snapshots).filter(([d])=>d>=lo&&d<=hi).map(([,s])=>s);
 return {schema:1,source:anchor.meta,competition:comp,before:before.meta,after:after.meta,rows,timeline:range.map(s=>({meta:s.meta,teams:s.leagues[comp]||{}})),ledger,reconciliation,issues:range.flatMap(s=>s.issues),changes:{model:before.meta.model!==after.meta.model,payload:before.meta.payload!==after.meta.payload,params:[...new Set([...Object.keys(before.meta.params),...Object.keys(after.meta.params)])].sort().filter(k=>JSON.stringify(before.meta.params[k])!==JSON.stringify(after.meta.params[k]))},input_revision:source.projection_sha256,input_files:{},notice:'Coincident forecast changes are not causal match attribution. Fixture changes use the two stored round ledgers.'};
}

async function matchEvidence({day,source,q,get,projection,atlas}){
 const agenda=await get('/api/agenda?date='+day),indices=await get('/material/fact-index/'+day);
 const facts=async f=>indices[key(f)]?get('/material/facts/'+indices[key(f)]):{facts:null};
 const base={schema:agenda.schema,snapshot:day,as_of:agenda.as_of,season:agenda.season,source};
 if(atlas){const team=q.get('team');if(!agenda.fixtures.some(f=>[f.home,f.away].includes(team)))throw fail('Club shot evidence is unavailable.',404);const matches=[];for(const f of agenda.fixtures.filter(f=>[f.home,f.away].includes(team)&&f.result&&f.kickoff.slice(0,10)<=agenda.as_of)){const retained=await facts(f);matches.push({fixture:f,shots:retained.facts?.shots||[],coverage:retained.facts?.coverage||null,evidence:retained.evidence??null,unavailable:retained.unavailable??null});}return {...base,schema:1,normalizer:agenda.schema,team,matches};}
 const fixture=agenda.fixtures.find(f=>key(f)===[q.get('competition'),q.get('home'),q.get('away'),q.get('day')].join('|'));if(!fixture)throw fail('Fixture/snapshot unavailable.',404);
 const [pre_match,forecast_change]=await forecastContext(day,fixture,projection,get);
 const played=Boolean(fixture.result)&&fixture.kickoff.slice(0,10)<=agenda.as_of;
 return {...base,fixture,facts:null,mode:played?'played':'preview',pre_match,forecast_change,...(played?await facts(fixture):{})};
}

async function forecastContext(day,fixture,projection,get){
 const listed=(await get('/material/index')).filter(r=>r.date<=day),matchDay=fixture.kickoff.slice(0,10),played=Boolean(fixture.result);let before=null,after=null;
 const safe=async path=>{try{return await get(path);}catch{return null;}};
 for(const row of [...listed].reverse()){
  const p=await get('/material/projection/'+row.date);if(p.params.season!==projection.params.season||p.as_of>=matchDay||(!played&&row.date!==day))continue;
  const matches=await safe('/material/matches/'+row.date);let found=matches?.fixtures?.find(f=>key(f)===key(fixture)&&f.ladder),keys=found?.stakes_of;
  if(!found||keys==null){const gw=await safe('/material/gw/'+row.date);for(const category of ['leagues','phases']){const block=gw?.[category]?.[fixture.competition]||{},other=block.fixtures?.find(f=>key({...f,competition:fixture.competition})===key(fixture)&&f.ladder);if(other){if(!found)found={...other,competition:fixture.competition};keys=keys?.length?keys:block.stakes_of;break;}}}
  if(found){before={snapshot:row.date,as_of:p.as_of,model:p.model,fixture:found,keys:keys||[],payload:p.version||1,projection:p};break;}
 }
 if(played&&before)for(const row of listed){const p=await get('/material/projection/'+row.date);if(p.params.season===before.projection.params.season&&p.as_of>=matchDay){after={snapshot:row.date,as_of:p.as_of,model:p.model,projection:p};break;}}
 if(before){const p=before.projection,known=before.as_of,context={},ratings=p.ratings||{},factor=ratings.rel?.[fixture.competition]?.now,gw=await safe('/material/gw/'+before.snapshot);let schedule=[];for(const category of ['leagues','phases'])for(const [comp,block]of Object.entries(gw?.[category]||{}))schedule.push(...(block.fixtures||[]).filter(f=>!f.result).map(f=>({...f,competition:comp})));schedule.push(...((await safe('/material/matches/'+before.snapshot))?.fixtures||[]));
  const master=await get('/material/master');const fields=(f,keys)=>Object.fromEntries(keys.map(k=>[k,f[k]??null]));
  for(const team of [fixture.home,fixture.away]){const past=master.filter(r=>Number(r.season)===projection.params.season&&['1','true','yes'].includes(String(r.played).toLowerCase())&&!['1','true','yes'].includes(String(r.tbd).toLowerCase())&&[r.home,r.away].includes(team)&&r.kickoff.slice(0,10)<=known&&r.kickoff.slice(0,10)<matchDay).sort((a,b)=>b.kickoff.localeCompare(a.kickoff)||b.competition.localeCompare(a.competition)||b.home.localeCompare(a.home)||b.away.localeCompare(a.away)),rating=ratings.teams?.find(r=>r.team===team),following=new Map();for(const f of schedule)if([f.home,f.away].includes(team)&&f.kickoff>fixture.kickoff&&!f.result&&(f.p_occurs==null||Number(f.p_occurs)===1))following.set(key(f),f);context[team]={rating:rating?{elo:rating.elo??null,att:factor&&rating.att!=null?rating.att*factor[0]:null,def:factor&&rating.def!=null?rating.def*factor[1]:null}:null,form:past.slice(0,5).map(f=>fields(f,['competition','home','away','kickoff','home_goals','away_goals','home_xg','away_xg','outcome'])),next:[...following.values()].sort((a,b)=>a.kickoff.localeCompare(b.kickoff)||a.competition.localeCompare(b.competition)||a.home.localeCompare(b.home)||a.away.localeCompare(b.away)).slice(0,3).map(f=>fields(f,['competition','home','away','kickoff']))};}before.context=context;
 }
 const rows=[];
 if(before&&after)for(const team of [fixture.home,fixture.away]){const values=p=>[...(p.leagues||[]),...(p.uefa||[]),...(p.cups||[])].find(b=>b.competition===fixture.competition)?.teams?.find(t=>t.team===team)||{},one=values(before.projection),two=values(after.projection);for(const metric of [...probabilities,'p_top8']){const first=one[metric],last=two[metric];if(numeric(first)&&numeric(last)&&first>=0&&first<=1&&last>=0&&last<=1)rows.push({team,metric,before:first,after:last,delta:last-first});}}
 if(before)delete before.projection;if(after)delete after.projection;
 return [before,{before:before?Object.fromEntries(Object.entries(before).filter(([k])=>k!=='fixture')):null,after,rows}];
}
