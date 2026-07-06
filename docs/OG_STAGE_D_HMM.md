# OG Stage D — HMM regime gate candidates (build years only)

**Status: COMPLETE. Final decision: no-HMM.**

Scope: `OG_BUILD_YEARS` only = {2018, 2020, 2023, 2026-partial}. Carries
forward Stage B (`sal_enabled=False`) and Stage C (`be_bars=60`,
`be_extra_lock=0.0`). Held constant for this stage: canonical 11:00-15:00 ET
entry restriction (isolating the HMM-gate variable, not yet Stage E's
`RESEARCH_ENTRY_BLACKOUT_10_16`), `PROP_HARD_BLACKOUT` (16:00-19:00 ET,
unconditional). No metric below includes 2019/2021/2022/2024/2025 trade
outcomes.

## Method (rebuilt from the original diagnostic-only version)

`src/og_hmm_gate.py` implements a genuinely causal, session-refit HMM:
- **Features** (all causal): 5-minute log return, trailing 30-minute
  realized volatility, trailing 30-minute cumulative return/trend.
- **Fitting**: refit once per session, training on the trailing 20-120
  completed sessions (never including the session being classified);
  standardization uses training-window statistics only.
- **Decoding**: a manual forward-algorithm (alpha-recursion) causal filter —
  never smoothing (forward-backward) or Viterbi full-path decoding, both of
  which would leak future-bar information into a given bar's regime label.
- **State labeling**: states ordered by fitted volatility (ascending) at
  every refit, so LOW/MID/HIGH are comparable labels across refits despite
  arbitrary internal state indexing from the EM fit.
- **Causality proof**: `tests/test_og_hmm_causality.py` asserts filtered
  probabilities for bar N are unchanged when future bars N+1, N+2, ... are
  appended after the fact. Passes.
- Feature construction uses the full historical bar stream (rolling,
  causal, lagged), permitted per the data-firewall rule that causal
  indicator construction may use all prior chronological data; no strategy
  OUTCOME metric was computed for non-build years anywhere in this process.

## Full candidate matrix (primary: window=120 sessions, seed=42)

`scripts/og_stage_d_hmm_full.py`. All results build-years-only.

| Candidate | n | net_pts | PF | PF ex-2026 | n ex-2026 |
|---|---|---|---|---|---|
| hmm2_LOW_only_p55 | 236 | 1015.62 | 1.3105 | 1.1318 | 207 |
| hmm2_LOW_only_p65 | 235 | 962.00 | 1.2941 | 1.1118 | 206 |
| hmm2_HIGH_only_p55 | 290 | 3477.69 | 1.5250 | 1.2200 | 245 |
| hmm2_HIGH_only_p65 | 288 | 3390.32 | 1.5118 | 1.2200 | 244 |
| **hmm2_no_gate (control)** | 500 | 4372.34 | 1.4548 | 1.1891 | 427 |
| hmm3_LOW_only_p55 | 121 | 848.36 | 1.6001 | 1.5016 | 112 |
| hmm3_LOW_only_p65 | 75 | 329.99 | 1.3908 | 1.1741 | 69 |
| hmm3_MID_only_p55 | 119 | 685.87 | 1.3700 | 1.0599 | 97 |
| hmm3_MID_only_p65 | 92 | 705.68 | 1.5362 | 1.1936 | 75 |
| hmm3_HIGH_only_p55 | 269 | 3433.69 | 1.5527 | 1.2674 | 227 |
| hmm3_HIGH_only_p65 | 267 | 3346.31 | 1.5386 | 1.2674 | 226 |
| hmm3_exclude_LOW_p55 | 376 | 3446.02 | 1.4224 | 1.1679 | 314 |
| hmm3_exclude_LOW_p65 | 353 | 3618.89 | 1.4769 | 1.1986 | 296 |
| **hmm3_exclude_MID_p55** | 386 | 4430.61 | **1.5806** | 1.3029 | 334 |
| hmm3_exclude_MID_p65 | 339 | 4019.11 | 1.5682 | 1.2980 | 291 |
| hmm3_exclude_HIGH_p55 | 257 | 1663.38 | 1.4592 | 1.1752 | 223 |
| hmm3_exclude_HIGH_p65 | 254 | 1402.76 | 1.3872 | 1.1330 | 221 |
| hmm3_no_gate (control) | 500 | 4372.34 | 1.4548 | 1.1891 | 427 |

(`hmm2_no_gate` and `hmm3_no_gate` are identical by construction — same
underlying signal population with no gate applied — confirming the harness
reproduces the Stage C baseline exactly regardless of which HMM is fit.)

### Per-build-year detail, top 2 candidates

**hmm3_HIGH_only_p55** (n=269, PF 1.5527) — **fails immediately**: 2023 is
net-negative.

| Year | n | net_pts | PF |
|---|---|---|---|
| 2018 | 83 | 112.23 | 1.1047 |
| 2020 | 70 | 1525.63 | 1.7652 |
| 2023 | 74 | **-237.66** | 0.8905 |
| 2026 | 42 | 2033.48 | 3.0838 |

**hmm3_exclude_MID_p55** (n=386, PF 1.5806) — all 4 build years individually
positive, the only serious candidate to clear that bar:

| Year | n | net_pts | PF |
|---|---|---|---|
| 2018 | 114 | 315.48 | 1.2702 |
| 2020 | 113 | 1436.02 | 1.5275 |
| 2023 | 107 | 199.50 | 1.0782 |
| 2026 | 52 | 2479.61 | 3.0857 |

