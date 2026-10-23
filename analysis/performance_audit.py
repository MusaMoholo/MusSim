"""Independent Performance Studio source ledger, replacement guards and cold/warm cost."""
from __future__ import annotations
import argparse,copy,csv,hashlib,json,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.dashboard_store import Snapshots
from scripts.performance_studio import PerformanceStudio,PerformanceError,generation_timing


def fixtures_case():
    with tempfile.TemporaryDirectory(prefix='football-performance-') as directory:
        root=Path(directory);snaproot=root/'snapshots';snaproot.mkdir();master=root/'master.csv'
        fields=['season','competition','kind','played','tbd','outcome','minutes','home','away','kickoff','home_goals','away_goals','home_xg','away_xg','home_shots','away_shots','match_id']
        comp='English Premier League';rows=[]
        for i,day in enumerate(('01','03','05')):
            rows.append(dict(zip(fields,[2026,comp,'league',True,False,'fulltime',90,'Alpha','Beta','2026-09-'+day+' 15:00:00',2,1,1.5,0.5,10,4,100+i])))
        def write_master():
            with master.open('w') as out:w=csv.DictWriter(out,fieldnames=fields);w.writeheader();w.writerows(rows)
        write_master();index=[]
        for day,cutoff in [('02','01'),('04','03'),('06','05')]:
            date='2026-09-'+day;folder=snaproot/date;folder.mkdir()
            p={'params':{'season':2026},'as_of':'2026-09-'+cutoff,'generated':'2026-10-01T12:00:00+00:00','model':'test','leagues':[{'competition':comp,'teams':[{'team':'Alpha'},{'team':'Beta'}]}]}
            (folder/'projection.json').write_text(json.dumps(p));index.append({'date':date})
            forecasts=[{**r,'ladder':{'h1':.2,'d':.3,'a1':.5}} for r in rows if r['kickoff'][:10]>p['as_of']]
            if day=='04':forecasts[0]['ladder']={'h1':.8,'d':.1,'a1':.1}
            (folder/'matches.json').write_text(json.dumps({'fixtures':forecasts}))
        fields += ['home_xgot','away_xgot','home_npxg','away_npxg','round','round_label','stage','phase']
        rows[1].update(home_xgot=1.2,away_xgot=.4,home_npxg=1.3,away_npxg=.5,round=2,round_label='League phase',stage='retained stage',phase='retained phase')
        # Include knockout entrants omitted from the remaining-forecast teams, and independent metric gaps.
        for comp_name,kind,team,minutes,outcome in [('UEFA Champions League','uefa','Gamma',90,'fulltime'),('English League Cup','cup','Delta',120,'afterextratime')]:
            extra=dict(rows[1],competition=comp_name,kind=kind,away=team,minutes=minutes,outcome=outcome,match_id=200+len(rows))
            rows.append(extra)
        write_master()
        for item in index:
            projection=snaproot/item['date']/'projection.json';p=json.loads(projection.read_text())
            p['uefa']=[{'competition':'UEFA Champions League','teams':[{'team':'Survivor'}]}]
            p['cups']=[{'competition':'English League Cup','teams':[{'team':'Survivor'}]}]
            projection.write_text(json.dumps(p))
        (snaproot/'index.json').write_text(json.dumps(index));snaps=Snapshots(snaproot,master);payload=snaps.load();revision=payload['source']['projection_sha256'];service=PerformanceStudio(snaps)
        result=service.read('2026-09-06',revision);assert len(result['fixtures'])==3 and result['coverage']['forecasts']==2
        expanded=service.read('2026-09-06',revision,all_competitions=True)
        assert expanded['all_competitions'] and len(expanded['fixtures'])==5 and expanded['coverage']['forecasts']==2
        assert all(f['forecast'] is None for f in expanded['fixtures'] if f['kind']!='league')
        assert {c['competition']:set(c['teams']) for c in expanded['competitions']}['English League Cup']=={'Alpha','Delta','Survivor'}
        extra=next(f for f in expanded['fixtures'] if f['kind']=='cup');assert extra['minutes']==120 and extra['outcome']=='afterextratime' and extra['result']==[2,1]
        assert extra['xgot']==[1.2,.4] and extra['npxg']==[1.3,.5] and extra['round']==2 and extra['round_label']=='League phase'
        assert extra['stage']=='retained stage' and extra['phase']=='retained phase'
        assert expanded['fixtures'][0]['xgot']==[None,None] and expanded['fixtures'][0]['round'] is None
        # An invalid component remains visible and cannot delete an actual match from last-N windows.
        rows[1]['home_shots']='bad';write_master();invalid_component=service.read('2026-09-06',revision)
        assert len(invalid_component['fixtures'])==3 and invalid_component['fixtures'][1]['shots'][0] is None and invalid_component['issues']
        rows[1]['home_shots']=10;write_master()
        first,second,third=result['fixtures'];assert first['forecast'] is None and second['forecast']['wdl']==[.2,.3,.5] and third['forecast']['wdl']==[.8,.1,.1]
        assert third['forecast']['timing']=='retrospective' and third['forecast']['snapshot']=='2026-09-04'
        # Content replacement with preserved name and mtime still invalidates the cache.
        import os
        stamp=master.stat();rows[0]['home_xg']=2.5;write_master();os.utime(master,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        changed=service.read('2026-09-06',revision);assert changed['input_revision']!=result['input_revision'] and changed['fixtures'][0]['xg'][0]==2.5
        path=snaproot/'2026-09-04/matches.json';raw=json.loads(path.read_text());raw['fixtures'][0]['ladder']['h1']=1.5;path.write_text(json.dumps(raw))
        invalid=service.read('2026-09-06',revision);assert invalid['fixtures'][-1]['forecast'] is None and invalid['fixtures'][-1]['forecast_error'] and invalid['coverage']['invalid_forecasts']==1
        # A newer corrupted probability must not silently fall back to the older valid forecast.
        assert invalid['coverage']['forecasts']==1
        try:service.read('2026-09-06','stale')
        except PerformanceError as exc:assert exc.status==409
        else:raise AssertionError('Stale snapshot revision accepted')
        rows.append(copy.deepcopy(rows[0]));write_master()
        try:service.read('2026-09-06',revision)
        except PerformanceError as exc:assert 'duplicate' in str(exc)
        else:raise AssertionError('Ambiguous result identity accepted')
    assert generation_timing('2026-09-03T13:59:00+00:00',{'competition':comp,'kickoff':'2026-09-03 15:00:00'})=='before_kickoff'
    assert generation_timing(None,{'competition':comp,'kickoff':'2026-09-03 15:00:00'})=='unknown'
    return 'league/all-competition populations; eliminated cup entrants; extra-time exposure; missing optional metrics; invalid component retains actual match; latest eligible cutoff; hash replacement; invalid forecast no fallback; stale revision and duplicate identity reject'


def real_reference(output=None):
    snaps=Snapshots();payload=snaps.load();service=PerformanceStudio(snaps);timings=[]
    for _ in range(2):
        start=time.perf_counter();data=service.read(payload['source']['date'],payload['source']['projection_sha256']);timings.append(time.perf_counter()-start)
    with snaps.master_csv.open() as source:
        actual=[r for r in csv.DictReader(source) if r['season']==str(data['season']) and r['kind']=='league' and r['played']=='True' and r['kickoff'][:10]<=data['as_of']]
    by_id={str(int(float(r['match_id']))):r for r in actual};assert len(by_id)==len(actual)==len(data['fixtures'])>0
    reference={};forecast_count=0
    for f in data['fixtures']:
        row=by_id[f['match_id']];assert f['result']==[int(float(row[k])) for k in ('home_goals','away_goals')]
        assert f['xg']==[float(row[k]) for k in ('home_xg','away_xg')]
        forecast=f['forecast']
        if forecast:
            forecast_count+=1;folder=snaps.root/forecast['snapshot'];raw=(folder/'matches.json').read_bytes();assert hashlib.sha256(raw).hexdigest()==forecast['matches_sha256']
            source=next(x for x in json.loads(raw)['fixtures'] if (x['competition'],x['home'],x['away'],x['kickoff'][:10])==(f['competition'],f['home'],f['away'],f['kickoff'][:10]))
            assert forecast['wdl']==[source['ladder'][k] for k in ('h1','d','a1')]
            assert forecast['as_of']<f['kickoff'][:10] and forecast['snapshot']<=f['kickoff'][:10]<=data['as_of']
        for side,team in enumerate((f['home'],f['away'])):
            gf,ga=f['result'][side],f['result'][1-side];points=3 if gf>ga else 1 if gf==ga else 0
            entry=reference.setdefault(team,{'n':0,'gf':0,'ga':0,'xgf':0.,'xga':0.,'points':0,'forecast_n':0,'covered_points':0,'expected':0.,'residual':0.})
            for key,value in [('n',1),('gf',gf),('ga',ga),('xgf',f['xg'][side]),('xga',f['xg'][1-side]),('points',points)]:entry[key]+=value
            if forecast:
                wdl=forecast['wdl'];expected=3*wdl[0 if side==0 else 2]+wdl[1]
                for key,value in [('forecast_n',1),('covered_points',points),('expected',expected),('residual',points-expected)]:entry[key]+=value
    assert sum(r['n'] for r in reference.values())==2*len(actual) and sum(r['forecast_n'] for r in reference.values())==2*forecast_count
    assert all(abs(r['residual']-(r['covered_points']-r['expected']))<1e-10 for r in reference.values())
    expanded_timings=[]
    for _ in range(2):
        start=time.perf_counter();expanded=service.read(payload['source']['date'],payload['source']['projection_sha256'],all_competitions=True);expanded_timings.append(time.perf_counter()-start)
    competitions={c['competition'] for c in expanded['competitions']}
    with snaps.master_csv.open() as source:
        all_actual=[r for r in csv.DictReader(source) if r['season']==str(data['season']) and r['competition'] in competitions and r['played']=='True' and r.get('tbd')!='True' and r.get('outcome')!='aborted' and r['kickoff'][:10]<=data['as_of']]
    all_by_id={str(int(float(r['match_id']))):r for r in all_actual};assert len(all_by_id)==len(all_actual)==len(expanded['fixtures'])>len(actual)
    def metric(row,key):return None if row.get(key) in (None,'','nan','NaN') else float(row[key])
    all_reference={}
    for fixture in expanded['fixtures']:
        row=all_by_id[fixture['match_id']]
        expected={key:[metric(row,side+'_'+key) for side in ('home','away')] for key in ('xg','xgot','npxg','shots')}
        expected.update(result=[int(float(row[side+'_goals'])) for side in ('home','away')],kind=row['kind'],minutes=metric(row,'minutes'))
        assert all(fixture[key]==value for key,value in expected.items())
        if row['kind']!='league':assert fixture['forecast'] is None
        all_reference[fixture['id']]=dict(expected,competition=row['competition'],home=row['home'],away=row['away'],kickoff=row['kickoff'])
    if output:
        output=Path(output);assert not output.exists() and ROOT/'data' not in output.resolve().parents;output.write_text(json.dumps({'data':data,'reference':reference,'all_data':expanded,'all_reference':all_reference}))
    return {'fixtures':len(actual),'appearances':2*len(actual),'forecasts':forecast_count,'clubs':len(reference),'cold_seconds':timings[0],'warm_seconds':timings[1],'json_bytes':len(json.dumps(data,separators=(',',':')).encode()),'all_fixtures':len(all_actual),'all_competitions':len(competitions),'all_cold_seconds':expanded_timings[0],'all_warm_seconds':expanded_timings[1],'all_json_bytes':len(json.dumps(expanded,separators=(',',':')).encode())}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);args=parser.parse_args()
    print('PASS '+fixtures_case());print(json.dumps(real_reference(args.output),indent=2))
