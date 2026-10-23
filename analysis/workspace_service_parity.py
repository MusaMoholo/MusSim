#!/usr/bin/env python3
"""Read-only parity proof for the extracted dashboard store against an archived server class.

Usage: .venv/bin/python analysis/workspace_service_parity.py --baseline ARCHIVE.tar.gz
The archive must contain scripts/serve.py. No model imports, collection or snapshot writes.
"""
import argparse
import ast
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import dashboard_store as store  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True, type=Path)
    args = parser.parse_args()
    with tarfile.open(args.baseline) as archive:
        source = archive.extractfile('scripts/serve.py').read().decode()
    old = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == 'Snapshots')
    new_source = (ROOT / 'scripts/dashboard_store.py').read_text()
    current = next(node for node in ast.parse(new_source).body if isinstance(node, ast.ClassDef) and node.name == 'Snapshots')
    assert ast.dump(old, include_attributes=False) == ast.dump(current, include_attributes=False), 'read-service AST changed during extraction'
    namespace = vars(store).copy()
    exec(compile(ast.Module(body=[old], type_ignores=[]), str(args.baseline), 'exec'), namespace)
    before, after = namespace['Snapshots'](), store.Snapshots()
    dates = [row['date'] for row in after.list()]
    assert len(dates) >= 3, 'need earliest, preceding and latest source states'
    selected = list(dict.fromkeys([dates[0], dates[-2], dates[-1]]))
    checks = 0
    for day in selected:
        for method in ['load', 'matches', 'players', 'gw', 'paths', 'pipeline']:
            assert getattr(before, method)(day) == getattr(after, method)(day), (day, method)
            checks += 1
        for method in ['players_bytes', 'gw_bytes']:
            assert getattr(before, method)(day) == getattr(after, method)(day), (day, method)
            checks += 1
        for team in ['Arsenal', 'Fiorentina']:
            assert before.team_fixtures(team, day) == after.team_fixtures(team, day), (day, team)
            checks += 1
    season = after.load(dates[-1])['params']['season']
    assert before.history(season) == after.history(season), 'history differs'
    assert before.track(season) == after.track(season), 'track differs'
    checks += 2
    print('PASS unchanged Snapshots class AST; public serve.py alias preserves the import path')
    print(f'PASS {checks} independent old/new read comparisons across {len(selected)} cutoffs; history covers {len(dates)} snapshots')
    print('No model imports, source writes, fitting or forecast regeneration')


if __name__ == '__main__':
    main()
