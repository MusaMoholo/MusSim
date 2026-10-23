#!/usr/bin/env python3
"""Owner-run nightly followed by a read-only MusSim export, only on success.

Defaults to iCloud Drive/MusSim/MusSim.mussim.gz. Remaining arguments go to nightly.py.
This wrapper never runs automatically and never changes scheduling or a running service.
"""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
ICLOUD_DRIVE = Path.home() / 'Library/Mobile Documents/com~apple~CloudDocs'
DEFAULT_OUTPUT = ICLOUD_DRIVE / 'MusSim/MusSim.mussim.gz'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT,
                        help='Optional override; default: iCloud Drive/MusSim/MusSim.mussim.gz')
    args, nightly_args = parser.parse_known_args()
    if '--backfill' in nightly_args or '--refresh-players' in nightly_args:
        parser.error('Run historical repairs/refreshes separately; this wrapper is for normal nightly.')
    if args.output == DEFAULT_OUTPUT and not ICLOUD_DRIVE.is_dir():
        parser.error('Enable iCloud Drive on this Mac before running MusSim nightly.')
    status = subprocess.run([sys.executable, str(ROOT / 'scripts/nightly.py'), *nightly_args], cwd=ROOT).returncode
    if status:
        print('Nightly did not succeed; the previous MusSim export is unchanged.', file=sys.stderr)
        return status
    if '--dry-run' in nightly_args:
        print('Dry run: no MusSim export written.')
        return 0
    print('Nightly succeeded. Exporting MusSim to ' + str(args.output.expanduser()), flush=True)
    return subprocess.run([sys.executable, str(ROOT / 'scripts/export_mussim.py'), '--output', str(args.output.expanduser())], cwd=ROOT).returncode


if __name__ == '__main__':
    raise SystemExit(main())
