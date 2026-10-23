"""Independent stored-snapshot/GW reconciliation, adversarial temporal guards and read cost."""
from __future__ import annotations
import argparse,copy,gzip,hashlib,json,os,sys,tempfile,time
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.dashboard_store import Snapshots
from scripts.time_machine import TimeMachine,TimeMachineError,bridge


def cases():
    with tempfile.TemporaryDirectory(prefix='football-time-machine-') as directory:
        root=Path(directory);master=root/'master.csv';master.write_text('CURRENT MASTER MUST NEVER BE READ')
        comp='English Premier League';days=['2026-09-02','2026-09-03'];index=[{'date':d} for d in days]
        (root/'index.json').write_text(json.dumps(index))
        for i,day in enumerate(days):
            folder=root/day;folder.mkdir()
            p={'params':{'season':2026,'seed':1},'worlds':100,'version':11,'model':'old' if i==0 else 'new','as_of':'2026-09-01' if i==0 else '2026-09-02','generated':'2026-10-22T10:00:00+00:00',
               'leagues':[{'competition':comp,'teams':[{'team':'Alpha','mean_pts':60.1234567890123+i,'p_win':.4+i*.1,'now':{'pts':3 if i==0 else 1,'pl':1}},{'team':'Beta','mean_pts':40.2,'p_win':.6-i*.1,'now':{'pts':0 if i==0 else 1,'pl':1}}]}],
               'cups':[{'competition':'Italian Coppa Italia','teams':[{'team':'Fiorentina','p_r16':1.4}]}],
               'ratings':{'teams':[{'team':'Alpha','elo':1500+i,'att':1.5,'def':.75}],'rel':{comp:{'now':[1+i*.1,2-i*.1]}}}}
            (folder/'projection.json').write_text(json.dumps(p))
            f={'home':'Alpha','away':'Beta','kickoff':'2026-09-01 15:00:00','result':[1,0] if i==0 else [1,1],'xg':[1.2,.5]}
            (folder/'gw.json.gz').write_bytes(gzip.compress(json.dumps({'leagues':{comp:{'fixtures':[f]}}}).encode()))
        snaps=Snapshots(root,master);service=TimeMachine(snaps);pins={d:snaps.load(d)['source']['projection_sha256'] for d in days}
        query=lambda a=days[0],b=days[1]:service.compare(days[1],pins[days[1]],a,pins[a],b,pins[b],comp)
        d=query();r=d['rows'][0];assert r['team']=='Alpha' and r['bridge']['banked']==-2 and r['bridge']['expected_final']==1 and r['bridge']['expected_remaining']==3
        assert d['ledger'][0]['change']=='revised' and d['ledger'][0]['points_delta']=={'Alpha':-2,'Beta':1}
        assert all(r['valid'] for r in d['reconciliation']) and d['changes']['model'] and all(i['field']=='p_r16' for i in d['issues'])
        assert d['before']['timing']=='rebuilt_later' and d['after']['timing']=='rebuilt_later'
        assert d['rows'][0]['before']['strength']['competition']['att']==1.5 and d['rows'][0]['after']['strength']['competition']['att']==1.5*1.1
        reverse=query(days[1],days[0]);assert all(reverse['rows'][i]['bridge'][k]==-r['bridge'][k] for i,r in enumerate(d['rows']) for k in ('banked','expected_final','expected_remaining'))
        same=query(days[1],days[1]);assert not same['ledger'] and all(all(r['bridge'][k]==0 for k in ('banked','expected_final','expected_remaining')) for r in same['rows'])
        assert all('master' not in name for name in d['input_files']);master.write_text('REPLACED TODAY');assert query()==d
        # A wrong derived remaining-points component must fail rather than balance by construction.
        broken=copy.deepcopy(r['before']);broken['expected_remaining']+=1
        try:bridge(broken,r['after'])
        except TimeMachineError:pass
        else:raise AssertionError('Bridge fault escaped')
        path=root/days[0]/'projection.json';old=path.stat();raw=json.loads(path.read_bytes());raw['leagues'][0]['teams'][0]['p_win']=1.4;path.write_text(json.dumps(raw));os.utime(path,ns=(old.st_atime_ns,old.st_mtime_ns))
        try:query()
        except TimeMachineError as error:assert error.status==409
        else:raise AssertionError('Stale endpoint pin accepted after same-mtime replacement')
        pins[days[0]]=snaps.load(days[0])['source']['projection_sha256'];bad=query();alpha=next(r for r in bad['rows'] if r['team']=='Alpha');assert alpha['before']['p_win'] is None and alpha['delta']['p_win'] is None and any(i['field']=='p_win' and i['value']==1.4 for i in bad['issues'])
        fixturepath=root/days[1]/'gw.json.gz';saved=fixturepath.read_bytes();fixturepath.unlink();missing=query();assert missing['ledger'] is None and missing['rows'][0]['bridge'] is not None
        fixturepath.write_bytes(saved);gw=json.loads(gzip.decompress(saved));gw['leagues'][comp]['fixtures'][0]['kickoff']='2026-09-04 15:00:00';fixturepath.write_bytes(gzip.compress(json.dumps(gw).encode()))
        try:query()
        except TimeMachineError as error:assert 'cutoff' in str(error)
        else:raise AssertionError('Future stored result accepted')
        fixturepath.write_bytes(saved);gw=json.loads(gzip.decompress(saved));gw['leagues'][comp]['fixtures']*=2;fixturepath.write_bytes(gzip.compress(json.dumps(gw).encode()))
        try:query()
        except TimeMachineError as error:assert 'Duplicate' in str(error)
        else:raise AssertionError('Duplicate stored fixture accepted')
        fixturepath.write_bytes(saved);gw=json.loads(gzip.decompress(saved));gw['leagues'][comp]['fixtures'][0]['result']=[9,0];fixturepath.write_bytes(gzip.compress(json.dumps(gw).encode()));gap=query();assert any(not r['valid'] for r in gap['reconciliation'])
        try:service.compare(days[0],pins[days[0]],days[0],pins[days[0]],days[1],pins[days[1]],comp)
        except TimeMachineError:pass
        else:raise AssertionError('Endpoint exceeds pinned dashboard knowledge date')
    return 'exact decimal/reverse/same-date bridges; revised score ledger; stored-only/current-master independence; generation/model/scales; bad component, stale content, invalid probability, missing/future/duplicate/corrupt GW and anchor guards'


