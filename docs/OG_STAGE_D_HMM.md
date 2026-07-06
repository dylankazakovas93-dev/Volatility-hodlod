# OG Stage D — HMM regime gate candidates (build years only)

Scope: `OG_BUILD_YEARS` only = {2018, 2020, 2023, 2026-partial}. Carries
forward Stage B (`sal_enabled=False`) and Stage C (`be_bars=60`,
`be_extra_lock=0.0`). No metric below includes 2019/2021/2022/2024/2025
trade outcomes.

## Method

`src/og_hmm_gate.py` builds a 2-state Gaussian HMM regime series on 60-minute
log returns:
- Walk-forward annual refit: the model used to classify year Y is fit only on
  60-min returns from years strictly before Y (2018 has no prior data, so no
  gate applies in 2018 — it is treated as "unknown regime, do not block").
- Causal per-bar decoding: a manual forward-algorithm (alpha-recursion) filter
  is used instead of hmmlearn's default Viterbi/posterior decode, so each
  bar's regime label uses only that bar and earlier bars, never future bars.
- This HMM fitting/feature construction uses the full historical bar stream
  (rolling, causal, lagged) per the task's data-firewall rule that causal
  feature construction may use all prior chronological data; no strategy
  OUTCOME metric was computed on non-build years anywhere in this process —
  only price-return statistics were used to fit the HMM.

Three candidates tested (`scripts/og_stage_d_hmm.py`):
- `no_hmm` — no regime gate (baseline, carrying Stage B/C freeze forward)
- `hmm_state0` — only allow entries when the causally filtered regime is state 0
- `hmm_state1` — only allow entries when the causally filtered regime is state 1

## Build-year aggregate results

| Candidate | n | net_pts | PF | win_rate | avg_trade | max_drawdown |
|---|---|---|---|---|---|---|
| no_hmm | 500 | 4372.34 | 1.4548 | 0.4100 | 8.745 | -793.77 |
| hmm_state0 | 438 | 1739.25 | 1.2233 | 0.4018 | 3.971 | -1197.64 |
| hmm_state1 | 212 | 2941.12 | 1.8283 | 0.4151 | 13.873 | -563.99 |

## hmm_state1 per-build-year breakdown (best PF candidate)

| Year | n | net_pts | PF | max_drawdown |
|---|---|---|---|---|
| 2018 | 140 | 103.61 | 1.0709 | -317.36 |
| 2020 | 34 | 2141.90 | 3.4142 | -221.12 |
| 2023 | 18 | -344.43 | 0.3708 | -426.82 |
| 2026 (partial) | 20 | 1040.04 | 2.5885 | -338.75 |

## Selection rationale

`hmm_state1` has the best aggregate PF (1.8283) but this is not robust
evidence of a real edge:
- Trade count collapses in three of four build years (2020: 34, 2023: 18,
  2026: 20, vs. ~140-150 under no_hmm) — the gate is filtering out most of
  the sample, and small-n years are noisy.
- 2023 is clearly net-negative under this gate (-344.43, PF 0.37, 0 TP out of
  18 trades) — a build year the ungated candidate keeps positive.
- The entire aggregate PF advantage is driven almost entirely by 2020's 34
  trades (net_pts 2141.90 of the candidate's total 2941.12) — a single-year,
  small-sample effect, not a broad-based improvement.

`hmm_state0` is dominated outright: lower net_pts, lower PF, and a
substantially worse aggregate max drawdown (-1197.64) than the ungated
baseline.

`no_hmm` (the Stage C-frozen configuration with no additional gate) has the
highest net_pts, the most trades, and (per Stage C) all 4 build years
positive. Neither HMM candidate clears the bar of "clearly helps and is
robust across build years" — per the task's explicit instruction that
"no-HMM" is a legitimate frozen choice when an HMM gate does not earn its
keep, that is the decision here.

**Frozen decision: no-HMM** (no regime gate added to the pipeline).

Raw outputs: `outputs/og_build_years/stage_d_regime_series.csv`,
`outputs/og_build_years/stage_d_*_build_years_trades.csv`,
`outputs/og_build_years/stage_d_hmm_results.json`.
