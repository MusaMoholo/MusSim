"""Independent Match Centre accounting and adversarial cutoff checks; standard library only."""
import builtins
import copy
import csv
import gzip
import json
import sys
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_original_import = builtins.__import__
def _read_only_import(name, *args, **kwargs):
    if name.split('.')[0] in {'numpy', 'pandas'} or name.startswith(('scripts.projection', 'scripts.simulate_season', 'scripts.attack_defence_qt')):
        raise AssertionError('Match Centre imported model dependency: ' + name)
    return _original_import(name, *args, **kwargs)
builtins.__import__ = _read_only_import
from scripts.dashboard_store import Snapshots
from scripts.match_centre import MatchCentre, clock, normalise
from analysis.match_centre_audit import audit


def run():
    # Independent complete source accounting, rather than expectations copied from the payload.
    source = audit()
    assert not source['errors'], source['errors'][:10]
    counts = source['counts']
    assert counts['matches'] > 0 and counts['own_goals'] > 0 and counts['shootout_shots_excluded'] > 0 and counts['known_player_xa'] > 0 and counts['named_goal_assists'] > 0
    assert counts['goal_score_disagreements'] == counts['shot_goal_score_disagreements'] == 0
    print('source reconciliation:', json.dumps(counts, sort_keys=True))
    assert clock({'time':45,'overloadTime':10})['order'] < clock({'time':46})['order']
    assert clock({'time':105,'overloadTime':3})['order'] < clock({'time':106})['order']
    assert clock({'time':45,'overloadTime':10})['order'] < clock({'time':45,'type':'Half'})['order']
    assert clock({'time':150}) is None
    raw = json.loads(gzip.decompress((ROOT/'data/fotmob/matches/5840306.json.gz').read_bytes()))
    fixture = {'home':'Cardiff City','away':'Swindon Town','result':[3,2]}
    # Use its independently recorded score, not a synthetic expectation for an actual match.
    rows = list(csv.DictReader((ROOT/'data/master_fixtures.csv').open()))
    row = next(r for r in rows if int(float(r['match_id'])) == 5840306)
    fixture['result'] = [int(float(row[s+'_goals'])) for s in ['home','away']]
    facts = normalise(fixture, raw)
    own = [s for s in facts['shots'] if s['own_goal']]
    assert own and facts['coverage']['goals_reconcile'] and facts['coverage']['shot_goals_reconcile']
    raw_duplicate = copy.deepcopy(raw);shot = raw_duplicate['content']['shotmap']['shots'][0]
    raw_duplicate['content']['shotmap']['shots'].append(copy.deepcopy(shot))
    duplicate = normalise(fixture, raw_duplicate)
    assert duplicate['shots'] == facts['shots'] and duplicate['coverage']['duplicate_shots'] == 1
    raw_missing = copy.deepcopy(raw);raw_missing['content'].pop('shotmap');raw_missing['content'].pop('lineup');raw_missing['content'].pop('playerStats')
    missing = normalise(fixture, raw_missing)
    assert not missing['coverage']['shotmap'] and not missing['coverage']['players'] and missing['shots'] == []
    # Two deliberately wrong normalized results must fail the same independent source-ID audit.
    def damaged(kind):
        def mutate(f, response):
            result = normalise(f, response)
            if kind == 'future':
                result['events'].append({'id':'event:injected-future','type':'Goal','side':'home','order':150000})
            elif kind == 'xa':
                result['players'][0]['xa'] = 999
            elif kind == 'assist':
                goal = next((e for e in result['events'] if e.get('assist')), None)
                if goal:goal['assist'] = {'id':'wrong', 'name':'Wrong assister'}
            else:
                excluded = next((s for s in ((response.get('content') or {}).get('shotmap') or {}).get('shots',[]) if s.get('period')=='PenaltyShootout'),None)
                if excluded:
                    result['shots'].append({**result['shots'][0], 'id':'shot:'+str(excluded['id'])})
            return result
        return mutate
    import analysis.match_centre_audit as audit_module
    original = audit_module.normalise
    for kind in ['future','shootout','xa','assist']:
        try:
            audit_module.normalise = damaged(kind)
            rejected = audit_module.audit()['errors']
            assert rejected, 'fault escaped: '+kind
            print('caught deliberate',kind,'inclusion:',len(rejected),'source/accounting failures')
        finally:
            audit_module.normalise = original
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory);cache = root/'cache';cache.mkdir()
        days=['2026-08-22','2026-08-24'];(root/'index.json').write_text(json.dumps([{'date':d} for d in days]))
        f={'competition':'League','home':'Alpha','away':'Beta','kickoff':'2026-08-23 15:00:00','ladder':{'h1':.5,'d':.3,'a1':.2},'stakes':[]}
        postponed={**f,'home':'Gamma','kickoff':'2026-08-25 15:00:00'}
        for day in days:
            p=root/day;p.mkdir();(p/'projection.json').write_text(json.dumps({'params':{'season':2026},'as_of':day,'leagues':[],'uefa':[]}))
            (p/'matches.json').write_text(json.dumps({'fixtures':[f,postponed]}))
        fields=['season','competition','home','away','kickoff','played','tbd','home_goals','away_goals','match_id','outcome','minutes','kind']
        entries=[{'season':2026,'competition':'League','home':home,'away':'Beta','kickoff':date+' 15:00:00','played':'true','tbd':'false','home_goals':1,'away_goals':0,'match_id':mid,'kind':'league','minutes':90} for home,date,mid in [('Alpha','2026-08-23','1'),('Gamma','2026-08-30','2')]]
        with (root/'master.csv').open('w',newline='') as handle:
            w=csv.DictWriter(handle,fieldnames=fields);w.writeheader();w.writerows(entries)
        detail={'general':{'matchId':'1','matchTimeUTCDate':'2026-08-23T15:00:00Z','finished':True,'homeTeam':{'id':10},'awayTeam':{'id':20}},'content':{'matchFacts':{'events':{'events':[{'eventId':1,'time':10,'type':'Goal','isHome':True}]}},'shotmap':{'shots':[{'id':1,'min':10,'period':'FirstHalf','teamId':10,'eventType':'Goal','expectedGoals':.2,'x':100,'y':30}]}}}
        (cache/'1.json').write_text(json.dumps(detail));store=MatchCentre(Snapshots(root,root/'master.csv'),cache)
        early=store.detail(days[0],'League','Alpha','Beta','2026-08-23')
        late=store.detail(days[1],'League','Alpha','Beta','2026-08-23')
        assert early['facts'] is None and early['mode']=='preview'
        assert late['facts']['coverage']['goals_reconcile'] and len(late['facts']['shots'])==1
        assert late['pre_match']['as_of']<'2026-08-23' and late['forecast_change']['after']['snapshot']==days[1]
        scheduled=store.detail(days[0],'League','Gamma','Beta','2026-08-25')
        assert scheduled['fixture']['kickoff']=='2026-08-25 15:00:00' and scheduled['facts'] is None
        assert store.detail(days[0],'League','Gamma','Beta','2026-08-30') is None
        detail['general']['matchTimeUTCDate']='2026-08-30T15:00:00Z';(cache/'1.json').write_text(json.dumps(detail))
        withheld=store.detail(days[1],'League','Alpha','Beta','2026-08-23')
        assert withheld['facts'] is None and 'withheld' in withheld['unavailable']
        detail['general']['matchTimeUTCDate']='2026-08-23T15:00:00Z';detail['general']['matchId']='2';(cache/'1.json').write_text(json.dumps(detail))
        assert store.detail(days[1],'League','Alpha','Beta','2026-08-23')['facts'] is None
        assert store.agenda('1900-01-01') is None
        assert len({f['id'] for f in store.agenda(days[0])['fixtures']})==2
        print('cutoff guards:2 snapshots,2 fixtures,1 positive completed match; future facts,postponement,future provider time,wrong identity and unknown snapshot rejected')
    print('Match Centre checks passed; model imports blocked')


if __name__=='__main__':
    run()
