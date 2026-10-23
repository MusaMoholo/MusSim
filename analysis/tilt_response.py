"""The fitted model's own response to ONE match -- the ratios the simulator's feedback is built on.

A world moves a side's state after every match. The size of those moves should be the estimator's
own (scaled by one factor calibrated against real season dispersion, `calibrate_drift3.py`), so
this measures, by appending one synthetic match to the training window and refitting:

    one-sided  : home npxG mu_h + D, away mu_a - D   -> Q-surprise (e_h - e_a) = 2D, T 0
    open game  : home npxG mu_h + D, away mu_a + D   -> T-surprise (e_h + e_a) = 2D, Q 0
    rating     : the side's prior rating raised by 20 Elo -> the prior's pass-through into Q

Surprises are ABSOLUTE, e = x - mu in npxG units, because that is what the estimator responds to
(the Poisson score is X'(y - mu)) and because it averages exactly zero under the simulator's
Gamma draw. The log ratio used before does not: E[log(x/mu)] = digamma(k) - log(k) < 0, and more
so for the side with the lower expectation, so every world drifted favourites up and underdogs
down -- Arsenal +0.17 Q and Burnley -0.13 over a re-simulated 2025, against a world-to-world SD of
0.20. Dispersion calibrated on that drift was partly measuring a bias.

    .venv/bin/python analysis/tilt_response.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.attack_defence_qt import NPXG_ELO_SLOPE, fit, predict_npxg  # noqa: E402
from scripts.backtest_qt import load_master  # noqa: E402

KW = dict(xi_q=np.log(2) / 140, xi_t=np.log(2) / 1460, lam_q=5.0, lam_t=40.0)
D = 0.4
DELO = 20.0


def main() -> int:
    m = load_master()
    cut = pd.Timestamp("2026-10-21")
    tr = m[m.kickoff < cut]
    base = fit(tr, cut, **KW)
    lg = tr[(tr.competition == "English Premier League") & (tr.season == 2026)]
    teams = sorted(t for t in set(lg.home) if t in base["Q"])
    rows = []
    for i, team in enumerate(teams):
        opp = teams[(i + 7) % len(teams)]
        proto = lg.iloc[[0]].copy()
        proto["home"], proto["away"] = team, opp
        proto["kickoff"] = cut - pd.Timedelta(hours=1)
        proto["home_elo"] = proto["away_elo"] = np.nan
        proto["minutes"] = 90.0
        mh, ma = predict_npxg(proto, base)
        for kind, (dh, da) in {"one-sided": (D, -D), "open": (D, D)}.items():
            row = proto.copy()
            row["home_npxg"] = mh[0] + dh
            row["away_npxg"] = max(ma[0] + da, 0.01)
            new = fit(pd.concat([tr, row], ignore_index=True), cut, **KW)
            rows.append({"team": team, "kind": kind,
                         "dQ_home": new["Q"][team] - base["Q"][team],
                         "dT_home": new["T"][team] - base["T"][team],
                         "dQ_away": new["Q"][opp] - base["Q"][opp],
                         "dT_away": new["T"][opp] - base["T"][opp]})
        # the prior's pass-through: this side's rating, as the window last saw it, plus DELO
        last = tr[(tr.home == team) | (tr.away == team)].iloc[-1]
        elo = last.home_elo if last.home == team else last.away_elo
        if np.isfinite(elo):
            new = fit(tr, cut, **KW, elo_now={team: float(elo) + DELO})
            rows.append({"team": team, "kind": "rating",
                         "dQ_home": new["Q"][team] - base["Q"][team],
                         "dT_home": new["T"][team] - base["T"][team]})
    r = pd.DataFrame(rows)
    g = r.groupby("kind")[["dQ_home", "dT_home", "dQ_away", "dT_away"]].mean()
    print(f"mean response, {len(teams)} EPL sides: npxG +-{D} per side, rating +{DELO:.0f} Elo\n")
    print(g.round(5).to_string())
    q_gain = g.loc["one-sided", "dQ_home"] / (2 * D)
    t_gain = g.loc["open", "dT_home"] / (2 * D)
    elo_to_q = NPXG_ELO_SLOPE / 200.0
    passthrough = g.loc["rating", "dQ_home"] / (elo_to_q * DELO)
    print(f"\nper unit of absolute npxG surprise: Q gain {q_gain:.4f}, T gain {t_gain:.4f}, "
          f"TILT_RATIO {t_gain / q_gain:.3f}")
    print(f"rating pass-through into Q: {passthrough:.3f} of ELO_TO_Q per Elo point")
    print(f"  -> per unit of result surprise (act - E[act]), K=19.58: "
          f"{passthrough * elo_to_q * 19.58:.4f} Q, RESULT_RATIO {passthrough * elo_to_q * 19.58 / q_gain:.3f}")
    print(f"cross-terms (should be ~0): open dQ_home {g.loc['open', 'dQ_home']:+.5f}, "
          f"one-sided dT_home {g.loc['one-sided', 'dT_home']:+.5f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
