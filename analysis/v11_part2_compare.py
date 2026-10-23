"""Exact snapshot comparison used for roadmap item 8.

Later additions need the archived item-8 output to reproduce this historical audit.
"""
import gzip
import json
from pathlib import Path

import argparse

parser = argparse.ArgumentParser(description='Audit what-if additions: all existing item-7 values stay exact.')
parser.add_argument('before', type=Path, help='Archived item-7 snapshot folder')
parser.add_argument('after', type=Path, help='Regenerated item-8 snapshot folder')
args = parser.parse_args()
before, after = args.before, args.after

def read(folder, name):
    content = (folder / name).read_bytes()
    return json.loads(gzip.decompress(content) if name.endswith('.gz') else content)

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
        for key in ('generated', 'elapsed'):
            old.pop(key)
            new.pop(key)
    if name == 'matches.json':
        count = sum('whatif' in f for f in new['fixtures'])
        assert count > 0, 'No what-if fixtures to compare'
        for fixture in new['fixtures']:
            fixture.pop('whatif', None)
        print(f'New conditional fields on {count} fixtures')
    equal(old, new, name)
    print('PASS exact existing values:', name)
print(f'PASS {cells:,} existing scalar values unchanged; only new conditional tallies/run timing added')
