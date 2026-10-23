"""Read-only Atlas membership and geometry audit against master CSV and permanent raw cache."""
import csv
import gzip
import json
import time
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.dashboard_store import Snapshots
from scripts.match_centre import MatchCentre


def verify(payload, rows, cache):
    team=payload['team'];cutoff=payload['as_of'];season=payload['season'];errors=[];counts={'matches':0,'shots':0,'located':0,'unknown_maps':0}
    expected={ '|'.join([r['competition'],r['home'],r['away'],r['kickoff'][:10]]):r for r in rows if str(r['season'])==str(season) and r['played'].lower()=='true' and r['tbd'].lower()!='true' and r['kickoff'][:10]<=cutoff and team in [r['home'],r['away']] }
    actual={m['fixture']['id']:m for m in payload['matches']}
    if len(actual)!=len(payload['matches']) or set(expected)!=set(actual):errors.append('exact cutoff match IDs')
    for fid,m in actual.items():
        if fid not in expected:continue
        counts['matches']+=1;r=expected[fid];mid=str(int(float(r['match_id'])));path=cache/(mid+'.json.gz')
        if not path.exists():path=cache/(mid+'.json')
        if not path.exists():
            if m['shots']:errors.append(fid+': invented uncached shots')
            continue
        body=path.read_bytes();raw=json.loads(gzip.decompress(body) if path.suffix=='.gz' else body)
        shots=((raw.get('content') or {}).get('shotmap') or {}).get('shots') or []
        eligible={str(s['id']):s for s in shots if s.get('id') is not None and s.get('period') in ['FirstHalf','SecondHalf','FirstHalfExtra','SecondHalfExtra'] and isinstance(s.get('min'),(int,float)) and 0<=s['min']<=120}
        norm={s['id'].removeprefix('shot:'):s for s in m['shots']}
        if set(norm)!=set(eligible):errors.append(fid+': source shot IDs')
        if not m['coverage'] or not m['coverage']['shotmap']:counts['unknown_maps']+=1
        for sid,s in norm.items():
            counts['shots']+=1;source=eligible.get(sid,{})
            if s['xg']!=source.get('expectedGoals') or s['x']!=source.get('x') or s['y']!=source.get('y'):errors.append(fid+': source coordinates/xG '+sid)
            if s['x'] is not None:
                counts['located']+=1
                if not 0<=s['x']<=105 or not 0<=68-s['y']<=68:errors.append(fid+': coordinate bounds')
            side='home' if str(source.get('teamId'))==str(raw['general']['homeTeam']['id']) else 'away'
            if s['side']!=side or s['own_goal']!=bool(source.get('isOwnGoal')):errors.append(fid+': side/own goal')
    return counts,errors


def audit(day=None):
    store=Snapshots();day=day or store.list()[-1]['date'];centre=MatchCentre(store);rows=list(csv.DictReader((ROOT/'data/master_fixtures.csv').open()));cache=ROOT/'data/fotmob/matches'
    teams=['Arsenal','Chelsea','Paris Saint-Germain','FC Barcelona','FC Bayern München','Cardiff City']
    totals={'teams':0,'matches':0,'shots':0,'located':0,'unknown_maps':0};errors=[];payloads=[]
    start=time.perf_counter()
    for team in teams:
        data=centre.atlas(day,team)
        if data is None:errors.append('missing club '+team);continue
        payloads.append(data);counts,off=verify(data,rows,cache);errors.extend(off);totals['teams']+=1
        for k,v in counts.items():totals[k]+=v
    elapsed=time.perf_counter()-start
    return {'counts':totals,'errors':errors,'seconds':elapsed},payloads,rows


if __name__=='__main__':
    result,_,_=audit();print(json.dumps(result,indent=2));raise SystemExit(bool(result['errors']) or not result['counts']['shots'])