## Mandatory perturbation validation — `hmm3_exclude_MID_p55`

Only this candidate cleared the primary screen (all years positive,
plausible trade count, PF improvement over no-gate). Re-run at training
windows 80/100/120 (seed fixed at 42) and at 5 preregistered seeds
(0, 1, 42, 123, 2024, window fixed at 120):

| Perturbation | window | seed | n | PF | 2018 net | 2020 net | 2023 net | 2026 net |
|---|---|---|---|---|---|---|---|---|
| window | 80 | 42 | 391 | 1.4822 | 253.6 | 1063.5 | 458.0 | 2113.4 |
| window | 100 | 42 | 384 | 1.4348 | 275.2 | 1070.2 | 240.0 | 1845.0 |
| window (primary) | 120 | 42 | 386 | 1.5806 | 315.5 | 1436.0 | 199.5 | 2479.6 |
| seed | 120 | 0 | 350 | 1.4152 | 100.6 | 1283.7 | **-574.8** | 2213.1 |
| seed | 120 | 1 | 352 | 1.5535 | **-28.0** | 1204.4 | 379.4 | 2295.0 |
| seed (primary) | 120 | 42 | 386 | 1.5806 | 315.5 | 1436.0 | 199.5 | 2479.6 |
| seed | 120 | 123 | 328 | 1.4504 | 237.6 | 1335.3 | 116.0 | 1208.1 |
| seed | 120 | 2024 | 329 | 1.4985 | 246.2 | 1445.6 | 137.4 | 1327.1 |

**Rejected.** At the identical training window (120), changing only the EM
initialization seed:
- **seed=0**: 2023 flips to net **-574.8** (vs. +199.5 at the primary
  seed=42) — the "all 4 build years positive" property the candidate was
  selected for does not survive a seed change.
- **seed=1**: 2018 flips to net **-28.0** (marginal, but still negative).

This is a direct hit on the preregistered rejection criterion "its result
depends materially on one particular seed." The window perturbation alone
looked survivable (PF stayed in 1.43-1.58, no collapse), but the seed
perturbation is decisive: the specific seed=42 run is not representative of
the candidate's behavior under EM re-initialization, and PF-only comparison
across seeds hid a real, materially different per-year outcome (a full
build year flipping sign). This is exactly the failure mode the mandatory
perturbation step exists to catch.

## Final decision: no-HMM

- `hmm3_HIGH_only` (the second-best primary candidate) independently fails
  on its own: 2023 net-negative at the primary setting, before any
  perturbation is even needed.
- `hmm3_exclude_MID_p55` (the only candidate with all 4 build years positive
  at its primary setting) fails the mandatory seed-perturbation test: two
  of five alternate seeds flip a build year negative.
- No other candidate in the full 18-row matrix improves over the no-gate
  baseline (PF 1.4548 / PF ex-2026 1.1891) while also keeping all 4 build
  years positive at its primary setting.

Per the preregistered rule that "no-HMM" is a legitimate outcome when no
gate demonstrably earns its keep, and consistent with this repository's
prior (separately superseded/rejected) HMM research lines, **Stage D is
frozen at no-HMM**: no regime gate is added to the pipeline.

Raw outputs: `outputs/og_build_years/stage_d_hmm_candidates_primary.csv`,
`outputs/og_build_years/stage_d_hmm_full_results_primary.json`,
`outputs/og_build_years/stage_d_hmm_perturbation.json`,
`outputs/og_build_years/stage_d_primary_*_build_years_trades.csv`.

Reproduction:
```
python3 scripts/og_stage_d_hmm_full.py
STAGE_D_PERTURB_CANDIDATES='[{"name":"hmm3_exclude_MID_p55","n_states":3,"exclude_idx":1,"threshold":0.55}]' \
    python3 scripts/og_stage_d_hmm_perturbation.py
```

---

## SUPERSEDED — original diagnostic-only version (annual-refit, 2-state, 60-min returns)

The original Stage D pass used a coarser, annual-refit (not session-refit)
2-state HMM on 60-minute returns only, as a diagnostic rather than the full
preregistered matrix. It reached the same final decision (no-HMM) via a
similar single-year-concentration argument (state1's PF advantage was
driven almost entirely by 2020), but did not test the 3-feature/3-state
matrix or run seed/window perturbation. Superseded by the complete method
above; kept here for history.

`src/og_hmm_gate.py`'s original method: walk-forward annual refit (fit only
on years strictly before year Y; 2018 had no gate, "unknown regime, do not
block"), causal per-bar forward-algorithm decoding.

| Candidate | n | net_pts | PF | win_rate | avg_trade | max_drawdown |
|---|---|---|---|---|---|---|
| no_hmm | 500 | 4372.34 | 1.4548 | 0.4100 | 8.745 | -793.77 |
| hmm_state0 | 438 | 1739.25 | 1.2233 | 0.4018 | 3.971 | -1197.64 |
| hmm_state1 | 212 | 2941.12 | 1.8283 | 0.4151 | 13.873 | -563.99 |

hmm_state1 per-year: 2018 +103.61 (PF 1.0709), 2020 +2141.90 (PF 3.4142,
n=34), 2023 **-344.43** (PF 0.3708, n=18), 2026 +1040.04 (PF 2.5885, n=20) —
same qualitative finding (trade-count collapse + single-year concentration +
one negative build year) as the full matrix's rejected candidates above.
