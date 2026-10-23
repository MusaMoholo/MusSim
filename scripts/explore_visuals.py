"""Compact source-pinned fixed schedule for cross-competition charts; stored files only."""
from __future__ import annotations
import gzip
import hashlib
import json
import threading
from pathlib import Path

class ExploreError(ValueError):
    def __init__(self,message,status=400):super().__init__(message);self.status=status

class ExploreVisuals:
    def __init__(self,snapshots):self.snaps=snapshots;self.lock=threading.Lock();self.cache={}
    def read(self,day,revision,input_revision=''):
        if day not in {r['date'] for r in self.snaps.list()}:raise ExploreError('Choose a retained snapshot.',404)
        p=self.snaps.load(day)
        if not revision or p['source']['projection_sha256']!=revision:raise ExploreError('Pinned forecast changed. Reload the snapshot.',409)
        paths=[self.snaps.root/day/name for name in ('projection.json','gw.json.gz','gw.json','matches.json')]
        def manifest():return {str(x):hashlib.sha256(x.read_bytes()).hexdigest() if x.exists() else None for x in paths}
        refs=manifest();digest=hashlib.sha256(json.dumps(refs,sort_keys=True).encode()).hexdigest()
        if input_revision and input_revision!=digest:raise ExploreError('Stored schedule evidence changed. Reset evidence to adopt the current revision.',409)
        with self.lock:cached=self.cache.get((day,revision,digest))
        if cached is not None:return cached
        packed,plain,match=paths[1:];gw=json.loads(gzip.decompress(packed.read_bytes())) if packed.exists() else json.loads(plain.read_bytes()) if plain.exists() else None
        matches=json.loads(match.read_bytes()) if match.exists() else None;fixtures={};issues=[]
        def consume(rows,competition=None,origin='matches'):
            seen=set()
            for raw in rows:
                comp=competition or raw.get('competition');home=raw.get('home');away=raw.get('away');kickoff=raw.get('kickoff')
                if not all(isinstance(v,str) and v for v in (comp,home,away,kickoff)) or home==away:raise ExploreError('Invalid stored fixture identity.',409)
                if raw.get('result') is not None:continue
                if raw.get('p_occurs',1)!=1:
                    issues.append({'competition':comp,'home':home,'away':away,'kickoff':kickoff,'reason':'Conditional pairing excluded'});continue
                if raw.get('tbd') or home.lower() in ('tbd','unknown') or away.lower() in ('tbd','unknown'):
                    issues.append({'competition':comp,'home':home,'away':away,'kickoff':kickoff,'reason':'Unconfirmed pairing excluded'});continue
                k=(comp,home,away,kickoff[:10])
                if k in seen:raise ExploreError('Duplicate stored schedule fixture.',409)
                seen.add(k)
                if k in fixtures:
                    if fixtures[k]['kickoff']!=kickoff:raise ExploreError('Conflicting stored kickoff revisions.',409)
                    fixtures[k]['evidence'].append(origin);continue
                fixtures[k]={'id':hashlib.sha256(json.dumps(k,ensure_ascii=False).encode()).hexdigest()[:24],'competition':comp,'home':home,'away':away,'kickoff':kickoff,'result':None,'evidence':[origin]}
        if gw:
            for category in ('leagues','phases'):
                for comp,block in gw.get(category,{}).items():consume(block.get('fixtures',[]),comp,'gw/'+category)
        if matches:consume(matches.get('fixtures',[]))
        # Compare bytes again before exposing a mixed-file bundle.
        if refs!=manifest() or self.snaps.load(day)['source']!=p['source']:raise ExploreError('Schedule evidence changed during the read.',409)
        out={'schema':1,'source':p['source'],'as_of':p['as_of'],'input_revision':digest,
             'input_files':{Path(k).name:v for k,v in refs.items()},'fixtures':sorted(fixtures.values(),key=lambda f:(f['kickoff'],f['competition'],f['home'],f['away'],f['id'])),'issues':issues,
             'coverage':{'gw':gw is not None,'matches':matches is not None,'fixed_fixture_records':len(fixtures)},
             'notice':'Stored fixed pairings only. Undrawn cup/UEFA participation is unknown; counts are a lower bound on future workload. No current master/provider data enriches old snapshots.'}
        with self.lock:self.cache={(day,revision,digest):out}
        return out
