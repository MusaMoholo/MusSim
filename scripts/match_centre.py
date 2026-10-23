"""Cutoff-gated, cache-only match evidence. No model, network, fitting or source writes."""
from __future__ import annotations
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 1
PERIODS = {'FirstHalf': 1, 'SecondHalf': 2, 'FirstHalfExtra': 3, 'SecondHalfExtra': 4}


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def flag(value):
    return str(value).lower() in {'true', '1', 'yes'}


def key(f):
    return '|'.join([f['competition'], f['home'], f['away'], str(f['kickoff'])[:10]])


def clock(raw, shot=False):
    minute = number(raw.get('min' if shot else 'time'))
    added = number(raw.get('minAdded' if shot else 'overloadTime')) or 0
    if minute is None or not minute.is_integer() or not 0 <= minute <= 120 or not 0 <= added < 100:
        return None
    minute, added = int(minute), int(added)
    period = raw.get('period') or ('FirstHalf' if minute <= 45 else 'SecondHalf' if minute <= 90 else 'FirstHalfExtra' if minute <= 105 else 'SecondHalfExtra')
    if period not in PERIODS:
        return None
    # Phase-end markers follow added-time events, without pretending to know seconds.
    sort_added = 999 if not shot and raw.get('type') == 'Half' else added
    return {'minute': minute, 'added': added, 'period': period,
            'order': minute * 1000 + sort_added, 'label': str(minute) + (f'+{added}' if added else '')}


def identity(raw, kind):
    explicit = raw.get('id' if kind == 'shot' else 'eventId')
    if explicit not in (None, '', 0):
        return f'{kind}:{explicit}'
    return kind + ':' + str(raw.get('reactKey') or hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()[:24])


