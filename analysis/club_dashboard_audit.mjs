// Optional Node audit of the club UI selectors; reads source files, never writes or loads a model.
import {readFileSync} from 'node:fs';
import {gunzipSync} from 'node:zlib';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import * as W from '../scripts/webapp/workspace.mjs';
const root=fileURLToPath(new URL('../',import.meta.url)),index=JSON.parse(readFileSync(root+'data/snapshots/index.json','utf8')),day=process.argv[2]||index.at(-1).date,base=root+'data/snapshots/'+day+'/';
const load=name=>JSON.parse(readFileSync(base+name,'utf8')),result=load('projection.json'),matches=load('matches.json'),gw=JSON.parse(gunzipSync(readFileSync(base+'gw.json.gz'))),players=JSON.parse(gunzipSync(readFileSync(base+'players.json.gz')));
const source=spawnSync(root+'.venv/bin/python',['-c',`import csv,json,sys
rows=[]
with open(sys.argv[1],newline='') as f:
 for r in csv.DictReader(f):
  if int(r['season'])!=int(sys.argv[2]) or r['played'].lower()!='true' or r['tbd'].lower()=='true' or r['kickoff'][:10]>sys.argv[3]:continue
  rows.append({**{k:r[k] for k in ['competition','home','away','kickoff','outcome']},'minutes':float(r['minutes']) if r.get('minutes') else None,'result':[int(float(r[s+'_goals'])) for s in ['home','away']],'xg':[float(r[s+'_xg']) if r.get(s+'_xg') else None for s in ['home','away']]})
print(json.dumps(rows))`,root+'data/master_fixtures.csv',String(result.params.season),result.as_of],{encoding:'utf8'});
if(source.status!==0)throw Error(source.stderr);
const truth=JSON.parse(source.stdout),pool=W.clubFixturePool(result,gw,{fixtures:[...matches.fixtures,...truth]}),errors=[],counts={};
const identity=f=>[f.competition,f.home,f.away,f.kickoff.slice(0,10)].join('|'),expected=new Set(truth.map(identity)),actual=new Set(pool.fixtures.filter(f=>f.result).map(identity));
if(!expected.size||expected.size!==actual.size||[...expected].some(id=>!actual.has(id)))errors.push('played fixture IDs differ');counts.played_matches=expected.size;
let scalarValues=0;
for(const b of [...result.leagues,...result.uefa])for(const t of b.teams){const p=W.clubPerformance(result,pool,t.team,{competition:b.competition});for(const key of ['pl','gf','ga']){scalarValues++;if(p[key]!==t.real[key])errors.push(t.team+'/'+b.competition+'/'+key);}}
counts.competition_values=scalarValues;
let sides=0;
for(const team of new Set(truth.flatMap(f=>[f.home,f.away]))){const rows=truth.filter(f=>f.home===team||f.away===team),p=W.clubPerformance(result,pool,team),gf=rows.reduce((a,f)=>a+f.result[f.home===team?0:1],0),ga=rows.reduce((a,f)=>a+f.result[f.home===team?1:0],0);sides+=rows.length;if(p.pl!==rows.length||p.gf!==gf||p.ga!==ga)errors.push(team+'/all competition sum');}
counts.side_appearances=sides;
let playerValues=0;
for(const team of result.leagues.flatMap(b=>b.teams.map(t=>t.team))){const actual=W.clubPlayerContributions(result,players,team),expected=new Map();for(const [comp,b] of Object.entries(players.competitions))for(const p of b.players){const part=p.by_team?.[team];if(part){const key=String(p.id),row=expected.get(key)||[];row.push(part);expected.set(key,row);}}
 if(actual.rows.length!==expected.size)errors.push(team+'/squad identities');for(const p of actual.rows)for(const key of ['matches','minutes','goals','xg','assists','shots']){const sources=expected.get(p.id),want=sources.every(s=>Number.isFinite(s[key]))?sources.reduce((sum,s)=>sum+s[key],0):null;playerValues++;if(p[key]!==want)errors.push(team+'/'+p.id+'/'+key);}}
counts.player_values=playerValues;
const anchor=result.leagues[0].teams[0].team,league=result.leagues[0].competition,peers=W.clubPeers(result,pool,anchor,{competition:league});
if(!peers.rows.length)errors.push('empty peers');for(const row of peers.rows){const want=Math.sqrt(peers.used.reduce((a,i)=>a+((row.values[i]-peers.target.values[i])/peers.sd[i])**2,0)/peers.used.length);if(Math.abs(row.distance-want)>1e-12)errors.push('peer distance '+row.team);}
counts.peer_rows=peers.rows.length;
const cup=pool.fixtures.find(f=>f.result&&result.cups.some(b=>b.competition===f.competition)),good=W.clubPerformance(result,pool,cup.home),bad=W.clubPerformance(result,{...pool,fixtures:[...pool.fixtures,cup]},cup.home),local=W.clubStrength(result,anchor,league),global=W.clubStrength(result,anchor);
counts.deliberate_faults_caught=Number(good.pl!==bad.pl)+Number(Math.abs(local.att-global.att)>1e-12);if(counts.deliberate_faults_caught!==2)errors.push('empty or uncaught fault');
const times=[];for(let i=0;i<20;i++){const start=performance.now();W.clubPeers(result,pool,anchor,{competition:'all'});times.push(performance.now()-start);}
console.log(JSON.stringify({date:day,cutoff:result.as_of,counts,peer_milliseconds:{runs:times.length,mean:times.reduce((a,b)=>a+b,0)/times.length,max:Math.max(...times)},errors},null,2));if(errors.length)process.exitCode=1;
