"""Exact metadata-only snapshot comparison used for roadmap item 7.

Later roadmap items add other fields; compare the archived part-1 output when reproducing this log.
"""
import gzip
import json
from pathlib import Path

import argparse

parser = argparse.ArgumentParser(description='Audit v11 part 1: all existing v10 snapshot values stay exact.')
parser.add_argument('before', type=Path, help='Archived v10 snapshot folder')
parser.add_argument('after', type=Path, help='Regenerated v11 part-1 snapshot folder')
args = parser.parse_args()
before, after = args.before, args.after

def read(folder, name):
    path = folder / name
    return json.loads(gzip.decompress(path.read_bytes()) if name.endswith('.gz') else path.read_bytes())

def strip_h2h(value):
    if isinstance(value, dict):
        return {k: strip_h2h(v) for k, v in value.items() if k != 'h2h'}
    if isinstance(value, list):
        return [strip_h2h(v) for v in value]
    return value

cells = 0
def equal(old, new, path):
    global cells
    if isinstance(old, dict):
        assert isinstance(new, dict) and old.keys() == new.keys(), (path, set(old) ^ set(new))
        for key in old:
            equal(old[key], new[key], path + '.' + key)
    elif isinstance(old, list):
        assert isinstance(new, list) and len(old) == len(new), (path, len(old), len(new))
        for i, (left, right) in enumerate(zip(old, new)):
            equal(left, right, path + '[' + str(i) + ']')
    else:
        assert old == new, (path, old, new)
        cells += 1

for name in ('projection.json', 'matches.json', 'gw.json.gz', 'paths.json.gz'):
    old, new = read(before, name), read(after, name)
    if name == 'projection.json':
        assert old['version'] == 10 and new['version'] == 11 and new['model'] == '2026-10-21'
        new.pop('model')
        for key in ('version', 'generated', 'elapsed'):
            old.pop(key)
            new.pop(key)
        extra_scales = set(new['ratings']['rel']) - set(old['ratings']['rel'])
        assert len(extra_scales) == 6, extra_scales
        for key in extra_scales:
            new['ratings']['rel'].pop(key)
        print('New cup strength scales:', ', '.join(sorted(extra_scales)))
    equal(strip_h2h(old), strip_h2h(new), name)
    print('PASS exact existing values:', name)
print(f'PASS {cells:,} existing scalar values unchanged; only version/model/head-to-head/cup-scale metadata added')
