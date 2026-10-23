"""Independent retained Track/source scores and adversarial evaluation boundaries; no publication."""
from __future__ import annotations
import argparse,copy,csv,hashlib,json,math,os,sys,tempfile,time
from collections import Counter
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from scripts.dashboard_store import Snapshots
from scripts.forecast_lab import ForecastLab,ForecastError,scores,summary,calibration,outcomes90

def cases():
    with tempfile.TemporaryDirectory(prefix='football-forecast-lab-') as directory:
        root=Path(directory);master=root/'master.csv';comp='English Premier League';fields=['season','competition','kind','home','away','kickoff','played','tbd','outcome','minutes','home_goals','away_goals','round','match_id']
        def row(day,h='Alpha',a='Beta',score=(1,0),season=2026,**kw):return dict(season=season,competition=comp,kind='league',home=h,away=a,kickoff=day+' 15:00:00',played='True',tbd='False',outcome='fulltime',minutes='90',home_goals=score[0],away_goals=score[1],round=1,match_id=day.replace('-',''),**kw)
        rows=[row('2025-09-01',season=2025),row('2025-09-02',score=(0,0),season=2025),row('2025-09-03',score=(0,1),season=2025),row('2026-09-02'),row('2026-09-04',h='Gamma'),row('2026-09-06',h='Delta')]
        def write_rows():
            with master.open('w') as handle:
                writer=csv.DictWriter(handle,fields);writer.writeheader();writer.writerows(rows)
        write_rows();days=['2026-09-01','2026-09-03','2026-09-07'];(root/'index.json').write_text(json.dumps([{'date':d} for d in days]))
        for i,day in enumerate(days):
            folder=root/day;folder.mkdir();p={'params':{'season':2026},'model':'model-a' if i==0 else 'model-b','version':11,'as_of':day,'fitted_through':day,'generated':'2026-09-01T10:00:00+00:00' if i==0 else None if i==1 else '2026-10-01T10:00:00+00:00','cups':[]}
            fixtures=[{k:r[k] for k in ('competition','home','away','kickoff')}|{'ladder':{'h1':.5,'d':.25,'a1':.25}} for r in rows if r['season']==2026]
            (folder/'projection.json').write_text(json.dumps(p));(folder/'matches.json').write_text(json.dumps({'fixtures':fixtures}))
        snaps=Snapshots(root,master);lab=ForecastLab(snaps);pin=snaps.load(days[-1])['source']['projection_sha256'];read=lambda ir='':lab.read(days[-1],pin,ir)
        d=read();assert d['coverage']=={'played':3,'evaluated':3,'excluded':0,'reasons':{},'timings':{'pre_kickoff':1,'unknown':2}}
        assert d['training']['by_kind']['league']['counts']==[1,1,1] and d['cohorts']['pre_kickoff']['n']==1
        assert all(v is None for v in d['cohorts']['pre_kickoff']['weekly_se'].values())
        assert sum(b['n'] for b in calibration(d['fixtures']))==3
        try:lab.read(days[-1],'stale')
        except ForecastError as e:assert e.status==409
        else:raise AssertionError('stale projection accepted')
        path=root/days[1]/'matches.json';raw=json.loads(path.read_text());raw['fixtures'][1]['ladder']['h1']=1.5;old=path.stat();path.write_text(json.dumps(raw));os.utime(path,ns=(old.st_atime_ns,old.st_mtime_ns))
        try:read(d['input_revision'])
        except ForecastError as e:assert e.status==409
        else:raise AssertionError('same-mtime evidence replacement accepted')
        changed=read();assert changed['coverage']['evaluated']==2 and changed['coverage']['reasons']=={'Invalid H/D/A probabilities':1} and not any(r['home']=='Gamma' for r in changed['fixtures'])
        raw['fixtures'][1]['ladder']={'h1':0,'d':.5,'a1':.5};path.write_text(json.dumps(raw));zero=read();target=next(r for r in zero['fixtures'] if r['home']=='Gamma');assert target['scores']['log_loss'] is None and math.isfinite(target['scores']['brier']) and summary(zero['fixtures'])['zero_support']==1
        raw['fixtures'][1]['result']=[1,0];path.write_text(json.dumps(raw));assert read()['coverage']['reasons']=={'Forecast already contains a result':1};del raw['fixtures'][1]['result']
        raw['fixtures'].append(copy.deepcopy(raw['fixtures'][1]));path.write_text(json.dumps(raw))
        try:read()
        except ForecastError as e:assert 'Duplicate retained forecast' in str(e)
        else:raise AssertionError('duplicate forecast accepted')
        raw['fixtures'].pop();raw['fixtures'][1]['ladder']={'h1':.5,'d':.25,'a1':.25};path.write_text(json.dumps(raw))
        source=root/days[1]/'projection.json';p=json.loads(source.read_text());p['fitted_through']='2026-09-05';source.write_text(json.dumps(p));assert read()['coverage']['reasons']=={'Training cutoff not before match day':1}
        raw['fixtures'][1]['score_basis']='tie_winner';path.write_text(json.dumps(raw));assert read()['coverage']['reasons']=={'90-minute forecast basis not established':1};del raw['fixtures'][1]['score_basis'];path.write_text(json.dumps(raw))
        # Equal generation/kickoff instants are retrospective; stored naive league time is BST.
        earlysource=root/days[0]/'projection.json';early=json.loads(earlysource.read_text());early['generated']='2026-09-02T14:00:00Z';earlysource.write_text(json.dumps(early));assert read()['coverage']['timings']['retrospective']==1;early['generated']='2026-09-02T13:59:59Z';earlysource.write_text(json.dumps(early));assert read()['coverage']['timings']['pre_kickoff']==1
        # Changes to an irrelevant score-grid overflow cannot change H/D/A scoring.
        p['fitted_through']=days[1];p['generated']='2026-10-01T10:00:00+00:00';source.write_text(json.dumps(p));before=read();raw['fixtures'][1].update(score_cap=12,score_counts=[[999999]]);path.write_text(json.dumps(raw));assert [f['scores'] for f in before['fixtures']]==[f['scores'] for f in read()['fixtures']]
        assert read()['coverage']['timings']=={'pre_kickoff':1,'retrospective':2}
        earlier=lab.read(days[0],snaps.load(days[0])['source']['projection_sha256']);assert earlier['coverage']['played']==0
        rows.append(copy.deepcopy(rows[-1]));write_rows()
        try:read()
        except ForecastError as e:assert 'Duplicate' in str(e)
        else:raise AssertionError('duplicate result accepted')
        # Return leg ET: aggregate level does NOT imply this match was drawn at90.
        legs=[row('2026-09-01',h='One',a='Two',score=(2,0)),row('2026-09-09',h='Two',a='One',score=(3,0))]
        for r in legs:r.update(competition='UEFA Champions League',kind='uefa',round='')
        legs[1].update(outcome='afterextratime',minutes='120');out=outcomes90(legs);assert out[(2026,'UEFA Champions League','Two','One','2026-09-09')][0]==0
        legs[0]['home_goals']=0;legs[0]['away_goals']=2;assert outcomes90(legs)[(2026,'UEFA Champions League','Two','One','2026-09-09')][0]==2
        # Independent score vector; intentionally reversing H/A must fail this check.
        p=[.6,.3,.1];r=scores(p,2);reference=sum((Decimal(str(v))-int(i==2))**2 for i,v in enumerate(p));assert abs(r['brier']-float(reference))<1e-14 and abs(r['rps']-.585)<1e-14
        fault=scores(list(reversed(p)),2);assert abs(fault['brier']-float(reference))>.01
        # Six equal-sized independent week blocks: closed-form SE of block means.
        toy=[{'week':str(week),'baselines':{'historical':[1/3]*3},'scores':dict.fromkeys(('log_loss','brier','rps'),0),'baseline_scores':{'historical':dict.fromkeys(('log_loss','brier','rps'),week)}} for week in range(6) for _ in range(2)]
        assert abs(summary(toy)['weekly_se']['brier']-math.sqrt(7/12))<1e-14
        assert abs(summary(toy)['weekly_se']['brier']-math.sqrt(7/12)/2)>.1
    return 'timing separation; source/cutoff/fit/stale/duplicate/zero-support/overflow guards; exact90 return-leg recovery; deliberate H/A fault caught'

