"""Independent exact-row/DC reference for competition charts; no provider or model fit."""
from __future__ import annotations
import argparse,csv,json,sys
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))


def reference(output,date='2026-10-22'):
    from scripts.dashboard_store import Snapshots
    from scripts.performance_studio import PerformanceStudio
    from scripts.backtest_qt import outcome_probs,MAXG
    from scripts.simulate_season import MATCH_DRAW
    snaps=Snapshots();selected=snaps.load(date)
    data=PerformanceStudio(snaps).read(date,selected['source']['projection_sha256'],all_competitions=True)
    assert data['fixtures'],'Real fixture evidence must be nonempty'
    with snaps.master_csv.open() as source:
        raw={(r['competition'],r['home'],r['away'],r['kickoff'][:10]):r for r in csv.DictReader(source) if int(r['season'])==data['season'] and r['played']=='True'}
    references=[]
    for f in data['fixtures']:
        r=raw[(f['competition'],f['home'],f['away'],f['kickoff'][:10])]
        for field in ('xg','xgot','npxg','shots'):
            values=[float(r.get(s+'_'+field)) if r.get(s+'_'+field) else None for s in ('home','away')]
            assert f[field]==values,(f['id'],field)
        x=[r.get(s+'_xg') or r.get(s+'_npxg') for s in ('home','away')]
        chance=None
        if f['kind'] in ('league','uefa') and all(v not in ('',None) for v in x):
            p=outcome_probs(np.array([max(.01,float(x[0]))]),np.array([max(.01,float(x[1]))]),MATCH_DRAW[f['kind']][2])[0]
            chance=[float(3*p[0]+p[1]),float(3*p[2]+p[1])]
        references.append({'id':f['id'],'chance':chance})
    Path(output).write_text(json.dumps({'data':data,'reference':references,'method':{'maxGoals':MAXG,'rho':{k:MATCH_DRAW[k][2] for k in ('league','uefa')}}}))
    return {'fixtures':len(data['fixtures']),'competitions':len(data['competitions']),'cutoff':data['as_of'],'output':str(output)}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--date',default='2026-10-22');args=parser.parse_args()
    target=Path(args.output)
    assert not target.exists(),'Choose a new review artifact path'
    assert not target.resolve().is_relative_to(ROOT/'data'),'Review artifacts never enter production data'
    print(json.dumps(reference(target,args.date),indent=2))
