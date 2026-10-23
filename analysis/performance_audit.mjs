// Independent Python ledger versus every browser selector; no server/browser required.
import {readFileSync} from 'node:fs';
import {stateFor,analysis,chartData,oriented,aggregate,fixtureDay} from '../scripts/webapp/performance-studio.mjs';
const {data,reference}=JSON.parse(readFileSync(process.argv[2],'utf8'));let checks=0;const assert=(ok,message)=>{checks++;if(!ok)throw Error(message);};
const state=stateFor(data,{competition:'all',window:'all',chart:'expectation'});let cells=0;
for(const [team,expected] of Object.entries(reference)){
 const s={...state,clubs:[team],detail:team},actual=analysis(data,s).clubs[0].stats;
 for(const [key,value] of Object.entries(expected)){assert(Math.abs(actual[key]-value)<1e-9,`${team} ${key}: ${actual[key]} != ${value}`);cells++;}
 const chart=chartData(data,s),last=chart.vals.get(team).at(-1);assert(Math.abs(last-expected.residual)<1e-9,team+' final chart total');
}
let populations=0;
for(const chart of ['trajectory','expectation','quality'])for(const venue of ['all','home','away'])for(const window of ['5','10','all']){
 const s=stateFor(data,{clubs:['Arsenal','Man City'],competition:'English Premier League',chart,venue,window,from:'2026-09-01',to:'2026-10-21'}),series=chartData(data,s);
 for(let index=0;index<series.dates.length;index++)for(const team of s.clubs){const date=series.dates[index];let rows=data.fixtures.filter(f=>f.competition===s.competition&&(f.home===team||f.away===team)&&fixtureDay(f)>=s.from&&fixtureDay(f)<=date&&(venue==='all'||(venue==='home'?f.home===team:f.away===team))).sort((a,b)=>a.kickoff.localeCompare(b.kickoff));if(chart!=='expectation'&&window!=='all')rows=rows.slice(-Number(window));
  assert(JSON.stringify(series.windows.get(team)[index])===JSON.stringify(rows.map(r=>r.id)),team+' selected point fixture identities');
  let total=0,shots=0;const known=[];
  for(const f of rows){const side=f.home===team?0:1;if(chart==='expectation'){if(!f.forecast)continue;const gf=f.result[side],ga=f.result[1-side],p=gf>ga?3:gf===ga?1:0;total+=p-3*f.forecast.wdl[side===0?0:2]-f.forecast.wdl[1];}else if(chart==='quality'){total+=f.xg[side];shots+=f.shots[side];}else total+=f.xg[side]-f.xg[1-side];known.push(f);}
  const expected=chart==='expectation'?known.length?total:null:chart==='quality'?shots?total/shots:null:rows.length?total/rows.length:null,actual=series.vals.get(team)[index];assert(expected===null?actual===null:Math.abs(actual-expected)<1e-10,chart+' chart population/denominator');populations++;
 }
}
const f=data.fixtures.find(f=>f.forecast&&f.home==='Arsenal'),away=oriented(f,f.away),wdl=f.forecast.wdl;assert(away.expected===3*wdl[2]+wdl[1],'away orientation');assert(Math.abs(away.expected-(3*wdl[0]+wdl[1]))>1e-4,'deliberate home/away fault must disagree');
const unknown=structuredClone(f);unknown.xg[0]=null;unknown.forecast=null;const r=aggregate([oriented(unknown,unknown.home)]);assert(r.xgf===null&&r.xga===null&&r.residual===null&&r.forecast_n===0,'unknown values never zero-imputed');
const zeroShots=structuredClone(f);zeroShots.shots[0]=0;const z=aggregate([oriented(zeroShots,zeroShots.home)]);assert(z.quality===null&&z.invalid_quality,'positive xG/zero-attempt inconsistency visible');
assert(analysis(data,{...state,clubs:['Arsenal'],from:'2026-10-22',to:'2026-09-01'}).error,'reversed calendar dates reject');
assert(analysis(data,{...state,clubs:['Arsenal'],competition:'Italian Serie A'}).error,'unsupported shared competition refuses');
// Missing fixtures must remain within a last-N actual match window, not be replaced by older covered games.
const partial=structuredClone(data),clubRows=partial.fixtures.filter(f=>f.home==='Arsenal'||f.away==='Arsenal');clubRows.at(-2).xg[0]=null;
const pstate=stateFor(partial,{clubs:['Arsenal'],window:'5',chart:'trajectory'}),p=analysis(partial,pstate).clubs[0];assert(p.rows.length===5&&p.stats.xg_n===4&&p.stats.xgd===null,'rolling missing coverage does not reach back to substitute a match');
const s=stateFor(data,{clubs:['Arsenal'],window:'all',chart:'expectation'}),rows=analysis(data,s).clubs[0].rows,expected=rows.filter(r=>r.expected!==null),correct=aggregate(rows);assert(Math.abs(correct.residual-(correct.covered_points-correct.expected))<1e-10,'covered residual accounting');
assert(rows.length===expected.length||Math.abs(correct.points-correct.expected-correct.residual)>1e-6,'wrong all-match point normalizer must disagree when uncovered results exist');
console.log(JSON.stringify({checks,reference_cells:cells,point_populations:populations,fixtures:data.fixtures.length,clubs:Object.keys(reference).length,faults:'away orientation, missing xG, missing forecast, zero shots and wrong points population'},null,2));

