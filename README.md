# MusSim

Football forecasts, match evidence and club/player analysis for the big-five leagues,
domestic cups and UEFA competitions. MusSim combines a laptop-run Python data/model pipeline
with a static, offline-capable dashboard for phones and computers.

- Personal project: https://github.com/MusaMoholo/MusSim
- PWA: https://musamoholo.github.io/MusSim/

The public repository contains source code and analysis/verification scripts. Collected provider
responses, datasets, generated forecasts, data bundles, machine configuration and local operation
logs are excluded. The hosted PWA contains only interface files; you supply its data by importing
your own bundle. There is no public football-data API or account requirement for browsing the PWA.

## Install the dashboard

On iPhone, open the PWA address in Safari, choose Share → Add to Home Screen, then open the
installed icon. Choose **Offline data & installation → Import data** and select a `.mussim.gz`
bundle from Files/iCloud Drive. Import inside the installed app: Safari and the installed app
may keep separate storage. Browsing works offline after app setup and a successful import.

The same PWA works on a laptop. Each device imports separately. Imported data stays on the device;
keep the source bundle as a backup because browser storage can be cleared. Charts and wide tables
scroll inside their panels. Touch marks show values on the first tap and their linked action on
the second. Live forecasts and Scenario Lab computations remain laptop/Python operations.

## Laptop setup

Use Python3.12 or newer and a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

NumPy and pandas are the numerical dependencies. Node is optional for browser/render checks and
is not needed to run the dashboard. Bring your own retained source data under `data/`; the full
forecast pipeline and data-dependent tests require those inputs. A fresh source clone can build
the static app shell without any datasets or numerical packages.

To run the Python dashboard against retained snapshots:

```sh
.venv/bin/python scripts/serve.py
```

Open `http://127.0.0.1:8765`. Normal snapshot browsing does not fit or simulate the model.

## Nightly → iCloud → PWA

On a Mac with iCloud Drive enabled, run:

```sh
.venv/bin/python scripts/nightly_mussim.py
```

This runs the normal nightly pipeline and, after success, exports a complete browsing bundle to
**iCloud Drive/MusSim/MusSim.mussim.gz**. macOS syncs the file to your other devices. Choose that
file using **Import data** in each PWA. There is no separate manual export/copy step, and no
scheduler is installed by this command. Usual nightly options can follow the command;
`--output` optionally chooses another export destination. Failed/dry runs preserve the last export.

To export existing retained data without running collection or simulation:

```sh
.venv/bin/python scripts/export_mussim.py --output "$HOME/Library/Mobile Documents/com~apple~CloudDocs/MusSim/MusSim.mussim.gz"
```

Exports retain source revisions and historical availability. They stage and verify the complete
bundle before replacement. Previous exports are archived under `~/Football_archive_ops/`.
The laptop retains working inputs for subsequent collection/model runs.

## Build and publish the static PWA

```sh
.venv/bin/python scripts/export_mussim.py --shell _site --base-path /MusSim/
```

Serve `_site` at `/MusSim/`, or build with `--base-path /` for hosting at a domain root. The build
contains HTML, native JavaScript modules, icons, the web manifest and a service worker. Never put
datasets or `.mussim.gz` bundles in the deployment directory.

The GitHub Pages workflow builds only this app shell and deploys it from `main`. Data updates go
through iCloud imports; app-code updates go through GitHub Pages. No ChatGPT/work account is used
by the deployed dashboard.

## Code map

| Location | Responsibility |
|---|---|
| `scripts/webapp/` | Dashboard, charts, routes, mobile controls and PWA runtime |
| `scripts/dashboard_store.py` and evidence modules | Model-free retained-data services |
| `scripts/export_mussim.py` | Static shell and portable data export |
| `scripts/nightly.py`, `scripts/nightly_mussim.py` | Collection/model orchestration and iCloud export |
| `scripts/projection.py`, `scripts/simulate_season.py` | Forecast worlds and aggregation |
| `scripts/attack_defence_qt.py` | Chance-based strength model |
| `analysis/` | Research, independent audits and browser acceptance scripts |
| `football_common.py` | Shared input handling and team identities |

## Verification

With the required retained inputs available:

```sh
.venv/bin/python scripts/smoke.py
.venv/bin/python scripts/uefa_bracket.py
.venv/bin/python scripts/cup_bracket.py
```

Mobile/offline acceptance includes narrow phones, landscape, both themes, touch interactions,
complete bundle import and checksum/truncation recovery. The renderer and both bracket suites
pass on the retained acceptance inputs. Full smoke currently stops at a pre-existing Scenario Lab
lifecycle catalogue assertion. Historical invalid probabilities remain explicit; no automatic
clamping or historical repair is performed. Retrospective evaluation does not establish a
prospective published track record. Real iPhone installation/storage still requires a device check.
