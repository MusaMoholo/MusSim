"""Read-only4-world preseason projection/bundle checks; writes only /private/tmp review artifacts."""
import sys,json,time,hashlib,tempfile
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from scripts.projection import Engine,coerce_params,run_projection,run_projection_parallel
from scripts.player_stats import build_players
from scripts.nightly import write_gw_snapshot,write_players_snapshot,_write_compressed_json,validate_snapshot_bundle

def main():
 engine=Engine();summaries=[];review=Path(tempfile.mkdtemp(prefix='football-august-check-'))
 for day in ['2026-08-01','2026-08-05','2026-08-06','2026-08-22']:
  params=coerce_params({'season':2026,'worlds':4,'seed':1,'replay_played':True,'as_of':day},2026)
  start=time.perf_counter();p=run_projection(engine,params)
  assert p['as_of']<=day and p['fitted_through']<=day,(day,p['as_of'],p['fitted_through'])
  folder=review/day;folder.mkdir()
  m=p.pop('matches');g=p.pop('gw');paths=p.pop('paths');p['snapshot']=day;p['generated']='2026-10-23T00:00:00+00:00'
  (folder/'projection.json').write_text(json.dumps(p,allow_nan=False));(folder/'matches.json').write_text(json.dumps(m,allow_nan=False));write_gw_snapshot(folder,g);_write_compressed_json(folder,'paths',paths)
  players=build_players(engine.master,2026,p['as_of'],Path('data/fotmob/players'));write_players_snapshot(folder,players);validate_snapshot_bundle(folder)
  assert players['as_of']==p['as_of'];assert p['params']['as_of']==day
  if day<'2026-08-06':
   assert p['as_of']==day and not players['competitions']
   assert not any(f.get('result') for f in m['fixtures'])
  if day in ['2026-08-01','2026-08-22']:
   b=run_projection_parallel(params,4,engine=engine)
   for key in ['elapsed','processes','generated','snapshot','match_fixtures']:
    p.pop(key,None);b.pop(key,None)
   assert b.pop('matches')==m,'Serial/four-process match sidecars differ'
   assert b.pop('gw')==g,'Serial/four-process gameweek sidecars differ'
   assert b.pop('paths')==paths,'Serial/four-process path sidecars differ'
   assert p==b,'Serial/four-process projections differ'
  summaries.append({'date':day,'as_of':p['as_of'],'fitted_through':p['fitted_through'],'fixtures':len(m['fixtures']),'seconds':round(time.perf_counter()-start,3),'stage':str(folder)})
 print(json.dumps(summaries,indent=2))
if __name__=='__main__':main()