def normalise(fixture, detail):
    """Pure normalizer. Caller must establish completion/cutoff before reading the cache."""
    content, general = detail.get('content') or {}, detail.get('general') or {}
    ids = {str((general.get(s + 'Team') or {}).get('id')): s for s in ('home', 'away')}
    raw_events = ((content.get('matchFacts') or {}).get('events') or {}).get('events')
    raw_shots = (content.get('shotmap') or {}).get('shots')
    events, shots, shootout, issues = [], [], [], []
    counts = {'raw_events': len(raw_events or []), 'raw_shots': len(raw_shots or []), 'duplicate_events': 0,
              'duplicate_shots': 0, 'excluded_shootout_events': 0, 'excluded_shootout_shots': 0,
              'unusable_events': 0, 'unusable_shots': 0}
    for kind, raw_rows, output in [('event', raw_events, events), ('shot', raw_shots, shots)]:
        seen = {}
        for raw in raw_rows if isinstance(raw_rows, list) else []:
            if not isinstance(raw, dict):
                counts['unusable_' + kind + 's'] += 1
                continue
            rid = identity(raw, kind)
            if rid in seen:
                counts['duplicate_' + kind + 's'] += 1
                if seen[rid] != raw:
                    issues.append('Conflicting duplicate ' + rid)
                continue
            seen[rid] = raw
            if raw.get('period') == 'PenaltyShootout' or raw.get('isPenaltyShootoutEvent') or raw.get('type') == 'PenaltyShootout':
                counts['excluded_shootout_' + kind + 's'] += 1
                shootout.append({'id': rid, 'kind': kind})
                continue
            time = clock(raw, kind == 'shot')
            side = ids.get(str(raw.get('teamId'))) if kind == 'shot' else 'home' if raw.get('isHome') is True else 'away' if raw.get('isHome') is False else None
            if time is None or kind == 'shot' and side is None:
                counts['unusable_' + kind + 's'] += 1
                continue
            if kind == 'shot':
                x, y, xg = number(raw.get('x')), number(raw.get('y')), number(raw.get('expectedGoals'))
                if x is None or y is None or not 0 <= x <= 105 or not 0 <= y <= 68:
                    x, y = None, None
                if xg is not None and not 0 <= xg <= 1:
                    issues.append('Invalid shot xG ' + rid);xg = None
                output.append({'id': rid, **time, 'side': side, 'player_id': str(raw.get('playerId') or ''),
                               'player': raw.get('playerName') or 'Unknown player', 'x': x, 'y': y,
                               'xg': xg, 'goal': raw.get('eventType') == 'Goal', 'own_goal': bool(raw.get('isOwnGoal')),
                               'outcome': raw.get('eventType'), 'situation': raw.get('situation')})
            else:
                player = raw.get('player') or {}
                output.append({'id': rid, **time, 'side': side, 'type': str(raw.get('type') or 'Event'),
                               'player_id': str(player.get('id') or raw.get('playerId') or ''),
                               'player': player.get('name') or raw.get('nameStr') or '',
                               'own_goal': bool(raw.get('ownGoal')), 'card': raw.get('card'),
                               'assist': {'id': str(raw.get('assistPlayerId') or ''), 'name': raw.get('assistInput') or ''}
                               if raw.get('type') == 'Goal' and not raw.get('ownGoal') and raw.get('assistPlayerId') and raw.get('assistInput') else None,
                               'swap': [{'id': str(p.get('id') or ''), 'name': p.get('name') or ''} for p in raw.get('swap') or []],
                               'text': raw.get('halfStrShort') or raw.get('minutesAddedStr') or ' · '.join(((raw.get('VAR') or {}).get('decision') or {}).get('value') or []),
                               'shot_id': 'shot:' + str((raw.get('shotmapEvent') or {}).get('id')) if raw.get('shotmapEvent') else None})
    for rows in [events, shots]:
        rows.sort(key=lambda r: (r['order'], r['id']))
    goals = {s: sum(e['type'] == 'Goal' and e['side'] == s for e in events) for s in ['home', 'away']}
    goal_ok = [goals['home'], goals['away']] == fixture.get('result') if isinstance(raw_events, list) else None
    if goal_ok is False:
        issues.append('Goal events do not reconcile to the recorded score')
    shot_goals = {s: sum(sh['goal'] and (('away' if sh['side'] == 'home' else 'home') if sh['own_goal'] else sh['side']) == s for sh in shots) for s in ['home', 'away']}
    summaries = {}
    for side in ['home', 'away']:
        attempts = [sh for sh in shots if sh['side'] == side and not sh['own_goal']]
        summaries[side] = {'attempts': len(attempts), 'shot_xg': sum(sh['xg'] for sh in attempts if sh['xg'] is not None),
                           'unknown_xg': sum(sh['xg'] is None for sh in attempts), 'goals_from_shots': shot_goals[side]}
    players = []
    for pid, row in (content.get('playerStats') or {}).items():
        side = ids.get(str(row.get('teamId')))
        if side is None:
            continue
        values = {}
        for group in row.get('stats') or []:
            entries = group.get('stats') or {}
            for stat in entries.values() if isinstance(entries, dict) else entries:
                if isinstance(stat, dict):
                    values[stat.get('key')] = number((stat.get('stat') or {}).get('value'))
        players.append({'id': str(pid), 'name': row.get('name') or '', 'side': side,
                        'goals': sum(sh['goal'] and not sh['own_goal'] and sh['player_id'] == str(pid) for sh in shots) if raw_shots else values.get('goals'),
                        **{key: values.get(source) for key, source in [('minutes', 'minutes_played'), ('xg', 'expected_goals'), ('assists', 'assists'), ('xa', 'expected_assists'), ('shots', 'total_shots')]}})
    lineup = content.get('lineup') or {}
    formations = {}
    for side in ['home', 'away']:
        team = lineup.get(side + 'Team') or {};formations[side] = team.get('formation')
        for group in ['starters', 'subs']:
            for p in team.get(group) or []:
                existing = next((r for r in players if r['id'] == str(p.get('id'))), None)
                if existing is None:
                    existing = {'id': str(p.get('id') or ''), 'name': p.get('name') or '', 'side': side,
                                'minutes': None, 'xg': None, 'assists': None, 'xa': None, 'shots': None, 'goals': None};players.append(existing)
                existing['starter'] = group == 'starters'
    status = (detail.get('header') or {}).get('status') or {};pens = (status.get('reason') or {}).get('penalties')
    provider_kickoff = general.get('matchTimeUTCDate') or status.get('utcTime')
    return {'events': events, 'shots': shots, 'shootout_excluded': shootout, 'players': players,
            'formations': formations, 'shootout_score': pens if isinstance(pens, list) and len(pens) == 2 else None,
            'coverage': {**counts, 'timeline': isinstance(raw_events, list), 'shotmap': isinstance(raw_shots, list) and bool(raw_shots),
                         'lineup': bool(lineup), 'players': bool(players), 'goals_reconcile': goal_ok,
                         'shot_goals_reconcile': [shot_goals['home'], shot_goals['away']] == fixture.get('result') if raw_shots else None},
            'summary': summaries, 'issues': issues, 'provider_kickoff': provider_kickoff,
            'revised_source_notice': 'Retained finished-match response; original retrieval time/revisions unavailable.'}


