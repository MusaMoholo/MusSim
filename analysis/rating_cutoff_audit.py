"""Isolated cutoff and assumed-prior acceptance; never publishes or fetches providers."""
from __future__ import annotations
import copy,json,shutil,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts import projection as p
from scripts.opta_ratings import build, load_snapshots
from scripts.rating_priors import starting_ratings
from scripts.simulate_season import HOME_ADV


def plain(value):
    if isinstance(value,dict):return {str(k):plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [plain(v) for v in value]
    if isinstance(value,np.ndarray):return value.tolist()
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,pd.Timestamp):return str(value)
    return value


def state(prep):
    art=copy.deepcopy(prep['opta'])
    if art:art.pop('built',None)
    value=copy.deepcopy({k:prep[k] for k in ['model','calib','goals','elo0','elo_start','rating_inputs']})
    # The retained file revision changes when later rows change; numeric inputs at this cutoff
    # must stay identical. The manifest correctly records that distinct underlying revision.
    value['rating_inputs'].pop('sources',None)
    return plain(value | {'opta':art})


def verify():
    start=time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='football-cutoff-test-') as temp:
        root=Path(temp);master=root/'master.pkl';elo=root/'elo.csv';opta=root/'opta';opta.mkdir()
        shutil.copy2(p.MASTER,master);shutil.copy2(p.ELO_CSV,elo)
        for source in p.OPTA_DIR.glob('team_rankings-*.csv'):shutil.copy2(source,opta/source.name)
        with patch.object(p,'OPTA_DIR',opta):
            engine=p.Engine(master,elo)
            early=engine.prepare(2026,as_of='2026-08-01');first=engine.prepare(2026,as_of='2026-08-22')
            a,b=state(early),state(first)
            params=p.coerce_params({'season':2026,'worlds':2,'seed':7,'as_of':'2026-08-22'},2026)
            forecast=copy.deepcopy(p.run_projection(engine,params))
            forecast.pop('elapsed');forecast['rating_inputs'].pop('sources')
            quiet=engine.prepare(2026,as_of='2026-08-20')
            assert quiet['cutoff']==pd.Timestamp('2026-08-21')
            assert early['opta'] is None
            assert first['opta']['snapshots']==['2026-08-22'] and first['opta']['beta']==0
            assert not first['opta']['start']
            assumed=early['rating_inputs']['assumed']
            promoted=[v for v in assumed.values() if v['basis']=='assumed league lower quartile']
            assert len(promoted)==6
            for v in promoted:
                league=early['fixtures'][early['fixtures'].competition==v['competition']]
                peers=(set(league.home)|set(league.away))-set(assumed)
                expected=np.percentile([early['elo_start'][t] for t in sorted(peers)],25)
                assert abs(v['elo']-expected)<=.050001
            cup=[v for v in assumed.values() if v['basis']=='assumed historical lower-tier cup entrants']
            assert len(cup)>100 and all(v['matches']>=20 for v in cup)
            assert max(v['elo'] for v in cup)<min(v['elo'] for v in promoted)
            # Reconstruct the English cohort independently and verify the displayed Elo
            # reproduces its pooled result score, including venue and the half-result prior.
            past=engine.master[(engine.master.kickoff<pd.Timestamp('2026-08-02')) & engine.master.played
                               & engine.master.home_goals.notna() & (engine.master.kickoff>=pd.Timestamp('2026-08-02')-pd.Timedelta(days=5*366))]
            top={(int(r.season), t) for r in past[past.kind=='league'].itertuples() for t in (r.home,r.away)}
            values=[]
            for r in past[(past.kind=='cup') & past.competition.str.startswith('English')].itertuples():
                h=(int(r.season),r.home) in top;a_top=(int(r.season),r.away) in top
                if h==a_top:continue
                opp=r.home_elo if h else r.away_elo
                if not np.isfinite(opp):continue
                score=(float(r.away_goals>r.home_goals) if h else float(r.home_goals>r.away_goals))+.5*(r.home_goals==r.away_goals)
                values.append((opp,score,-HOME_ADV if h else HOME_ADV))
            # HOME_ADV belongs to the shared simulator; it is fixed, not refitted here.
            opp,score,ha=np.asarray(values).T
            english=next(v for v in cup if v['population']=='English')
            assert english['matches']==len(values)
            assert abs(np.mean(1/(1+10**(-(english['elo']-opp+ha)/400)))-(sum(score)+.5)/(len(score)+1))<.0001
            assert all(v['evidence_before']<='2026-08-02' for v in assumed.values())
            # Everything later than the two cutoffs is deliberately destroyed. The earlier
            # fitted parameters, calibrations, priors, levels and source dates must stay exact.
            frame=pd.read_pickle(master);future=frame.kickoff>=pd.Timestamp('2026-08-23')
            frame.loc[future,['home_goals','home_npxg','home_elo']]=77.
            frame.loc[future,['away_goals','away_npxg','away_elo']]=.001
            frame.loc[future,'played']=True;frame.to_pickle(master)
            ratings=pd.read_csv(elo);ratings.loc[ratings.date>='2026-08-23','elo']=9999.;ratings.to_csv(elo,index=False)
            for source in opta.glob('team_rankings-*.csv'):
                if source.name>'team_rankings-2026-08-22.csv':source.write_text('deliberately invalid future data')
            assert state(engine.prepare(2026,as_of='2026-08-01'))==a
            assert state(engine.prepare(2026,as_of='2026-08-22'))==b
            again=copy.deepcopy(p.run_projection(engine,params))
            again.pop('elapsed');again['rating_inputs'].pop('sources')
            assert again==forecast, 'Future data changed an earlier forecast or sidecar'
            # Historical chart refits must not reuse the current artifact or baseline priors.
            fit,walk,seed=p.fit_through(engine,first,pd.Timestamp('2026-08-02'))
            assert plain(fit)==a['model'] and walk==early['elo0']
            # Fault injection on an ELIGIBLE source must be detected, and a same-name source
            # replacement must invalidate the cache rather than return its previous good fit.
            eligible=opta/'team_rankings-2026-08-22.csv';eligible.write_text('deliberately invalid eligible data')
            try:engine.prepare(2026,as_of='2026-08-22')
            except ValueError as exc:assert 'invalid Opta snapshot schema' in str(exc)
            else:raise AssertionError('invalid eligible source silently accepted')
            # Deliberate future-rating leak is caught by the same equality assertion.
            broken=copy.deepcopy(a);broken['elo_start'][next(iter(broken['elo_start']))]=9999.
            try:assert broken==a
            except AssertionError:pass
            else:raise AssertionError('future-rating fault escaped')
    return {'checks':'full forecast/sidecar and future results/Elo/Opta invariance; first eligible observation; six promoted priors; cup populations; historical refit equality; source replacement; deliberate leak fault', 'seconds':round(time.perf_counter()-start,3)}

if __name__=='__main__':print(json.dumps(verify(),indent=2))
