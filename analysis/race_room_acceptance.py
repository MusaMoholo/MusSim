"""Read-only joint-event bounds and accounting against the published snapshot/GW bundle."""
from pathlib import Path
import gzip,json,sys
import numpy as np
ROOT=Path(__file__).resolve().parent.parent


def bounded(joint,a,b,tol=1e-9):
    return max(0,a+b-1)-tol<=joint<=min(a,b)+tol


def main():
    folder=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'data/snapshots/2026-10-22'
    p=json.loads((folder/'projection.json').read_text())
    gw=json.loads(gzip.decompress((folder/'gw.json.gz').read_bytes())) if (folder/'gw.json.gz').exists() else json.loads((folder/'gw.json').read_text())
    assert gw['worlds']==p['worlds']>0
    assert not bounded(.3,.1,.2), 'Deliberate impossible joint event must fail'
    title_cells=route_cells=0
    for block in p['leagues']:
        g=gw['leagues'][block['competition']];n=len(g['teams']);rounds=g['rounds']+1
        joint=np.zeros((n,rounds));terms=np.zeros((n,rounds),int)
        for i,r,v in g['clinch']:
            assert 0<=v<=1
            joint[i,r]+=v;terms[i,r]+=1
        joint=joint.cumsum(axis=1);terms=terms.cumsum(axis=1)
        settled=joint.sum(axis=0);total_terms=terms.sum(axis=0)
        for i,team in enumerate(g['teams']):
            win=next(t['p_win'] for t in block['teams'] if t['team']==team)
            for r in range(rounds):
                # Each retained probability has at most half a 4dp unit rounding error.
                tol=.00005*(int(total_terms[r])+int(terms[i,r])+1)+1e-9
                assert bounded(joint[i,r],win,settled[r],tol),(team,r,'title/settled Frechet bound')
                assert abs(joint[i,r]+(win-joint[i,r])-win)<1e-12
                title_cells+=1
        assert abs(float(settled[-1])-1)<.00005*int(total_terms[-1])+1e-9
        routes=block.get('entry_routes')
        if routes:
            w=routes['worlds'];assert w==p['worlds']
            for team,values in routes['teams'].items():
                counts=np.asarray(values,dtype=np.int64);entry=np.asarray(routes['entry_counts'][team])/w
                reason=counts.sum(axis=0)/w
                assert np.array_equal(counts.sum(axis=1),routes['entry_counts'][team])
                for e in range(3):
                    for k in range(len(routes['routes'])):
                        assert bounded(counts[e,k]/w,entry[e],reason[k]),(team,e,k,'entry/route Frechet bound')
                        route_cells+=1
    assert title_cells>1000 and route_cells>0
    print(f'PASS {title_cells} title/settled and {route_cells} entry/route joint-event Frechet bounds;exclusive sums;nonempty world counts')
    print('PASS deliberate impossible joint event rejected;no source values clamped')

if __name__=='__main__':main()