class MatchCentre:
    def __init__(self, snapshots, cache_root=None):
        self.snaps = snapshots
        self.cache_root = Path(cache_root) if cache_root is not None else ROOT / 'data/fotmob/matches'
        self._master_key = None;self._master_rows = [];self._agenda_cache = {};self._facts_cache = {}

    def master(self):
        path = self.snaps.master_csv;stat = path.stat();key0 = (stat.st_mtime_ns, stat.st_size)
        if key0 != self._master_key:
            with path.open(newline='', encoding='utf-8-sig') as f:self._master_rows = list(csv.DictReader(f))
            self._master_key = key0;self._agenda_cache = {}
        return self._master_rows

    def agenda(self, day):
        if day not in {r['date'] for r in self.snaps.list()}:
            return None
        result = self.snaps.load(day)
        rows = self.master();revisions = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in (self.snaps.root / day).iterdir() if p.name in {'matches.json','gw.json','gw.json.gz'})
        cache_key = (day, result['source']['projection_sha256'], self._master_key, revisions)
        # A cached agenda belongs to a forecast revision; detail file revisions are inspected on demand.
        if cache_key in self._agenda_cache:return self._agenda_cache[cache_key]
        season, cutoff = result['params']['season'], result['as_of'];merged = {}
        gw = self.snaps.gw(day) or {}
        for collection in ['leagues', 'phases']:
            for comp, block in gw.get(collection, {}).items():
                for f in block.get('fixtures', []):
                    if f.get('result') and f['kickoff'][:10] > cutoff:continue
                    merged[key({**f, 'competition': comp})] = {**f, 'competition': comp, 'stakes_of': block.get('stakes_of', [])}
        for f in (self.snaps.matches(day) or {}).get('fixtures', []):
            if number(f.get('p_occurs')) is not None and float(f['p_occurs']) < 1:continue
            k = key(f)
            if k not in merged:merged[k] = dict(f)
        eligible = [r for r in rows if str(r['season']) == str(season) and flag(r.get('played')) and not flag(r.get('tbd')) and r['kickoff'][:10] <= cutoff]
        for r in eligible:
            score = [number(r.get(s + '_goals')) for s in ['home', 'away']]
            if any(v is None or v < 0 or not v.is_integer() for v in score):continue
            k = key(r);entry = merged.setdefault(k, {field: r.get(field) for field in ['competition', 'home', 'away', 'kickoff', 'kind']})
            if entry.get('result') is None:entry['result'] = [int(v) for v in score]
            entry['outcome'] = r.get('outcome') or entry.get('outcome')
            entry['match_id'] = str(int(float(r['match_id']))) if number(r.get('match_id')) is not None else None
            entry['minutes'] = number(r.get('minutes'))
        fixtures = []
        for k, f in merged.items():
            f = dict(f);f['id'] = k
            probability = number(f.get('p_occurs'))
            if probability is not None and probability < 1:continue
            if f.get('result') and f['kickoff'][:10] > cutoff:continue
            fixtures.append(f)
        fixtures.sort(key=lambda f: (f['kickoff'], f['competition'], f['home'], f['away']))
        out = {'schema': SCHEMA, 'season': season, 'as_of': cutoff, 'snapshot': day, 'source': result['source'], 'fixtures': fixtures}
        self._agenda_cache = {cache_key: out}
        return out

    def forecast_context(self, day, fixture):
        match_day = fixture['kickoff'][:10]
        played = bool(fixture.get('result'));before = None;after = None
        season = self.snaps.load(day)['params']['season']
        for row in reversed(self.snaps.list()):
            if row['date'] > day:continue
            p = self.snaps.load(row['date'])
            if p['params']['season'] != season:continue
            if p.get('as_of', '') >= match_day:continue
            if not played and row['date'] != day:continue
            candidates = (self.snaps.matches(row['date']) or {}).get('fixtures', [])
            gw = None
            found = next((f for f in candidates if key(f) == key(fixture) and f.get('ladder')), None)
            keys = found.get('stakes_of') if found else None
            if found is None or keys is None:
                gw = self.snaps.gw(row['date']) or {}
                for category in ['leagues', 'phases']:
                    block = gw.get(category, {}).get(fixture['competition'], {})
                    other = next((f for f in block.get('fixtures', []) if key({**f, 'competition': fixture['competition']}) == key(fixture) and f.get('ladder')), None)
                    if other:
                        if found is None:found = {**other, 'competition': fixture['competition']}
                        keys = keys or block.get('stakes_of');break
            if found:
                before = {'snapshot': row['date'], 'as_of': p['as_of'], 'model': p.get('model'),
                          'fixture': found, 'keys': keys or [], 'payload': p.get('version', 1), 'projection': p};break
        if played and before:
            for row in self.snaps.list():
                if row['date'] > day:continue
                p = self.snaps.load(row['date'])
                if p['params']['season'] == before['projection']['params']['season'] and p.get('as_of', '') >= match_day:
                    after = {'snapshot': row['date'], 'as_of': p['as_of'], 'model': p.get('model'), 'projection': p};break
        if before:
            p = before['projection'];known = before['as_of'];context = {}
            ratings = p.get('ratings') or {};factor = ((ratings.get('rel') or {}).get(fixture['competition']) or {}).get('now')
            gw = self.snaps.gw(before['snapshot']) or {};schedule = []
            for category in ['leagues','phases']:
                for comp, block in gw.get(category, {}).items():
                    schedule += [{**f, 'competition': comp} for f in block.get('fixtures', []) if not f.get('result')]
            schedule += (self.snaps.matches(before['snapshot']) or {}).get('fixtures', [])
            for team in [fixture['home'],fixture['away']]:
                past = [r for r in self.master() if str(r.get('season')) == str(season) and flag(r.get('played')) and not flag(r.get('tbd')) and team in [r.get('home'),r.get('away')] and r['kickoff'][:10] <= known and r['kickoff'][:10] < match_day]
                past.sort(key=lambda r:(r['kickoff'],r['competition'],r['home'],r['away']),reverse=True)
                rating = next((r for r in ratings.get('teams',[]) if r['team']==team),None)
                strength = None if rating is None else {'elo':rating.get('elo'), 'att':rating.get('att')*factor[0] if factor and rating.get('att') is not None else None, 'def':rating.get('def')*factor[1] if factor and rating.get('def') is not None else None}
                following = {key(f):f for f in schedule if team in [f.get('home'),f.get('away')] and f['kickoff'] > fixture['kickoff'] and not f.get('result') and (number(f.get('p_occurs')) is None or number(f.get('p_occurs'))==1)}
                context[team] = {'rating':strength,'form':[{field:r.get(field) for field in ['competition','home','away','kickoff','home_goals','away_goals','home_xg','away_xg','outcome']} for r in past[:5]],'next':[{field:f.get(field) for field in ['competition','home','away','kickoff']} for f in sorted(following.values(),key=lambda f:(f['kickoff'],f['competition'],f['home'],f['away']))[:3]]}
            before['context'] = context
        bridge = []
        if before and after:
            for team in [fixture['home'], fixture['away']]:
                def values(p):
                    block = next((b for b in p.get('leagues', []) + p.get('uefa', []) + p.get('cups', []) if b['competition'] == fixture['competition']), {})
                    return next((t for t in block.get('teams', []) if t['team'] == team), {})
                one, two = values(before['projection']), values(after['projection'])
                for metric in ['p_win', 'p_ucl', 'p_uel', 'p_uecl', 'p_releg', 'p_top8']:
                    first, last = number(one.get(metric)), number(two.get(metric))
                    if first is not None and last is not None and 0 <= first <= 1 and 0 <= last <= 1:
                        bridge.append({'team': team, 'metric': metric, 'before': first, 'after': last, 'delta': last-first})
        for item in [before, after]:
            if item:item.pop('projection', None)
        return before, {'before': {k:v for k,v in before.items() if k != 'fixture'} if before else None,
                        'after': after, 'rows': bridge}

    def detail(self, day, competition, home, away, match_day):
        agenda = self.agenda(day)
        if agenda is None:return None
        fixture = next((f for f in agenda['fixtures'] if key(f) == '|'.join([competition, home, away, match_day])), None)
        if fixture is None:return None
        out = {'schema': SCHEMA, 'snapshot': day, 'as_of': agenda['as_of'], 'season': agenda['season'],
               'fixture': fixture, 'source': agenda['source'], 'facts': None, 'mode': 'preview'}
        out['pre_match'], out['forecast_change'] = self.forecast_context(day, fixture)
        # This guard precedes cache access: future cache contents cannot enter an old preview.
        if not fixture.get('result') or fixture['kickoff'][:10] > agenda['as_of']:
            return out
        out['mode'] = 'played'
        out.update(self.retained_facts(agenda, fixture))
        return out

    def retained_facts(self, agenda, fixture):
        # Shared by Match Centre and Atlas; no forecast-context/history reads for spatial data.
        out = {'facts': None}
        if not fixture.get('result') or fixture['kickoff'][:10] > agenda['as_of']:
            return out
        mid = str(fixture.get('match_id') or '')
        if not mid.isdigit():out['unavailable'] = 'No provider identity for this played fixture.';return out
        for suffix in ['.json.gz', '.json']:
            path = self.cache_root / (mid + suffix)
            if not path.is_file():continue
            raw = path.read_bytes()
            try:
                detail = json.loads(gzip.decompress(raw) if suffix.endswith('gz') else raw)
            except (ValueError, OSError, EOFError):
                out['unavailable'] = 'Retained provider response could not be read.';return out
            general = detail.get('general') or {}
            if str(general.get('matchId')) != mid:
                out['unavailable'] = 'Provider identity does not match this fixture.';return out
            provider_time = general.get('matchTimeUTCDate') or ((detail.get('header') or {}).get('status') or {}).get('utcTime')
            if provider_time and str(provider_time)[:10] > agenda['as_of']:
                out['unavailable'] = 'Provider kickoff is after this cutoff; later facts are withheld.';return out
            if general.get('finished') is False:
                out['unavailable'] = 'Retained provider response is unfinished.';return out
            digest = hashlib.sha256(raw).hexdigest();cache_key = (mid, digest, tuple(fixture['result']), SCHEMA)
            if cache_key not in self._facts_cache:
                if len(self._facts_cache) >= 64:self._facts_cache.clear()
                self._facts_cache[cache_key] = normalise(fixture, detail)
            out['facts'] = self._facts_cache[cache_key]
            out['evidence'] = {'provider_id': mid, 'sha256': digest, 'schema': SCHEMA}
            return out
        out['unavailable'] = 'No retained provider response for this fixture.'
        return out


    def atlas(self, day, team):
        agenda = self.agenda(day)
        if agenda is None or not team or len(team) > 200:
            return None
        members = {f[s] for f in agenda['fixtures'] for s in ['home', 'away']}
        if team not in members:
            return None
        matches = []
        for fixture in agenda['fixtures']:
            if team not in [fixture['home'], fixture['away']] or not fixture.get('result') or fixture['kickoff'][:10] > agenda['as_of']:
                continue
            retained = self.retained_facts(agenda, fixture)
            facts = retained.get('facts')
            matches.append({'fixture': fixture, 'shots': facts['shots'] if facts else [],
                            'coverage': facts['coverage'] if facts else None,
                            'evidence': retained.get('evidence'), 'unavailable': retained.get('unavailable')})
        return {'schema': 1, 'normalizer': SCHEMA, 'snapshot': day, 'as_of': agenda['as_of'],
                'season': agenda['season'], 'source': agenda['source'], 'team': team, 'matches': matches}