def raw_gw(root,day,comp):
    packed=root/day/'gw.json.gz';plain=root/day/'gw.json'
    return json.loads(gzip.decompress(packed.read_bytes()) if packed.exists() else plain.read_bytes())['leagues'][comp]['fixtures']


def real_reference(output=None):
    snaps=Snapshots();root=snaps.root;latest=snaps.load();day=latest['source']['date'];pin=latest['source']['projection_sha256'];service=TimeMachine(snaps)
    start=time.perf_counter();catalog=service.catalog(day,pin);cold=time.perf_counter()-start
    dates={d['date']:d for d in catalog['dates']};a='2026-09-22' if '2026-09-22' in dates else catalog['dates'][0]['date'];b=day
    counts={'catalog_dates':len(dates),'bridges':0,'fixture_club_totals':0,'probability_cells':0,'reversal_cells':0}
    proof=None;timings=[]
    for comp in catalog['dates'][-1]['competitions']:
        start=time.perf_counter();d=service.compare(day,pin,a,dates[a]['projection_sha256'],b,dates[b]['projection_sha256'],comp);timings.append(time.perf_counter()-start)
        pa=snaps.load(a);pb=snaps.load(b);la=next(l for l in pa['leagues'] if l['competition']==comp);lb=next(l for l in pb['leagues'] if l['competition']==comp)
        teams_a={t['team']:t for t in la['teams']};teams_b={t['team']:t for t in lb['teams']}
        ga,gb=raw_gw(root,a,comp),raw_gw(root,b,comp)
        for row in d['rows']:
            team=row['team'];ta,tb=teams_a[team],teams_b[team];banked_a=ta['now']['pts'];banked_b=tb['now']['pts'];final_a=Fraction(str(ta['mean_pts']));final_b=Fraction(str(tb['mean_pts']))
            expected={'banked':Fraction(banked_b-banked_a),'expected_final':final_b-final_a,'expected_remaining':(final_b-banked_b)-(final_a-banked_a)}
            assert all(Fraction(row['bridge']['exact'][key])==value for key,value in expected.items());counts['bridges']+=1
            for meta,fixtures,t in ((pa,ga,ta),(pb,gb,tb)):
                played=[f for f in fixtures if f.get('result') is not None and team in (f['home'],f['away'])];points=0
                for f in played:
                    assert f['kickoff'][:10]<=meta['as_of'];h,g=f['result'];own,other=(h,g) if f['home']==team else (g,h);points+=3 if own>other else 1 if own==other else 0
                assert points==t['now']['pts'] and len(played)==t['now']['pl'];counts['fixture_club_totals']+=1
            for key in ('p_win','p_ucl','p_uel','p_uecl','p_releg'):
                assert row['before'][key]==ta[key] and row['after'][key]==tb[key];assert abs(row['delta'][key]-(tb[key]-ta[key]))<1e-12;counts['probability_cells']+=1
            match_delta=sum(f['points_delta'].get(team,0) for f in d['ledger']);assert match_delta==banked_b-banked_a
        reverse=service.compare(day,pin,b,dates[b]['projection_sha256'],a,dates[a]['projection_sha256'],comp);back={r['team']:r for r in reverse['rows']}
        for row in d['rows']:
            for key,value in row['delta'].items():
                assert back[row['team']]['delta'][key]==-value if value is not None else back[row['team']]['delta'][key] is None;counts['reversal_cells']+=1
        same=service.compare(day,pin,b,dates[b]['projection_sha256'],b,dates[b]['projection_sha256'],comp);assert not same['ledger'] and all(all(v==0 for v in r['delta'].values() if v is not None) for r in same['rows'])
        if comp=='English Premier League':proof=d
    oldest=catalog['dates'][0];history=service.compare(day,pin,oldest['date'],oldest['projection_sha256'],b,dates[b]['projection_sha256'],'English Premier League')
    invalid=[i for i in history['issues'] if i['competition']=='Italian Coppa Italia' and i['team']=='Fiorentina' and i['field']=='p_r16'];assert len(invalid)==12 and all(i['value']>1 for i in invalid)
    counts.update(catalog_cold_seconds=cold,comparison_seconds=timings,known_invalid_coppa=len(invalid),json_bytes=len(json.dumps(proof,separators=(',',':')).encode()))
    if output:
        output=Path(output);assert not output.exists() and ROOT/'data' not in output.resolve().parents;output.write_text(json.dumps({'catalog':catalog,'data':proof,'history':history}))
    return counts

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);args=parser.parse_args();print('PASS '+cases());print(json.dumps(real_reference(args.output),indent=2))
