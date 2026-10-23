#!/usr/bin/env python3
"""Cache-only, read-only accounting for normalized Match Centre evidence; no network/model."""
import csv
import gzip
import json
import sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.match_centre import normalise


def audit(master=None,cache=None):
    rows=list(csv.DictReader(open(master or ROOT/'data/master_fixtures.csv')));cache=Path(cache or ROOT/'data/fotmob/matches')
    counts=Counter();problems=[];examples={}
    for row in rows:
        if row['season']!='2026' or row['played'].lower()!='true' or row['tbd'].lower()=='true':continue
        mid=str(int(float(row['match_id'])));path=cache/(mid+'.json.gz')
        if not path.exists():counts['missing_cache']+=1;continue
        raw=json.loads(gzip.decompress(path.read_bytes()));fixture={**row,'result':[int(float(row[s+'_goals'])) for s in ['home','away']]}
        result=normalise(fixture,raw);counts['matches']+=1
        shots=(((raw.get('content') or {}).get('shotmap') or {}).get('shots') or [])
        known={str((raw.get('general',{}).get(s+'Team') or {}).get('id')):s for s in ['home','away']}
        eligible={str(s['id']):s for s in shots if s.get('id') is not None and s.get('period')!='PenaltyShootout' and s.get('period') in ['FirstHalf','SecondHalf','FirstHalfExtra','SecondHalfExtra'] and str(s.get('teamId')) in known and isinstance(s.get('min'),(float,int)) and 0<=s['min']<=120}
        normalized={s['id'].removeprefix('shot:'):s for s in result['shots']}
        if set(eligible)!=set(normalized):problems.append(mid+':shot identities')
        for sid,s in eligible.items():
            counts['shots']+=1
            r=normalized[sid]
            if r['minute']!=s['min'] or r['added']!=(s.get('minAdded') or 0) or r['own_goal']!=bool(s.get('isOwnGoal')):problems.append(mid+':clock/own goal '+sid)
        # Exact event membership is checked independently, including its source-stable fallback ID.
        import hashlib
        raw_events = ((((raw.get('content') or {}).get('matchFacts') or {}).get('events') or {}).get('events') or [])
        expected_events = set()
        for e in raw_events:
            if e.get('isPenaltyShootoutEvent') or e.get('type')=='PenaltyShootout' or e.get('period')=='PenaltyShootout':continue
            minute=e.get('time');added=e.get('overloadTime') or 0
            if not isinstance(minute,(int,float)) or int(minute)!=minute or not 0<=minute<=120 or not 0<=added<100:continue
            if e.get('period') and e['period'] not in ['FirstHalf','SecondHalf','FirstHalfExtra','SecondHalfExtra']:continue
            eid=e.get('eventId')
            if eid in (None,'',0):eid=e.get('reactKey') or hashlib.sha256(json.dumps(e,sort_keys=True).encode()).hexdigest()[:24]
            expected_events.add('event:'+str(eid))
        if expected_events!={e['id'] for e in result['events']}:problems.append(mid+':event identities')
        for side in ['home','away']:
            mine=[s for s in eligible.values() if known[str(s['teamId'])]==side and not s.get('isOwnGoal')]
            expected=sum(s['expectedGoals'] for s in mine if isinstance(s.get('expectedGoals'),(float,int)))
            if abs(result['summary'][side]['shot_xg']-expected)>1e-9:problems.append(mid+':shot xG '+side)
            counts['xg_sides']+=1
        coverage=result['coverage']
        for kind in ['event','shot']:
            total=len(result[kind+'s'])+coverage['duplicate_'+kind+'s']+coverage['excluded_shootout_'+kind+'s']+coverage['unusable_'+kind+'s']
            if total!=coverage['raw_'+kind+'s']:problems.append(mid+':'+kind+' accounting')
        raw_stats=(raw.get('content') or {}).get('playerStats') or {}
        for player in result['players']:
            source=raw_stats.get(player['id']) or {};values={}
            for group in source.get('stats') or []:
                entries=group.get('stats') or {}
                for stat in entries.values() if isinstance(entries,dict) else entries:
                    if isinstance(stat,dict):values[stat.get('key')]=(stat.get('stat') or {}).get('value')
            expected=values.get('expected_assists')
            if player.get('xa')!=expected:problems.append(mid+':player xA '+player['id'])
            counts['player_xa_cells']+=1;counts['known_player_xa']+=expected is not None
        raw_by_id={}
        for event in raw_events:
            eid=event.get('eventId')
            if eid in (None,'',0):eid=event.get('reactKey') or hashlib.sha256(json.dumps(event,sort_keys=True).encode()).hexdigest()[:24]
            raw_by_id['event:'+str(eid)]=event
        for event in result['events']:
            source=raw_by_id.get(event['id'],{})
            expected=({'id':str(source['assistPlayerId']),'name':source['assistInput']} if source.get('type')=='Goal' and not source.get('ownGoal') and source.get('assistPlayerId') and source.get('assistInput') else None)
            if event.get('assist')!=expected:problems.append(mid+':goal assist '+event['id'])
            if expected:counts['named_goal_assists']+=1
        counts['events']+=len(result['events']);counts['shootout_shots_excluded']+=coverage['excluded_shootout_shots'];counts['own_goals']+=sum(s['own_goal'] for s in result['shots'])
        counts['goal_score_disagreements']+=coverage['goals_reconcile'] is False
        counts['shot_goal_score_disagreements']+=coverage['shot_goals_reconcile'] is False
        if row['outcome'] in ['penalties','afterextratime']:examples.setdefault(row['outcome'],mid)
    if not counts['matches'] or not counts['shots']:problems.append('empty audit')
    return {'counts':dict(counts),'errors':problems,'examples':examples}


if __name__=='__main__':
    result=audit();print(json.dumps(result,indent=2));raise SystemExit(bool(result['errors']))
