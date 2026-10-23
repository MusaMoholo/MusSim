// Optional Node source audit for Task4's first slice. No model imports/network/data writes.
import {readFileSync} from 'node:fs';
import {gunzipSync} from 'node:zlib';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import * as W from '../scripts/webapp/workspace.mjs';
const root=fileURLToPath(new URL('../',import.meta.url)),day=process.argv[2]||'2026-10-22',base=root+'data/snapshots/'+day+'/',result=JSON.parse(readFileSync(base+'projection.json')),players=JSON.parse(gunzipSync(readFileSync(base+'players.json.gz')));
const reference=spawnSync(root+'.venv/bin/python',['-c',String.raw`
import csv,json,sys,math
from pathlib import Path
from collections import defaultdict
root=Path(sys.argv[1]);season=sys.argv[2];cutoff=sys.argv[3];metrics=['minutes','goals','xg','xa','chances_created','assists','shots']
fixtures={}
for r in csv.DictReader(open(root/'data/master_fixtures.csv')):
 if r['season']==season and r['played'].lower()=='true' and r['tbd'].lower()!='true' and r['kickoff'][:10]<=cutoff:fixtures[r['competition'],str(int(float(r['match_id'])))]=r
rows={};duplicates=0
for path in sorted((root/'data/fotmob/players').rglob('*-'+season+'.csv')):
 for row in csv.DictReader(open(path)):
  key=(row['competition'],str(int(float(row['match_id']))));fixture=fixtures.get(key)
  if not fixture or row['side'] not in ['home','away'] or row['season']!=season:continue
  identity=(*key,row['player_id'],row['side'])
  if identity in rows:duplicates+=1;assert rows[identity]==row,'conflicting raw duplicate needs independent adjudication'
  rows[identity]=row
parts=defaultdict(list)
for (comp,mid,pid,side),row in rows.items():parts[pid,comp,fixtures[comp,mid][side]].append(row)
summary=[]
for (pid,comp,team),items in sorted(parts.items()):
 fields={}
 for metric in metrics:
  values=[float(r[metric]) for r in items if r.get(metric) and math.isfinite(float(r[metric]))]
  fields[metric]={'total':round(math.fsum(values),8) if len(values)==len(items) else None,'observed':round(math.fsum(values),8) if values else None,'known':len(values),'appearances':len(items),'unknown':len(items)-len(values)}
 summary.append({'id':'player:fotmob:'+pid,'competition':comp,'team':team,'fields':fields})
print(json.dumps({'appearances':len(rows),'duplicates':duplicates,'parts':summary}))
`,root,String(result.params.season),result.as_of],{encoding:'utf8',maxBuffer:20*1024*1024});
if(reference.status!==0)throw Error(reference.stderr);
const truth=JSON.parse(reference.stdout),index=W.playerEvidenceIndex(result,players),errors=[],near=(a,b)=>a===null||b===null?a===b:Math.abs(a-b)<1e-7;
let fields=0,transfers=0,rates=0,shares=0;
for(const row of truth.parts){const profile=W.playerProfileEvidence(result,players,row.id,{competition:row.competition,team:row.team});if(profile.parts.length!==1)errors.push('stint identity '+row.id+' '+row.team);
 for(const [key,want] of Object.entries(row.fields)){const actual=profile.metrics[key];for(const field of ['total','observed','known','unknown','appearances']){fields++;if(!near(actual[field],want[field]))errors.push(row.id+'/'+key+'/'+field);}}
 for(const key of ['xa','chances_created','assists']){const rate=W.contributionRate(profile.parts,key),expected=row.fields[key].total!=null&&row.fields.minutes.total>0?90*row.fields[key].total/row.fields.minutes.total:null;rates++;if(!near(rate.value,expected))errors.push('matched rate '+row.id+'/'+key);}
}
for(const entity of index.entities){const p=W.playerProfileEvidence(result,players,entity.id);if(p.stints.length!==truth.parts.filter(r=>r.id===entity.id).length)errors.push('identity partition '+entity.id);if(new Set(p.stints.map(r=>r.team)).size>1)transfers++;}
for(const team of index.clubs)for(const metric of ['minutes','goals','xg','xa','chances_created']){const data=W.squadContributionEvidence(result,players,team,{metric}),selected=truth.parts.filter(r=>r.team===team),denominator=selected.reduce((sum,p)=>sum+(p.fields[metric].observed??0),0),known=selected.reduce((sum,p)=>sum+p.fields[metric].known,0);shares++;
 if(!near(data.denominator,known?denominator:null)||known!==data.evidence.known)errors.push('squad denominator '+team+'/'+metric);
 if(denominator>0&&Math.abs(data.rows.reduce((sum,r)=>sum+(r.share??0),0)-1)>1e-10)errors.push('share partition '+team+'/'+metric);
}
const partial=truth.parts.find(p=>p.fields.xa.total===null&&p.fields.xa.observed>0),profile=W.playerProfileEvidence(result,players,partial.id,{competition:partial.competition,team:partial.team}),ev=profile.metrics.xa;
const sameEvidence=(actual,want)=>['total','observed','known','unknown','appearances'].every(key=>near(actual[key],want[key]));
const faults={unknown_xa_as_zero:!sameEvidence({...ev,total:0},partial.fields.xa),partial_xa_per_all_minutes:!near(ev.observed/Math.max(1,profile.metrics.minutes.observed)*90,W.contributionRate(profile.parts,'xa').value)};
const moved=truth.parts.find(p=>truth.parts.some(other=>other.id===p.id&&other.team!==p.team));const filtered=W.playerProfileEvidence(result,players,moved.id,{team:moved.team});const wrongParts=W.playerProfileEvidence(result,players,moved.id).parts;faults.pooled_transfer_fallback=filtered.parts.every(p=>p.team===moved.team)&&!wrongParts.every(p=>p.team===moved.team);
if(!Object.values(faults).every(Boolean))errors.push('fault escaped');if(!truth.appearances||!fields||!transfers)errors.push('empty audit');
const start=performance.now();for(let i=0;i<20;i++)W.creatorDiscovery(result,players);const mean=(performance.now()-start)/20;
console.log(JSON.stringify({appearances:truth.appearances,duplicate_rows:truth.duplicates,identities:index.entities.length,stints:truth.parts.length,source_fields:fields,matched_rates:rates,multi_club_identities:transfers,squad_metric_denominators:shares,deliberate_faults_rejected:faults,warm_creator_ms:mean,errors:errors.slice(0,15),error_count:errors.length},null,2));process.exitCode=errors.length?1:0;
