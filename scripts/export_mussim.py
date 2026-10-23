#!/usr/bin/env python3
"""Export model-free MusSim browsing data and/or its data-free static PWA shell.

No collection, simulation, snapshot replacement or production writes. An export freezes
its read inputs first and publishes one complete gzip/NDJSON bundle atomically.
"""
from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.dashboard_store import Snapshots
from scripts.match_centre import MatchCentre, key as fixture_key
from scripts.time_machine import TimeMachine
from scripts.performance_studio import PerformanceStudio
from scripts.forecast_lab import ForecastLab
from scripts.explore_visuals import ExploreVisuals

WEB = ROOT / 'scripts/webapp'


def packed(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def context_projection(p):
    """Only the fields read by Match Centre's retained pre/post-match context adapter.

    Full projections remain separate /api/snapshot records for every browsing date.
    """
    out = {k: p.get(k) for k in ('params', 'as_of', 'model', 'version', 'source')}
    for category in ('leagues', 'uefa', 'cups'):
        out[category] = [{'competition': b['competition'], 'teams': [
            {k: v for k, v in t.items() if k == 'team' or k.startswith('p_')}
            for t in b['teams']]} for b in p.get(category, [])]
    ratings = p.get('ratings') or {}
    out['ratings'] = {'rel': ratings.get('rel'), 'teams': [
        {k: t.get(k) for k in ('team', 'elo', 'att', 'def')} for t in ratings.get('teams', [])]}
    return out


def context_rounds(gw):
    if gw is None:
        return None
    return {category: {comp: {k: block.get(k) for k in ('fixtures', 'stakes_of')}
                       for comp, block in gw.get(category, {}).items()}
            for category in ('leagues', 'phases')}


def portable_revision(value):
    """An export's evidence revision must not depend on its temporary read-copy path."""
    if isinstance(value, dict) and 'input_revision' in value and 'input_files' in value:
        return {**value, 'input_revision': hashlib.sha256(
            json.dumps(value['input_files'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
    return value


def build_shell(destination, archive_root=None, base_path='/'):
    """Create a clean deploy directory; never copy football data or repository secrets."""
    destination = Path(destination)
    base_path = '/' + base_path.strip('/') + '/' if base_path.strip('/') else '/'
    if not re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)*', base_path):
        raise ValueError('Base path must contain only simple URL directory names.')
    if destination.exists() and any(destination.iterdir()):
        from scripts.ops_storage import archive_paths
        archive, saved = archive_paths([destination], archive_root)
        # Directory archives receive the same complete-byte verification as file archives.
        for path in destination.rglob('*'):
            if path.is_file():
                assert path.read_bytes() == (saved[destination] / path.relative_to(destination)).read_bytes()
        print(f'Previous shell archived: {archive}', flush=True)
        shutil.rmtree(destination)
    (destination / 'assets').mkdir(parents=True, exist_ok=True)
    html = (WEB / 'index.html').read_text()
    assert html.count('\nboot();\n') == 1
    html = html.replace('\nboot();\n', '\n// Static boot is owned by pwa.mjs.\n')
    html = html.replace('</head>', f'<link rel="manifest" href="{base_path}manifest.webmanifest"><link rel="apple-touch-icon" href="{base_path}apple-touch-icon.png"><link rel="icon" href="{base_path}icon.svg"></head>')
    html = html.replace('</body>', '<script type="module">import {start} from "/assets/pwa.mjs"; await start(boot);</script>\n</body>')
    html = html.replace('/assets/', base_path + 'assets/').replace('/badges/', base_path + 'badges/')
    (destination / 'index.html').write_text(html)
    for path in WEB.glob('*.mjs'):
        if path.name != 'render_check.mjs':
            shutil.copy2(path, destination / 'assets' / path.name)
    for name in ('sw.js', 'manifest.webmanifest', 'icon.svg', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png'):
        shutil.copy2(WEB / name, destination / name)
    manifest = json.loads((destination / 'manifest.webmanifest').read_text())
    for key in ('id', 'start_url', 'scope'):
        manifest[key] = base_path
    for icon in manifest['icons']:
        icon['src'] = base_path + icon['src'].lstrip('/')
    (destination / 'manifest.webmanifest').write_text(json.dumps(manifest, indent=2) + '\n')
    (destination / '.nojekyll').touch()
    # A content-derived shell version invalidates caches on every real app change.
    version = hashlib.sha256(b''.join(p.read_bytes() for p in sorted(destination.rglob('*')) if p.is_file())).hexdigest()[:20]
    sw = destination / 'sw.js'
    sw.write_text(sw.read_text().replace('__SHELL_VERSION__', version))
    (destination / '_headers').write_text(f'{base_path}sw.js\n  Cache-Control: no-cache\n{base_path}manifest.webmanifest\n  Cache-Control: no-cache\n/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: no-referrer\n')
    print(f'Static shell: {destination} · version {version}', flush=True)


class FrozenSnapshots(Snapshots):
    """Bounded to one export; immutable reads avoid repeatedly decoding every projection."""
    def __init__(self, root, master):
        super().__init__(root, master)
        self.memo = {}

    def cached(self, name, day, read):
        day = day or self.list()[-1]['date']
        k = name, day
        if k not in self.memo:
            self.memo[k] = read(day)
        return self.memo[k]

    def load(self, day=None):
        return self.cached('projection', day, super().load)

    def matches(self, day=None):
        return self.cached('matches', day, super().matches)

    def gw(self, day=None):
        return self.cached('gw', day, super().gw)


def export_bundle(output, source, dates=None, archive_root=None):
    """Use a private source copy: never certify a mixture while nightly replaces files."""
    source = Path(source).resolve()
    output = Path(output).expanduser().resolve()
    if output.is_relative_to(source / 'data'):
        raise ValueError('Export destination must be outside production data.')
    if not output.name.endswith('.mussim.gz'):
        raise ValueError('Use a .mussim.gz export filename.')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        # Runtime replacements retain the prior complete file outside the repo.
        from scripts.ops_storage import archive_paths
        archive_paths([output], archive_root)
    with tempfile.TemporaryDirectory(prefix='mussim-export-') as tmp:
        frozen = Path(tmp)
        def inventory():
            files = [source / 'data/master_fixtures.csv']
            for rel in ('data/snapshots', 'data/fotmob/matches', 'data/badges'):
                if (source / rel).exists():
                    files.extend(p for p in (source / rel).rglob('*') if p.is_file())
            return {str(p.relative_to(source)): (p.stat().st_size, p.stat().st_mtime_ns) for p in files}
        before = inventory()
        for rel in ('data/snapshots', 'data/fotmob/matches', 'data/badges'):
            if (source / rel).exists():
                shutil.copytree(source / rel, frozen / rel)
        shutil.copy2(source / 'data/master_fixtures.csv', frozen / 'data/master_fixtures.csv')
        if before != inventory():
            raise ValueError('Data changed during the export copy. Retry after nightly finishes; the previous export is unchanged.')
        return write_bundle(output, frozen, dates)


def write_bundle(output, source, dates=None):
    snaps = FrozenSnapshots(source / 'data/snapshots', source / 'data/master_fixtures.csv')
    listed = snaps.list()
    if dates:
        if set(dates) - {r['date'] for r in listed}:
            raise ValueError('Requested snapshot is unavailable.')
        selected = [r for r in listed if r['date'] in dates]
    else:
        selected = listed
    if not selected:
        raise ValueError('No snapshots to export.')
    centre = MatchCentre(snaps, source / 'data/fotmob/matches')
    tm, performance, lab, explore = TimeMachine(snaps), PerformanceStudio(snaps), ForecastLab(snaps), ExploreVisuals(snaps)
    count, seen = 0, set()
    descriptor, staging = tempfile.mkstemp(prefix='.mussim-', suffix='.partial', dir=output.parent)
    os.close(descriptor)
    header = {'format': 'mussim', 'version': 1, 'created': datetime.now(timezone.utc).isoformat(),
              'latest': selected[-1]['date'], 'snapshots': [r['date'] for r in selected]}
    try:
        with gzip.open(staging, 'wt', encoding='utf-8', compresslevel=6) as stream:
            stream.write(packed(header) + '\n')

            def emit(key, value, status=200, content_type='application/json', binary=False):
                nonlocal count
                if key in seen:
                    raise ValueError('Duplicate export key: ' + key)
                seen.add(key)
                body = base64.b64encode(value).decode() if binary else packed(value)
                record = {'key': key, 'body': body, 'status': status, 'type': content_type, 'binary': binary,
                          'sha256': hashlib.sha256(body.encode()).hexdigest()}
                stream.write(packed(record) + '\n')
                count += 1

            def optional(key, value):
                emit(key, value if value is not None else {'error': 'This detail was not retained for this snapshot.'}, 200 if value is not None else 404)

            emit('/api/meta', {'defaults': {}, 'snapshots': selected, 'pipeline': snaps.pipeline(), 'model_loaded': False, 'static': True})
            emit('/material/index', listed)
            badges = source / 'data/badges'
            emit('/api/badges', json.loads((badges / 'index.json').read_text()) if (badges / 'index.json').exists() else {})
            for file in sorted(badges.glob('*.png')):
                if file.stem.isdigit():
                    emit('/badges/' + file.name, file.read_bytes(), content_type='image/png', binary=True)
            seasons = sorted({snaps.load(r['date'])['params']['season'] for r in listed})
            for season in seasons:
                emit(f'/api/history?season={season}', snaps.history(season))
                optional(f'/api/track?season={season}', snaps.track(season))
            # All historical projections/round ledgers remain available for arbitrary date pairs
            # and retained pre-match contexts, even in a selected-date browsing bundle.
            for row in listed:
                day = row['date']; projection = snaps.load(day)
                emit('/material/projection/' + day, context_projection(projection))
                optional('/material/matches/' + day, snaps.matches(day))
                optional('/material/gw/' + day, context_rounds(snaps.gw(day)))
                emit('/material/compact/' + day, tm._archive(day, projection['source']['projection_sha256'])[0][day])
            master = list(csv.DictReader(snaps.master_csv.open(encoding='utf-8-sig', newline='')))
            emit('/material/master', [{k: r.get(k) for k in ('season','played','tbd','competition','home','away','kickoff','home_goals','away_goals','home_xg','away_xg','outcome')} for r in master])
            emitted_facts = set()
            for i, row in enumerate(selected, 1):
                day = row['date']; p = snaps.load(day); revision = p['source']['projection_sha256']
                print(f'Export {i}/{len(selected)} · {day}', flush=True)
                for endpoint, value in [('snapshot', p), ('matches', snaps.matches(day)), ('gw', snaps.gw(day)),
                                        ('paths', snaps.paths(day)), ('players', snaps.players(day)), ('pipeline', snaps.pipeline(day))]:
                    optional(f'/api/{endpoint}?date={day}', value)
                agenda = centre.agenda(day)
                emit(f'/api/agenda?date={day}', agenda)
                for name, service in [('performance', lambda: performance.read(day, revision)),
                                      ('performance-all', lambda: performance.read(day, revision, all_competitions=True)),
                                      ('forecast-lab', lambda: lab.read(day, revision)),
                                      ('explore-visuals', lambda: explore.read(day, revision))]:
                    endpoint = 'performance' if name == 'performance-all' else name
                    key = f'/api/{endpoint}?date={day}' + ('&scope=all' if name == 'performance-all' else '')
                    try:
                        emit(key, portable_revision(service()))
                    except ValueError as error:
                        emit(key, {'error': str(error)}, getattr(error, 'status', 409))
                facts = {}
                for f in agenda['fixtures']:
                    if not f.get('result') or f['kickoff'][:10] > agenda['as_of']:
                        continue
                    value = centre.retained_facts(agenda, f)
                    digest = hashlib.sha256(packed(value).encode()).hexdigest()
                    if digest not in emitted_facts:
                        emit('/material/facts/' + digest, value); emitted_facts.add(digest)
                    facts[fixture_key(f)] = digest
                emit('/material/fact-index/' + day, facts)
                teams = sorted({f[s] for f in agenda['fixtures'] for s in ('home','away')})
                for team in teams:
                    # URLSearchParams-compatible canonical keys are also used by the browser.
                    from urllib.parse import urlencode
                    optional('/api/team-fixtures?' + urlencode({'date': day, 'team': team}), snaps.team_fixtures(team, day))
            stream.write(packed({'end': True, 'records': count}) + '\n')
        # Validate the complete gzip and record checksums before publication.
        with gzip.open(staging, 'rt', encoding='utf-8') as check:
            assert json.loads(next(check)) == header
            actual = 0
            for line in check:
                item = json.loads(line)
                if item.get('end'):
                    assert item['records'] == actual == count
                else:
                    assert hashlib.sha256(item['body'].encode()).hexdigest() == item['sha256']; actual += 1
        os.replace(staging, output)
        print(f'Bundle: {output} · {count:,} records · {output.stat().st_size / 1e6:.1f} MB', flush=True)
        return header
    finally:
        Path(staging).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shell', type=Path, help='Build data-free PWA into a new/empty directory')
    parser.add_argument('--base-path', default='/', help='Hosting directory, e.g. /MusSim/ for GitHub Pages')
    parser.add_argument('--output', type=Path, help='Write .mussim.gz data bundle; iCloud Drive is supported')
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--archive-root', type=Path, help='Override archive root (tests/review only)')
    parser.add_argument('--date', action='append', help='Limit browsing dates; all history remains available')
    args = parser.parse_args()
    if not args.shell and not args.output:
        parser.error('Provide --shell and/or --output')
    if args.shell:
        build_shell(args.shell, args.archive_root, args.base_path)
    if args.output:
        export_bundle(args.output, args.source, args.date, args.archive_root)


if __name__ == '__main__':
    main()
