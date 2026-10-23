"""Compare one approved rivals publication to its archived bundle, without changing either.

.venv/bin/python analysis/race_room_publication_audit.py /path/to/original /path/to/published
"""
import gzip
import json
from pathlib import Path
import sys
import numpy as np


def read(folder,stem):
    zipped=folder/(stem+'.json.gz')
    return json.loads(gzip.decompress(zipped.read_bytes()) if zipped.exists() else (folder/(stem+'.json')).read_bytes())


def compare(a,b,path=''):
    if type(a)!=type(b): raise AssertionError(f'{path}: types differ')
    if isinstance(a,dict):
        assert a.keys()==b.keys(), f'{path}: keys differ'
        return sum(compare(a[k],b[k],path+'/'+str(k)) for k in a)
    if isinstance(a,list):
        assert len(a)==len(b), f'{path}: lengths differ'
        return sum(compare(x,y,path+'/'+str(i)) for i,(x,y) in enumerate(zip(a,b)))
    assert a==b, f'{path}: {a!r} != {b!r}'
    return 1


def main():
    before,after=map(Path,sys.argv[1:3])
    old,new=read(before,'projection'),read(after,'projection')
    assert new['version'] in (13,14) and old['model']==new['model']
    assert old['params']==new['params'], 'Original simulation parameters must remain exact'
    assert old['worlds']==new['worlds']==10000 and old['as_of']==new['as_of']
    for block in new['leagues']:
        if block['competition']!='English Premier League':
            assert 'rivals' not in block
            continue
        r=block['rivals'];g=np.asarray(r['gap_counts'],np.int64);pos=np.asarray(r['position_counts'],np.int64)
        n,w=len(r['teams']),r['worlds'];above=g[:,:,n:].sum(axis=2)
        assert w==new['worlds'] and np.all(g.sum(axis=2)==w)
        assert np.array_equal(above+above.T,(1-np.eye(n,dtype=int))*w)
        assert np.array_equal(above.sum(axis=1),pos@np.arange(n-1,-1,-1))
        assert np.array_equal(g,g.transpose(1,0,2)[:,:,::-1])
        for i,t in enumerate(r['teams']):
            row=next(row for row in block['teams'] if row['team']==t)
            assert abs(float(pos[i]@np.arange(1,n+1)/w)-row['mean_pos'])<=.005001
        raw=json.dumps(r,separators=(',',':')).encode()
        print(f'Rivals: {n} teams, {w} worlds, {len(raw)} compact JSON / {len(gzip.compress(raw,mtime=0))} gzip bytes')
        previous=next(v for v in old['leagues'] if v['competition']==block['competition'])
        if 'rivals' not in previous:block.pop('rivals')
        if new['version']>=14:
            routes=block['entry_routes'];assert routes['worlds']==w and routes['schema']==1
            global_entry={v['team']:v for v in new['europe']['teams']}
            cells=0
            for team,values in routes['teams'].items():
                counts=np.asarray(values,np.int64);m=np.asarray(routes['entry_counts'][team])
                assert (counts>=0).all() and counts.sum()<=w and np.array_equal(counts.sum(axis=1),m)
                for e,key in enumerate(routes['entries']):
                    source=global_entry.get(team)
                    if source is None:assert int(m.sum())==0, 'Only zero-entry clubs may be absent from the retained nonzero list'
                    assert abs(float(m[e]/w)-(source['p_'+key] if source else 0))<=.000050001
                    cells+=1
            print(f'Routes: {len(routes["teams"])} clubs, {cells} independently retained entry marginals exact')
            raw=json.dumps(routes,separators=(',',':')).encode()
            print(f'Route JSON: {len(raw)} compact / {len(gzip.compress(raw,mtime=0))} gzip bytes')
            if 'entry_routes' not in previous:block.pop('entry_routes')

    for p in (old,new):
        for k in ('version','generated','elapsed'):p.pop(k,None)
    count=compare(old,new)
    for stem in ('matches','gw','paths','players'):
        cells=compare(read(before,stem),read(after,stem));count+=cells
        print(f'{stem}: {cells} identical existing scalars')
    print(f'PASS {count} existing scalar values exact; only newly added Race Room fields, payload version and run timestamps differ')

if __name__=='__main__':main()
