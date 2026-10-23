"""Model-free job boundary checks using isolated inputs and a controlled worker."""
from __future__ import annotations
import copy,csv,json,shutil,sys,tempfile,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.scenario_store import ScenarioManager,ScenarioError,catalog,source_manifest,validate
from scripts.dashboard_store import Snapshots


def verify():
    live=Snapshots();payload=live.load();day=payload['source']['date'];revision=payload['source']['projection_sha256']
    from scripts.scenario_store import MODEL
    payload['model']=MODEL  # isolated current-generation catalogue, independent of owner publication
    class Saved:
        def load(self,value):return copy.deepcopy(payload) if value==day else None
        def list(self):return [{'date':day}]
    with tempfile.TemporaryDirectory(prefix='football-scenario-test-') as directory:
        root=Path(directory);(root/'data').mkdir();shutil.copyfile(ROOT/'data/master_fixtures.csv',root/'data/master_fixtures.csv')
        # Job-boundary tests need a controlled snapshot-consistent fixture ledger. A live
        # collection can be ahead of the latest projection while owner backfill is running.
        master=root/'data/master_fixtures.csv'
        with master.open() as handle:
            reader=csv.DictReader(handle);fields=reader.fieldnames;rows=list(reader)
        for row in rows:
            if str(row['season'])==str(payload['params']['season']) and row['kickoff'][:10]>payload['as_of']:
                row['played']='False'
                for key in ['home_goals','away_goals','outcome','minutes']:
                    if key in row:row[key]=''
        with master.open('w',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader();writer.writerows(rows)
        snaps=Saved();cat=catalog(snaps,day,revision,root=root);assert cat['available'] and cat['fixtures']
        body={'date':day,'revision':revision,'input_revision':cat['input_revision'],'competition':cat['competitions'][0],'worlds':200,'seed':1,'conditions':[]}
        calls=[];release=threading.Event();entered=threading.Event()
        def worker(params,comp,conditions,processes,progress,cancel):
            calls.append((params,conditions));entered.set();progress(8,params['worlds'],3,'simulating')
            assert release.wait(5),'test worker never released'
            return {'proposals':params['worlds'],'accepted':3}
        def done(manager,key):
            for _ in range(500):
                state=manager.get(key)
                if state['status']!='running':return state
                time.sleep(.005)
            raise AssertionError('job failed to finish')
        manager=ScenarioManager(snaps,root=root,executor=worker)
        broken={**body,'conditions':[{'fixture':cat['fixtures'][0]['id'],'outcome':'home'},{'fixture':cat['fixtures'][0]['id'],'outcome':'away'}]}
        try:manager.start(broken)
        except ScenarioError:pass
        else:raise AssertionError('contradiction did not reject')
        assert not calls and not manager.jobs
        key,_=manager.start(body);assert entered.wait(5)
        try:manager.start(body)
        except ScenarioError as e:assert e.status==409
        else:raise AssertionError('concurrent job accepted')
        assert manager.get(key)['done']==8
        manager.cancel(key);release.set();assert done(manager,key)['status']=='cancelled' and 'result' not in manager.get(key)
        # A replacement source with the same filename invalidates an in-flight answer.
        release.clear();entered.clear();key,_=manager.start(body);assert entered.wait(5)
        with (root/'data/master_fixtures.csv').open('a') as out:out.write('\n')
        release.set();state=done(manager,key);assert state['status']=='error' and 'discarded' in state['error'] and 'result' not in state
        try:manager.start(body)
        except ScenarioError as e:assert e.status==409
        else:raise AssertionError('stale input revision accepted')
        updated={**body,'input_revision':source_manifest(root)['sha256']};key,_=manager.start(updated);state=done(manager,key)
        assert state['status']=='done' and state['result']['source']==payload['source']
        assert state['result']['params']['as_of'] is None and state['result']['params']['worlds']==200
        assert state['result']['input_revision']==updated['input_revision']
        try:manager.cancel('expired')
        except ScenarioError as e:assert e.status==404
        else:raise AssertionError('missing job accepted')
        release.clear();entered.clear();key,_=manager.start(updated);assert entered.wait(5)
        previous=payload['source']['projection_sha256'];payload['source']['projection_sha256']='replacement'
        release.set();state=done(manager,key);payload['source']['projection_sha256']=previous
        assert state['status']=='error' and 'pinned forecast changed' in state['error'] and 'result' not in state
        assert len(calls)==4
        # Edited Python must never mix newly spawned workers with previously imported code.
        from scripts import scenario_store as store
        saved_code=store._CODE_AT_IMPORT
        try:
            store._CODE_AT_IMPORT={}
            actual=catalog(snaps,day,revision,root=root);guard=ScenarioManager(snaps,root=root,executor=worker)
            from unittest.mock import patch
            with patch.object(store,'ROOT',root):
                key,_=guard.start({**body,'input_revision':actual['input_revision']})
                state=done(guard,key);assert state['status']=='error' and 'Restart' in state['error'] and len(calls)==4
        finally:store._CODE_AT_IMPORT=saved_code
    return 'contradictions before worker; single active job; targeted cancellation; changed-source discard and retry; snapshot revision discard; stale-code restart guard; saved params; expiry'

if __name__=='__main__':print('PASS '+verify())
