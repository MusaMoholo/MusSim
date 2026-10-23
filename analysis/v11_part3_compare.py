"""Exact snapshot comparison used for roadmap item 9.

Compare archived item-8/item-9 output after later roadmap additions.
"""
import gzip
import json
from pathlib import Path

import argparse

parser = argparse.ArgumentParser(description='Audit sample-world additions: existing item-8 values stay exact.')
parser.add_argument('before', type=Path, help='Archived item-8 snapshot folder')
parser.add_argument('after', type=Path, help='Regenerated item-9 snapshot folder')
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
        assert len(new.pop('samples')) == 5, 'Five sampled worlds required'
        for key in ('generated', 'elapsed'):
            old.pop(key)
            new.pop(key)
    equal(old, new, name)
    print('PASS exact existing values:', name)
print(f'PASS {cells:,} existing scalar values unchanged; only five sampled worlds/run timing added')
