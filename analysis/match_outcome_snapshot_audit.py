#!/usr/bin/env python3
"""Compare the archived snapshot to the score-count-only regeneration; never write data."""
import gzip
import json
import sys
import tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def compare(archive,day='2026-10-22'):
    folder=ROOT/'data/snapshots'/day;counts={};problems=[]
    with tarfile.open(archive) as tar:
        def old(name):
            b=tar.extractfile('data/snapshots/'+day+'/'+name).read()
            return json.loads(gzip.decompress(b) if name.endswith('.gz') else b)
        def now(name):
            b=(folder/name).read_bytes();return json.loads(gzip.decompress(b) if name.endswith('.gz') else b)
        for name in ['projection.json','matches.json','gw.json.gz','players.json.gz','paths.json','paths.json.gz']:
            if not (folder/name).exists():continue
            a,b=old(name),now(name)
            if name=='projection.json':
                for k in ['generated','elapsed','version']:a.pop(k,None);b.pop(k,None)
            if name=='matches.json':
                for f in b['fixtures']:
                    grid=f.pop('score_counts',None);cap=f.pop('score_cap',None)
                    if grid is None or len(grid)!=cap+1 or any(len(r)!=cap+1 for r in grid) or sum(map(sum,grid))!=f['n']:problems.append('invalid grid '+str(f['fixture_id']))
                    counts['new_grids']=counts.get('new_grids',0)+1
            def scalars(x):
                if isinstance(x,dict):return sum(scalars(v) for v in x.values())
                if isinstance(x,list):return sum(scalars(v) for v in x)
                return 1
            counts[name]=scalars(a)
            if a!=b:problems.append(name+':pre-existing fields differ')
    return {'counts':counts,'errors':problems}

if __name__=='__main__':
    result=compare(sys.argv[1]);print(json.dumps(result,indent=2));raise SystemExit(bool(result['errors']))