// Independent all-competition source reference: every fixture field and every exact scope.
const source=JSON.parse(readFileSync(process.argv[2],'utf8'));
if(source.all_data){
 const expanded=source.all_data,raw=source.all_reference;
 assert(expanded.fixtures.length===Object.keys(raw).length&&expanded.fixtures.length>data.fixtures.length,'all-competition population is nonempty and wider than domestic leagues');
 for(const fixture of expanded.fixtures){const expected=raw[fixture.id];for(const key of ['competition','home','away','kickoff','kind','minutes','result','xg','xgot','npxg','shots'])assert(JSON.stringify(fixture[key])===JSON.stringify(expected[key]),'source row '+fixture.id+' '+key);}
 for(const scope of ['all','leagues',...expanded.competitions.map(c=>c.competition)]){
  const expected=Object.entries(raw).filter(([,r])=>scope==='all'||scope==='leagues'&&r.kind==='league'||r.competition===scope);
  const teams=[...new Set(expected.flatMap(([,r])=>[r.home,r.away]))];
  for(const team of teams){const state=stateFor(expanded,{clubs:[team],competition:scope,window:'all',chart:'quality'}),result=analysis(expanded,state);assert(!result.error,'covered actual entrant supported '+scope+' '+team);const ids=expected.filter(([,r])=>r.home===team||r.away===team).map(([id])=>id).sort();assert(JSON.stringify(result.clubs[0].stats.ids.slice().sort())===JSON.stringify(ids),'exact competition population '+scope+' '+team);}
 }
}

