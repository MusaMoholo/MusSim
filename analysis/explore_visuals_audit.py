"""Independent stored schedule, common-scale ranks and title-curve reference; no writes to data."""
from __future__ import annotations
import argparse,copy,gzip,hashlib,json,os,sys,tempfile,time
from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from scripts.dashboard_store import Snapshots
from scripts.explore_visuals import ExploreVisuals,ExploreError
from scripts.forecast_lab import ZONES

def cases():
    with tempfile.TemporaryDirectory(prefix='football-explore-') as directory:
        root=Path(directory);day='2026-10-22';folder=root/day;folder.mkdir();comp='English Premier League';p={'params':{'season':2026},'as_of':'2026-10-21'};(folder/'projection.json').write_text(json.dumps(p));(root/'index.json').write_text(json.dumps([{'date':day}]))
        f={'home':'Alpha','away':'Beta','kickoff':'2026-10-24 15:00:00'};gw={'leagues':{comp:{'fixtures':[f]}}};(folder/'gw.json.gz').write_bytes(gzip.compress(json.dumps(gw).encode()));m={'fixtures':[{**f,'competition':comp,'p_occurs':1},{**f,'home':'Gamma','p_occurs':.8,'competition':comp}]};mp=folder/'matches.json';mp.write_text(json.dumps(m));master=root/'DO_NOT_READ.csv';master.write_text('forbidden current data')
        snaps=Snapshots(root,master);lab=ExploreVisuals(snaps);pin=snaps.load(day)['source']['projection_sha256'];read=lambda ir='':lab.read(day,pin,ir);d=read();assert len(d['fixtures'])==1 and len(d['fixtures'][0]['evidence'])==2 and len(d['issues'])==1
        assert all('master' not in k and 'DO_NOT_READ' not in k for k in d['input_files']);master.write_text('changed');assert read()==d
        try:lab.read(day,'stale')
        except ExploreError as e:assert e.status==409
        else:raise AssertionError('Stale projection accepted')
        old=mp.stat();m['fixtures'][0]['kickoff']='2026-10-24 16:00:00';mp.write_text(json.dumps(m));os.utime(mp,ns=(old.st_atime_ns,old.st_mtime_ns))
        try:read(d['input_revision'])
        except ExploreError as e:assert e.status==409
        else:raise AssertionError('Same-mtime replacement accepted')
        try:read()
        except ExploreError as e:assert 'Conflicting' in str(e)
        else:raise AssertionError('Conflicting kickoff accepted')
        m['fixtures'][0]['kickoff']=f['kickoff'];m['fixtures'].append(copy.deepcopy(m['fixtures'][0]));mp.write_text(json.dumps(m))
        try:read()
        except ExploreError as e:assert 'Duplicate' in str(e)
        else:raise AssertionError('Duplicate schedule accepted')
        mp.unlink();(folder/'gw.json.gz').unlink();empty=read();assert empty['coverage']=={'gw':False,'matches':False,'fixed_fixture_records':0} and not empty['fixtures']
    return 'stored-only source pins; conditional/duplicate/conflicting fixtures; same-mtime replacement; missing sidecars unavailable'

def real_reference(output=None):
    snaps=Snapshots();result=snaps.load('2026-10-22');store=ExploreVisuals(snaps);start=time.perf_counter();schedule=store.read('2026-10-22',result['source']['projection_sha256']);cold=time.perf_counter()-start;start=time.perf_counter();assert store.read('2026-10-22',result['source']['projection_sha256'])==schedule;warm=time.perf_counter()-start
    root=snaps.root/'2026-10-22';gw=json.loads(gzip.decompress((root/'gw.json.gz').read_bytes()));matches=json.loads((root/'matches.json').read_bytes());raw={}
    for category in ('leagues','phases'):
        for comp,block in gw[category].items():
            for f in block['fixtures']:
                if f.get('result') is None:raw[(comp,f['home'],f['away'],f['kickoff'][:10])]={**f,'competition':comp}
    for f in matches['fixtures']:
        if f.get('result') is None and f.get('p_occurs',1)==1:raw.setdefault((f['competition'],f['home'],f['away'],f['kickoff'][:10]),f)
    keys={(f['competition'],f['home'],f['away'],f['kickoff'][:10]) for f in schedule['fixtures']};assert keys==set(raw) and len(keys)>0
    start_date=datetime.fromisoformat(result['source']['date']).date();end_date=start_date+timedelta(days=27);appearances={t['team']:[] for l in result['leagues'] for t in l['teams']};window=[]
    for f in raw.values():
        stamp=datetime.fromisoformat(f['kickoff'].replace('Z','+00:00'))
        if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=ZoneInfo(ZONES[f['competition']]))
        day=stamp.astimezone(ZoneInfo('Europe/London')).date()
        if not start_date<=day<=end_date:continue
        k='|'.join((f['competition'],f['home'],f['away'],f['kickoff'][:10]));item={'key':k,'instant':stamp.timestamp()*1000,'uk_day':day.isoformat(),'monday':(day-timedelta(days=day.weekday())).isoformat()};window.append(item)
        for team in (f['home'],f['away']):
            if team in appearances:appearances[team].append(item)
    calendar={}
    for team,fixtures in appearances.items():
        fixtures.sort(key=lambda f:(f['instant'],f['key']));gaps=[(b['instant']-a['instant'])/3600000 for a,b in zip(fixtures,fixtures[1:])];calendar[team]={'keys':[f['key'] for f in fixtures],'total':len(fixtures),'shortest':min(gaps) if gaps else None,'weeks':dict(Counter(f['monday'] for f in fixtures))}
    ratings={r['team']:r for r in result['ratings']['teams']};depth={}
    for metric in ('elo','att','def','net'):
        depth[metric]={}
        for l in result['leagues']:
            values=[{'team':t['team'],'value':ratings[t['team']]['att']-ratings[t['team']]['def'] if metric=='net' else ratings[t['team']][metric]} for t in l['teams']];values.sort(key=lambda r:(r['value'] if metric=='def' else -r['value'],r['team']));depth[metric][l['competition']]=values
    title={}
    for l in result['leagues']:
        ranked=sorted(l['teams'],key=lambda r:(-r['p_win'],r['team']));cumulative=0;rows=[]
        for rank,t in enumerate(ranked,1):cumulative+=t['p_win'];rows.append({'team':t['team'],'rank':rank,'prob':t['p_win'],'cumulative':cumulative,'share':100*rank/len(ranked)})
        assert abs(cumulative-1)<=len(ranked)*.00005+1e-12;title[l['competition']]=rows
    if output:
        assert not output.exists();output.write_text(json.dumps({'result':result,'schedule':schedule,'reference':{'calendar':calendar,'depth':depth,'title':title,'window':window}},allow_nan=False))
    return {'fixed_records':len(raw),'window_records':len(window),'clubs':len(appearances),'club_appearances':sum(len(v) for v in appearances.values()),'cold_seconds':cold,'warm_seconds':warm,'json_bytes':len(json.dumps(schedule,separators=(',',':')).encode()),'rank_cells':4*len(appearances),'title_cells':len(appearances)}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);args=parser.parse_args();print('PASS '+cases());print(json.dumps(real_reference(args.output),indent=2))
