"""Atlas exact source accounting and independently detected faults; no source writes."""
import copy
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from analysis.atlas_audit import audit,verify,ROOT
from scripts.dashboard_store import Snapshots
from scripts.match_centre import MatchCentre


def run():
    result,payloads,rows=audit();assert not result['errors'],result['errors'][:5]
    assert result['counts']['teams']==6 and result['counts']['matches']>0 and result['counts']['shots']>0
    print('Atlas source reconciliation:',json.dumps(result,sort_keys=True))
    cache=ROOT/'data/fotmob/matches'
    for fault in ['future','coordinate','xg']:
        bad=copy.deepcopy(payloads[0])
        if fault=='future':
            item=copy.deepcopy(bad['matches'][0]);item['fixture']['id']='injected-future';item['fixture']['kickoff']='2099-01-01 12:00:00';bad['matches'].append(item)
        else:
            shot=next(s for m in bad['matches'] for s in m['shots'])
            shot['x' if fault=='coordinate' else 'xg']+=1
        _,errors=verify(bad,rows,cache);assert errors,'fault escaped: '+fault
        print('caught deliberate Atlas',fault,':',len(errors),'source failures')
    centre=MatchCentre(Snapshots())
    assert centre.atlas('1900-01-01','Arsenal') is None
    assert centre.atlas('2026-10-22','unknown-club') is None
    old=centre.atlas('2026-08-22','Arsenal');assert old is not None and all(m['fixture']['kickoff'][:10]<=old['as_of'] for m in old['matches'])
    print('Atlas guards:3 unknown-snapshot/unknown-club/older-cutoff cases pass; exact membership stays cutoff-safe')
    print('Atlas checks passed')


if __name__=='__main__':run()
