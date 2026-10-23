// Pure Time Machine selectors versus raw stored projection files; Node is optional.
import {readFileSync} from 'node:fs';
import {stateFor,seriesFor,selectedLedger} from '../scripts/webapp/time-machine.mjs';
const {catalog,data}=JSON.parse(readFileSync(process.argv[2],'utf8')),root=new URL('../data/snapshots/',import.meta.url);let checks=0;
const assert=(ok,label)=>{checks++;if(!ok)throw Error(label);},raw=new Map(data.timeline.map(t=>[t.meta.date,JSON.parse(readFileSync(new URL(t.meta.date+'/projection.json',root),'utf8'))]));
let values=0;
for(const row of data.rows){
 const team=row.team,s=stateFor(catalog,{a:data.before.date,b:data.after.date,competition:data.competition,team,chart:'bridge'}),series=seriesFor(data,s);
 for(const [i,date]of series.dates.entries()){
  const p=raw.get(date),t=p.leagues.find(l=>l.competition===data.competition).teams.find(t=>t.team===team),bank=t.now?.pts??t.real?.pts,final=t.mean_pts;
  for(const [name,expected]of[['Banked',bank],['Expected final',final],['Expected remaining',final-bank]]){assert(Math.abs(series.values.get(name)[i]-expected)<1e-10,team+' '+date+' '+name);values++;}
 }
 for(const fate of ['p_win','p_ucl','p_uel','p_uecl','p_releg']){
  const f=seriesFor(data,{...s,chart:'fates',fate});for(const [i,date]of f.dates.entries()){const t=raw.get(date).leagues.find(l=>l.competition===data.competition).teams.find(t=>t.team===team);assert(Math.abs([...f.values.values()][0][i]-100*t[fate])<1e-10,'raw fate chronology');values++;}
 }
 for(const reference of ['competition','five_leagues'])for(const metric of ['elo','att','def','net']){
  const f=seriesFor(data,{...s,chart:'strength',reference,metric});for(const [i,date]of f.dates.entries()){const p=raw.get(date),r=p.ratings.teams.find(r=>r.team===team),factor=reference==='competition'?p.ratings.rel[data.competition].now:[1,1];const expected=metric==='elo'?r.elo:metric==='att'?r.att*factor[0]:metric==='def'?r.def*factor[1]:r.att*factor[0]-r.def*factor[1];assert(Math.abs([...f.values.values()][0][i]-expected)<1e-10,'stored strength/scales');values++;}
 }
 const ledger=selectedLedger(data,{...s,ledger:'club'});assert(ledger.every(f=>f.home===team||f.away===team),'fixture membership');assert(ledger.reduce((n,f)=>n+f.points_delta[team],0)===row.delta.banked,'fixture/bridge sum');
}
const pinned=stateFor(catalog,{a:data.before.date,b:data.after.date,ap:'stale-a',bp:'stale-b'});assert(pinned.ap==='stale-a'&&pinned.bp==='stale-b','saved stale revisions must not silently upgrade');
const missing=structuredClone(data);missing.timeline[0].teams[data.rows[0].team].p_win=null;const unavailable=seriesFor(missing,{team:data.rows[0].team,chart:'fates',fate:'p_win'});assert([...unavailable.values.values()][0][0]===null,'missing probability must not become zero');
assert(selectedLedger({...data,ledger:null},{ledger:'all'})===null,'missing stored GW must not produce a fabricated empty ledger');
assert(stateFor(catalog,{b:'invalid-date'}).b==='invalid-date','malformed saved date should remain visible for recovery');
const source=readFileSync(new URL('../scripts/webapp/index.html',import.meta.url),'utf8');assert(!source.includes('A season')&&!source.includes('SAMPLE_WORLD')&&!source.includes('sampleSeasonHtml'),'retired sampled-season UI still referenced');
console.log(JSON.stringify({checks,raw_timeline_values:values,clubs:data.rows.length,dates:data.timeline.length,retirement:true},null,2));
