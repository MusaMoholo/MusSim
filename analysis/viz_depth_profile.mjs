// Read-only cost profile of the added selectors, using frozen files and a review-server ledger.
import {readFileSync} from 'node:fs';
import {performance} from 'node:perf_hooks';
import {toughestStretch,pointsTarget,quantile} from '../scripts/webapp/workspace.mjs';
import {formReferences,stateFor} from '../scripts/webapp/competition-evidence.mjs';
const [folder='/private/tmp/football-chart-guides-render',app='http://127.0.0.1:8768',day='2026-10-22']=process.argv.slice(2);
const projection=JSON.parse(readFileSync(folder+'/projection.json')),gw=JSON.parse(readFileSync(folder+'/gw.json'));
const current=await(await fetch(app+'/api/snapshot?date='+day)).json();
const response=await fetch(app+'/api/performance?'+new URLSearchParams({date:day,pr:current.source.projection_sha256,scope:'all'}));
if(!response.ok)throw Error(await response.text());const data=await response.json(),competition=projection.leagues[0].competition;
const state=stateFor(data,{competition,metric:'xgd'},'form',competition);
const populations=[...Object.entries(gw.leagues||{}),...Object.entries(gw.phases||{})];
const measure=fn=>{const start=performance.now();fn();const cold=performance.now()-start,samples=[];for(let i=0;i<30;i++){const start=performance.now();fn();samples.push(performance.now()-start);}return {first_ms:cold,median_ms:quantile(samples,.5),p95_ms:quantile(samples,.95)};};
console.log(JSON.stringify({fixture_count:data.fixtures.length,clubs:populations.reduce((n,[,g])=>n+g.teams.length,0),
 runin_all_clubs:measure(()=>populations.forEach(([comp,g])=>g.teams.forEach(team=>toughestStretch(g.fixtures,team,comp)))),
 form_reference_one_league:measure(()=>formReferences(data,state)),
 point_tails_all_clubs:measure(()=>[...projection.leagues,...projection.uefa].forEach(b=>b.teams.forEach(t=>pointsTarget(t.pts,70)))),
 league_middle_half:measure(()=>projection.leagues.forEach(b=>{const v=projection.ratings.teams.filter(r=>r.league===b.competition).map(r=>r.att-r.def);[.25,.5,.75].forEach(q=>quantile(v,q));}))},null,2));