// Nonempty synthetic faults isolate missing components from all real-data coincidences.
const comp='English Premier League',uefa='UEFA Champions League',cup='English League Cup';
const sample=(id,competition,kind,home,away,result,xg,shots)=>({id:String(id),competition,kind,home,away,result,xg,shots,kickoff:`2026-08-0${id} 19:00:00`,minutes:kind==='cup'?120:90,outcome:kind==='cup'?'afterextratime':'fulltime',forecast:kind==='league'?{wdl:[.5,.2,.3],timing:'retrospective'}:null});
const synthetic={as_of:'2026-08-06',all_competitions:true,competitions:[{competition:comp,kind:'league',teams:['Alpha','Beta']},{competition:uefa,kind:'uefa',teams:['Alpha','Gamma']},{competition:cup,kind:'cup',teams:['Alpha','Delta']}],fixtures:[
 sample(1,comp,'league','Alpha','Beta',[2,1],[1.2,.6],[12,6]),
 sample(2,uefa,'uefa','Gamma','Alpha',[2,3],[1.5,2],[10,8]),
 sample(3,cup,'cup','Alpha','Delta',[3,0],[null,.3],[10,3]),
 sample(4,comp,'league','Beta','Alpha',[1,2],[1.1,1.4],[11,null]),
 sample(5,uefa,'uefa','Alpha','Gamma',[2,1],[2,.9],[20,9]),
 sample(6,cup,'cup','Delta','Alpha',[1,2],[.5,1.5],[5,15])
]};
let faultChecks=0;
for(const scope of ['all','leagues',comp,uefa,cup])for(const venue of ['all','home','away'])for(const window of ['5','10','all'])for(const side of ['for','against']){
 const state=stateFor(synthetic,{clubs:['Alpha'],competition:scope,venue,window,side,chart:'quality'}),result=analysis(synthetic,state);assert(!result.error,'synthetic supported scope');
 let fixtures=synthetic.fixtures.filter(f=>(scope==='all'||scope==='leagues'&&f.kind==='league'||f.competition===scope)&&(venue==='all'||(venue==='home'?f.home==='Alpha':f.away==='Alpha')));if(window!=='all')fixtures=fixtures.slice(-Number(window));
 const expectedIds=fixtures.map(f=>f.id),known=fixtures.flatMap(f=>{const teamSide=f.home==='Alpha'?0:1,index=side==='against'?1-teamSide:teamSide;return Number.isFinite(f.xg[index])&&Number.isFinite(f.shots[index])?[{id:f.id,xg:f.xg[index],shots:f.shots[index]}]:[];}),stats=result.clubs[0].stats;
 assert(JSON.stringify(stats.ids)===JSON.stringify(expectedIds),'synthetic actual window IDs');assert(JSON.stringify(stats.quality_ids)===JSON.stringify(known.map(f=>f.id)),'synthetic exact xG/attempt intersection');
 const xg=known.reduce((sum,r)=>sum+r.xg,0),shots=known.reduce((sum,r)=>sum+r.shots,0),quality=known.length===fixtures.length&&known.length&&shots>0?xg/shots:null;
 assert(stats.quality_n===known.length&&stats.quality_xg===xg&&stats.quality_shots===shots,'joint fixture numerator and denominator');assert(quality===null?stats.quality===null:Math.abs(stats.quality-quality)<1e-12,'weighted strict quality');
 if(scope===cup||scope===uefa)assert(stats.points===null&&stats.forecast_n===0,'nonleague match points unavailable');faultChecks++;
}
const faultState=stateFor(synthetic,{clubs:['Alpha'],competition:'all',window:'5',chart:'quality'}),fault=analysis(synthetic,faultState).clubs[0];
assert(fault.stats.n===5&&JSON.stringify(fault.stats.ids)===JSON.stringify(['2','3','4','5','6']),'last5 counts actual matches including missing metrics');
const xgKnown=fault.rows.filter(r=>Number.isFinite(r.xgf)),shotsKnown=fault.rows.filter(r=>Number.isFinite(r.shots));assert(xgKnown.length===4&&shotsKnown.length===4&&fault.stats.quality_n===3,'equal component counts do not establish a joint intersection');
const checkQuality=stats=>{if(stats.quality!==null||JSON.stringify(stats.quality_ids)!==JSON.stringify(['2','5','6']))throw Error('Disjoint xG/attempt fixture populations accepted');};checkQuality(fault.stats);
let deliberateFaultRejected=false;try{checkQuality({...fault.stats,quality:xgKnown.reduce((a,r)=>a+r.xgf,0)/shotsKnown.reduce((a,r)=>a+r.shots,0),quality_ids:xgKnown.map(r=>r.fixture.id)});}catch(e){deliberateFaultRejected=e.message.includes('Disjoint');}assert(deliberateFaultRejected,'deliberate equal-size/disjoint population fault must fail');
for(const scope of ['all',uefa,cup])assert(analysis(synthetic,stateFor(synthetic,{clubs:['Alpha'],competition:scope,chart:'expectation'})).error,'unsupported expectation scope refuses instead of substituting domestic');
const leaguePoints=chartData(synthetic,stateFor(synthetic,{clubs:['Alpha'],competition:'leagues',chart:'trajectory',metric:'points',window:'all'}));assert(leaguePoints.vals.get('Alpha').at(-1)===3,'league points metric');
const cupPoints=chartData(synthetic,stateFor(synthetic,{clubs:['Alpha'],competition:cup,chart:'trajectory',metric:'points',window:'all'}));assert(cupPoints.vals.get('Alpha').every(v=>v===null),'cup points never silently become league wins');
const falseForecast=structuredClone(synthetic.fixtures[2]);falseForecast.forecast={wdl:[.7,.2,.1],timing:'retrospective'};assert(oriented(falseForecast,'Alpha').expected===null,'cup forecast cannot acquire league points');
const awayQuality=aggregate(synthetic.fixtures.slice(0,2).map(f=>oriented(f,'Alpha')),'against');assert(Math.abs(awayQuality.quality-(.6+1.5)/(6+10))<1e-12,'Against quality uses opponents exact xG and attempts');
console.log(JSON.stringify({checks,synthetic_scope_populations:faultChecks,deliberate_disjoint_fault_rejected:deliberateFaultRejected,all_fixture_count:source.all_data?.fixtures.length},null,2));
