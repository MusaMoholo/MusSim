// Independent fixture accounting and deliberate population/method faults.
import {readFileSync} from 'node:fs';
import {POINTS_METHOD,stateFor,formSeries,goalsStats,chancePoints,pointsStats,pointsEligible,competitionAnalysis} from '../scripts/webapp/competition-evidence.mjs';
import {oriented,fixtureDay} from '../scripts/webapp/performance-studio.mjs';
let checks=0;const assert=(ok,message)=>{checks++;if(!ok)throw Error(message);},near=(a,b,message)=>assert(Math.abs(a-b)<1e-10,message+`: ${a} != ${b}`);
const comp='English Premier League',teams=['Alpha','Beta'];
const fixture=(id,day,xg,shots=[10,5],extras={})=>({id,competition:comp,kind:'league',round:Number(id),kickoff:`2026-09-${day} 15:00:00`,home:'Alpha',away:'Beta',result:[2,1],xg,xgot:xg.map(v=>v===null?null:v+.1),npxg:[...xg],shots,minutes:90,outcome:'fulltime',...extras});
const fixtures=[fixture('1','01',[1,.5]),fixture('2','02',[1.2,.6]),fixture('3','03',[1.4,.7]),fixture('4','04',[1.6,.8]),fixture('5','05',[1.8,.9]),fixture('6','06',[2,1])];
const data={as_of:'2026-09-06',competitions:[{competition:comp,kind:'league',teams}],fixtures};
const base=stateFor(data,{window:'5'},'quality',comp),result=competitionAnalysis(data,base);
const alpha=result.clubs[0];near(alpha.x,10,'same-match attempt volume');near(alpha.y,(1.2+1.4+1.6+1.8+2)/50,'weighted quality');
assert(JSON.stringify(alpha.covered_ids)===JSON.stringify(fixtures.slice(1).map(f=>f.id)),'exact joint quality IDs');
const away=competitionAnalysis(data,{...base,side:'against'}).clubs[0];near(away.x,5,'against attempt orientation');near(away.y,(.6+.7+.8+.9+1)/25,'against quality orientation');
const missing=structuredClone(data);missing.fixtures[4].xg[0]=null;missing.fixtures[5].shots[0]=null;
const incomplete=competitionAnalysis(missing,{...base,window:'all'}).clubs[0];assert(incomplete.coverage===4&&incomplete.x===null&&incomplete.y===null,'disjoint missing sets do not establish matched coverage');
const wrongIndependentRatio=(1+1.2+1.4+1.6+2)/5/(50/5);assert(wrongIndependentRatio!==null&&incomplete.y===null,'deliberate independently-normalized denominator rejected');
const missingForm=structuredClone(data);missingForm.fixtures[4].xg[0]=null;
const form=formSeries(missingForm,{teams,competition:comp,metric:'nd',window:'5'});
assert(JSON.stringify(form.windows.get('Alpha').at(-1))===JSON.stringify(['2','3','4','5','6']),'last5 actual fixtures retain unknown component');
assert(form.vals.get('Alpha').at(-1)===null,'incomplete last5 form withheld');
const wrongCovered=missingForm.fixtures.filter(f=>f.xg.every(Number.isFinite)).slice(-5).map(f=>f.id);assert(JSON.stringify(wrongCovered)!==JSON.stringify(form.windows.get('Alpha').at(-1)),'deliberate reachback fault fails selected IDs');
let caughtFault='';try{assert(JSON.stringify(wrongCovered)===JSON.stringify(form.windows.get('Alpha').at(-1)),'Injected older-covered-match substitution must fail the actual-match identity check');}catch(error){caughtFault=error.message;}
assert(caughtFault.includes('Injected older-covered-match'),'deliberate population fault actually triggered acceptance failure');
const postponed=structuredClone(data);postponed.fixtures[0].round=9;postponed.fixtures[5].round=1;
assert(JSON.stringify(formSeries(postponed,{teams,competition:comp,metric:'pp',window:'5'}).windows.get('Alpha').at(-1))===JSON.stringify(['2','3','4','5','6']),'kickoff chronology beats original rounds');
near(formSeries(data,{teams,competition:comp,metric:'pp',window:'5'}).vals.get('Alpha').at(-1),3,'points metric keeps actual full window');
for(const side of ['for','against'])for(const measure of ['xg','xgot']){
 const s=goalsStats(fixtures.map(f=>oriented(f,'Alpha')),{side,measure});assert(s.complete&&s.known===6,'complete goals metric fixture identity');
 near(s.goals,side==='for'?12:6,'official goals exact population');near(s.value,fixtures.reduce((n,f)=>n+f[measure][side==='for'?0:1],0),'selected metric exact population');
}
const different=structuredClone(data);different.fixtures[0].xg[0]=null;different.fixtures[1].xgot[0]=null;
const gx=goalsStats(different.fixtures.map(f=>oriented(f,'Alpha')),{measure:'xgot'});assert(gx.goals===null&&gx.covered_ids.includes('1')&&!gx.covered_ids.includes('2'),'equal xG/xGOT counts do not establish same population');
const z=structuredClone(data);z.fixtures[2].shots[0]=0;assert(competitionAnalysis(z,base).clubs[0].invalid&&competitionAnalysis(z,base).clubs[0].y===null,'zero-attempt positive-xG fault visible');
const uefa='UEFA Champions League',udata={...data,competitions:[{competition:uefa,kind:'uefa',teams}],fixtures:fixtures.map(f=>({...f,kind:'uefa',competition:uefa}))};
udata.fixtures.push({...udata.fixtures[0],id:'knockout',round:null,kickoff:'2026-09-06 20:00:00'});
const uf=formSeries(udata,{teams,competition:uefa,metric:'points',window:'5'});assert(!uf.windows.get('Alpha').at(-1).includes('knockout'),'UEFA form preserves phase population');near(uf.vals.get('Alpha').at(-1),3,'explicit UEFA phase points');
assert(!pointsEligible({...fixtures[0],minutes:120})&&!pointsEligible({...fixtures[0],round:null})&&!pointsEligible({...fixtures[0],kind:'cup'}),'ET/unclassified/cup points refused');
const c=chancePoints(fixtures[0]);near(c.wdl.reduce((n,v)=>n+v,0),1,'outcome probability accounting');
const pr=pointsStats(fixtures.map(f=>oriented(f,'Alpha')));near(pr.gap,pr.points-pr.expected,'covered points residual accounting');
const fallback=structuredClone(fixtures[0]);fallback.xg[0]=null;assert(chancePoints(fallback).npxg_fallback,'existing npxG fallback explicitly retained');
let realFixtures=0,realPopulations=0;
if(process.argv[2]){
 const {data:real,reference,method}=JSON.parse(readFileSync(process.argv[2],'utf8'));assert(reference.length>0,'independent real reference nonempty');
 assert(POINTS_METHOD.maxGoals===method.maxGoals&&JSON.stringify(POINTS_METHOD.rho)===JSON.stringify(method.rho),'method constants equal production reference');
 const byId=new Map(reference.map(r=>[r.id,r]));
 for(const f of real.fixtures){const expected=byId.get(f.id).chance;if(expected){const actual=chancePoints(f);near(actual.values[0],expected[0],'home exact legacy DC xG points');near(actual.values[1],expected[1],'away exact legacy DC xG points');realFixtures++;}}
 for(const block of real.competitions)for(const side of ['for','against'])for(const window of ['all','5']){
  const s=stateFor(real,{side,window},'quality',block.competition),selected=competitionAnalysis(real,s);
  for(const c of selected.clubs){let rows=real.fixtures.filter(f=>f.competition===block.competition&&(f.home===c.team||f.away===c.team)&&fixtureDay(f)<=real.as_of).sort((a,b)=>a.kickoff.localeCompare(b.kickoff)||a.id.localeCompare(b.id));if(window==='5')rows=rows.slice(-5);
   assert(JSON.stringify(c.ids)===JSON.stringify(rows.map(f=>f.id)),'real actual fixture window identity');
   const joint=rows.filter(f=>{const i=(f.home===c.team)===(side==='for')?0:1;return Number.isFinite(f.xg[i])&&Number.isFinite(f.shots[i]);});
   assert(c.coverage===joint.length,'real joint coverage count');
   const shots=joint.reduce((n,f)=>n+f.shots[(f.home===c.team)===(side==='for')?0:1],0),xg=joint.reduce((n,f)=>n+f.xg[(f.home===c.team)===(side==='for')?0:1],0);
   if(rows.length&&joint.length===rows.length&&shots>0&&!joint.some(f=>{const i=(f.home===c.team)===(side==='for')?0:1;return f.shots[i]===0&&f.xg[i]>0;})){near(c.x,shots/rows.length,'real matched volume denominator');near(c.y,xg/shots,'real weighted quality denominator');}else assert(c.y===null,'real incomplete quality unavailable');
   realPopulations++;
  }
 }
}
console.log(JSON.stringify({checks,syntheticFixtures:fixtures.length,realPointFixtures:realFixtures,realClubPopulations:realPopulations,injectedFaultRejected:caughtFault,faults:'missing last-N xG; disjoint shot/xG; equal-count xG/xGOT; round reorder; zero attempts; future/no-phase points; independent wrong denominator'},null,2));
