// Optional Node source-clock audit. Read-only; Python zoneinfo supplies an independent reference.
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {fixtureInstant,kickoffLabel,FIXTURE_ZONES} from '../scripts/webapp/workspace.mjs';
const root=fileURLToPath(new URL('../',import.meta.url));
const source=spawnSync(root+'.venv/bin/python',['-c',String.raw`
import ast,csv,gzip,json,sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
root=Path(sys.argv[1]);tree=ast.parse((root/'scripts/fetch_fotmob.py').read_text())
layout=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.AnnAssign) and getattr(n.target,'id',None)=='LAYOUT')
rows=[];differences=[]
for r in csv.DictReader(open(root/'data/master_fixtures.csv')):
 if r['season']!='2026':continue
 zone=layout[r['competition']][2];dt=datetime.fromisoformat(r['kickoff']).replace(tzinfo=ZoneInfo(zone));stamp=dt.timestamp()*1000
 row={'competition':r['competition'],'kickoff':r['kickoff'],'instant':stamp,'uk':dt.astimezone(ZoneInfo('Europe/London')).strftime('%H:%M')}
 if r['played'].lower()=='true':
  path=root/'data/fotmob/matches'/(str(int(float(r['match_id'])))+'.json.gz')
  if path.exists():
   raw=json.loads(gzip.decompress(path.read_bytes()));provider=raw.get('general',{}).get('matchTimeUTCDate')
   if provider and datetime.fromisoformat(provider.replace('Z','+00:00')).timestamp()*1000!=stamp:differences.append({'id':r['match_id'],'stored':r['kickoff'],'provider':provider})
 rows.append(row)
print(json.dumps({'zones':{c:v[2] for c,v in layout.items()},'rows':rows,'provider_differences':differences}))
`,root],{encoding:'utf8'});
if(source.status!==0)throw Error(source.stderr);
const evidence=JSON.parse(source.stdout),errors=[];
for(const [comp,zone] of Object.entries(evidence.zones))if(FIXTURE_ZONES[comp]!==zone)errors.push('zone mapping '+comp);
for(const row of evidence.rows)if(fixtureInstant(row.kickoff,row.competition)!==row.instant||!kickoffLabel(row.kickoff,row.competition).includes(row.uk))errors.push('clock '+JSON.stringify(row));
if(!evidence.rows.length)errors.push('empty audit');
const barca=kickoffLabel('2026-10-20 21:00:00','UEFA Champions League');if(!barca.includes('20:00'))errors.push('PSG–Barcelona');
// A naive UTC interpretation must fail the independent instant for this actual match.
const faultCaught=fixtureInstant('2026-10-20 21:00:00','UEFA Champions League')!==Date.parse('2026-10-20T21:00:00Z');if(!faultCaught)errors.push('fault escaped');
console.log(JSON.stringify({fixtures:evidence.rows.length,zones:Object.keys(evidence.zones).length,psg_barcelona_uk:barca,provider_disagreements:evidence.provider_differences,deliberate_naive_utc_fault_rejected:faultCaught,errors},null,2));
process.exitCode=errors.length?1:0;