def real_reference(output=None):
    snaps=Snapshots();p=snaps.load('2026-10-22');lab=ForecastLab(snaps);start=time.perf_counter();data=lab.read('2026-10-22',p['source']['projection_sha256']);cold=time.perf_counter()-start;start=time.perf_counter();assert lab.read('2026-10-22',p['source']['projection_sha256'])==data;warm=time.perf_counter()-start
    import pandas as pd
    from scripts.track_record import build_track
    master=pd.read_csv(ROOT/'data/master_fixtures.csv',parse_dates=['kickoff'])
    track=build_track(master,snaps.root,int(p['params']['season']),as_of=data['as_of'])
    retained=json.loads((snaps.root/'track.json').read_bytes())
    retained_matches_current=retained.get('matches')==track.get('matches')
    expected={(r['competition'],r['home'],r['away'],r['date']):r for r in track['matches'] if r['date']<=data['as_of']};assert len(expected)==len(data['fixtures'])>0
    checks=0;cache={}
    for f in data['fixtures']:
        ref=expected[(f['competition'],f['home'],f['away'],f['kickoff'][:10])];assert f['prob']==ref['prob'] and f['result']==ref['result'] and f['source']['date']==ref['snapshot'];checks+=3
        day=f['source']['date']
        if day not in cache:
            folder=snaps.root/day;projection=json.loads((folder/'projection.json').read_bytes());forecasts=json.loads((folder/'matches.json').read_bytes());cache[day]=(projection,{(r['competition'],r['home'],r['away'],r['kickoff'][:10]):r for r in forecasts['fixtures']})
        projection,forecasts=cache[day];raw=forecasts[(f['competition'],f['home'],f['away'],f['kickoff'][:10])];assert [raw['ladder'][k] for k in ('h1','d','a1')]==f['prob'];assert projection['as_of']<f['kickoff'][:10] and projection['fitted_through']<f['kickoff'][:10]
        pdec=list(map(lambda x:Decimal(str(x)),f['prob']));brier=sum((v-int(i==f['result']))**2 for i,v in enumerate(pdec));rps=((pdec[0]-int(f['result']==0))**2+(pdec[0]+pdec[1]-int(f['result']<=1))**2)/2
        assert abs(f['scores']['brier']-float(brier))<1e-14 and abs(f['scores']['rps']-float(rps))<1e-14 and abs(f['scores']['log_loss']+math.log(f['prob'][f['result']]))<1e-14;checks+=5
    assert {k:v['prob'] for k,v in data['training']['by_kind'].items()}=={k:v['prob'] for k,v in track['base_rates'].items()}
    census=master[(master.season==int(p['params']['season'])) & master.played & ~master.tbd
                  & (master.kickoff.dt.strftime('%Y-%m-%d')<=data['as_of'])]
    assert data['coverage']['played']==data['coverage']['evaluated']+data['coverage']['excluded']==len(census)>0
    for outcome in range(3):
        bins=calibration(data['fixtures'],outcome);assert sum(b['n'] for b in bins)==len(data['fixtures']) and sum(b['successes'] for b in bins)==sum(r['result']==outcome for r in data['fixtures']);checks+=2
    # Independent weighted block-mean variance, from raw Track forecasts/base rates.
    for metric in ('log_loss','brier','rps'):
        blocks={}
        for f in data['fixtures']:
            ref=expected[(f['competition'],f['home'],f['away'],f['kickoff'][:10])];prob=ref['prob'];base=track['base_rates'][ref['kind']]['prob'];result=ref['result']
            def loss(v):
                if metric=='log_loss':return -math.log(v[result])
                if metric=='brier':return sum((v[i]-(i==result))**2 for i in range(3))
                return ((v[0]-(result==0))**2+(sum(v[:2])-(result<=1))**2)/2
            blocks.setdefault(f['week'],[]).append(loss(base)-loss(prob))
        total=sum(map(len,blocks.values()));mean=sum(sum(v) for v in blocks.values())/total;g=len(blocks)
        variance=g/(g-1)*sum((len(v)/total)**2*(sum(v)/len(v)-mean)**2 for v in blocks.values())
        assert abs(mean-data['cohorts']['retrospective']['improvement'][metric])<1e-13 and abs(math.sqrt(variance)-data['cohorts']['retrospective']['weekly_se'][metric])<1e-13;checks+=2
    assert len(data['archive_issues'])==12 and all(i['team']=='Fiorentina' and i['value']>1 for i in data['archive_issues'])
    if output:
        assert not output.exists();output.write_text(json.dumps(data,allow_nan=False))
    return {'retained_track_matches_current':retained_matches_current,'fixtures':len(data['fixtures']),'exclusions':len(data['exclusions']),'independent_checks':checks,'cohorts':data['coverage']['timings'],'cold_seconds':cold,'warm_seconds':warm,'json_bytes':len(json.dumps(data,separators=(',',':')).encode()),'historical_invalid_coppa':len(data['archive_issues']),'scores':data['cohorts']['retrospective']}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);args=parser.parse_args();print('PASS '+cases());print(json.dumps(real_reference(args.output),indent=2))
