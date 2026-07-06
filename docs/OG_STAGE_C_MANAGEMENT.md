# OG Stage C — Management (BE/exit-management) candidates (build years only)

**This document supersedes the original 4-candidate Stage C result below the
horizontal rule.** This is the full, preregistered 20-candidate management
family sweep required by the Phase 1 rigor follow-up.

Scope: `OG_BUILD_YEARS` only = {2018, 2020, 2023, 2026-partial through
2026-06-07}. No metric anywhere in this document includes
2019/2021/2022/2024/2025 trade outcomes.

Held constant across the whole comparison: `sal_enabled=False` (Stage B
freeze), the **canonical** 11:00-15:00 ET blocked entry window (NOT yet
Stage E's `RESEARCH_ENTRY_BLACKOUT_10_16` -- Stage C isolates the management
variable alone, per the task scope), no HMM gate, `PROP_HARD_BLACKOUT`
(16:00-19:00 ET, unconditional in the shared engine path), all
signal/level-generation mechanics unchanged.

Code: `src/og_management_variants.py` (`simulate_managed()` +
`run_variant_managed()`), additive wrapper reusing
`src/strict_engine.py`'s touch/level/session helpers and
`src/og_build_variant_engine.py`'s `PROP_HARD_BLACKOUT`/entry-gate skeleton.
`src/strict_engine.py` itself is untouched. Driver:
`python3 scripts/og_stage_c_full_sweep.py`.

**Correctness check:** `ctrl_BE45` (canonical, be_bars=45, canonical window)
reproduces the prior session's canonical result exactly: n=507,
net_pts=4039.77, PF=1.4533. `bc_BE60` reproduces the prior session's BE-60
pick exactly: n=500, net_pts=4372.34, PF=1.4548. This confirms the new
generic engine matches the original bar-count mechanics bit-for-bit before
trusting the new family results.

## Candidates tested (20 total)

| Group | Label | Parameters |
|---|---|---|
| Control | `ctrl_BE45` | be_bars=45 (canonical) |
| Control | `ctrl_noBE` | no BE mechanism at all, raw 1:1 TP/SL |
| Bar-count BE | `bc_BE30` / `bc_BE45` / `bc_BE60` / `bc_BE75` / `bc_BE90` | be_bars = 30/45/60/75/90 |
| Exact-R BE | `exr_050` / `exr_075` / `exr_100` / `exr_125` | move stop to breakeven at +0.50/0.75/1.00/1.25 R (R = trade's own `cap`), active from next bar |
| Profit lock | `lock_075_010` / `lock_100_010` / `lock_125_010` | trigger at +0.75/1.00/1.25R, lock stop at +0.10R, active from next bar |
| Time-based conditional BE | `time_30` / `time_45` / `time_60` / `time_75` | at 30/45/60/75 min elapsed, arm BE only if MFE>=0.25R by then AND most recent completed bar closed favorably; active from following bar |
| Scratch on recovery | `scratch_050` / `scratch_075` | arm at -0.50R / -0.75R adverse excursion; close at entry (breakeven) next time price recovers to touch/cross entry, evaluated from bar after arming; original stop stays live throughout |

All families use the same touch-bar-stop-only discipline as
`strict_engine.simulate_from_touch`/`simulate_cond_be`: the touch bar is
checked only for a stop hit (a touch-bar target hit is never assumed a win).

## Build-year aggregate results (all 20 candidates)

| candidate | n | net_pts | PF | avg_pts_per_trade | median_pts_per_trade | payoff_ratio | max_drawdown | avg_cap_norm_pnl |
|---|---|---|---|---|---|---|---|---|
| ctrl_BE45 | 507 | 4039.77 | 1.4533 | 7.968 | 0.0 | 1.247 | -721.54 | 0.0777 |
| ctrl_noBE | 477 | 4277.83 | 1.3567 | 8.968 | 9.375 | 1.171 | -702.77 | 0.1015 |
| bc_BE30 | 512 | 4337.67 | 1.4891 | 8.472 | 0.0 | 1.229 | -542.05 | 0.0892 |
| bc_BE45 | 507 | 4039.77 | 1.4533 | 7.968 | 0.0 | 1.247 | -721.54 | 0.0777 |
| bc_BE60 | 500 | 4372.34 | 1.4548 | 8.745 | 0.0 | 1.270 | -793.77 | 0.0794 |
| bc_BE75 | 494 | 2376.98 | 1.2231 | 4.812 | 0.0 | 1.134 | -932.60 | 0.0581 |
| bc_BE90 | 494 | 3817.34 | 1.3681 | 7.727 | 0.0 | 1.155 | -768.14 | 0.0875 |
| exr_050 | 503 | 3474.03 | 1.3663 | 6.907 | 0.0 | 1.127 | -613.25 | 0.0872 |
| exr_075 | 484 | 3711.56 | 1.3357 | 7.669 | 0.0 | 1.157 | -749.65 | 0.0939 |
| exr_100 | 477 | 4277.83 | 1.3567 | 8.968 | 9.375 | 1.171 | -702.77 | 0.1015 |
| exr_125 | 477 | 4277.83 | 1.3567 | 8.968 | 9.375 | 1.171 | -702.77 | 0.1015 |
| lock_075_010 | 484 | 3345.83 | 1.3026 | 6.913 | 4.894 | 0.925 | -872.36 | 0.0803 |
| lock_100_010 | 477 | 4277.83 | 1.3567 | 8.968 | 9.375 | 1.171 | -702.77 | 0.1015 |
| lock_125_010 | 477 | 4277.83 | 1.3567 | 8.968 | 9.375 | 1.171 | -702.77 | 0.1015 |
| time_30 | 497 | 4494.77 | 1.4442 | 9.044 | 0.0 | 1.197 | -661.54 | 0.0952 |
| time_45 | 499 | 4406.59 | 1.4470 | 8.831 | 0.0 | 1.237 | -738.04 | 0.0858 |
| time_60 | 495 | 4172.01 | 1.4008 | 8.428 | 0.0 | 1.209 | -758.61 | 0.0884 |
| time_75 | 491 | 3014.72 | 1.2754 | 6.140 | 0.0 | 1.141 | -986.69 | 0.0733 |
| scratch_050 | 487 | 2821.11 | 1.3062 | 5.793 | 0.0 | 1.037 | -603.39 | 0.0882 |
| scratch_075 | 479 | 3992.15 | 1.3729 | 8.334 | 0.0 | 1.167 | -612.44 | 0.0964 |

Note: `exr_100`, `exr_125`, `lock_100_010`, `lock_125_010` all collapse
exactly onto `ctrl_noBE`'s numbers. This is a real structural finding, not a
bug: the strategy's target is fixed at exactly 1.0R (1:1 R:R), so MFE can
never reach 1.0R or 1.25R without the trade having already exited at TP in
the same or an earlier bar -- these four candidates are degenerate
(equivalent to no-BE-at-all) under this strategy's fixed 1:1 payoff
structure.

## Full-year-only (excluding partial 2026)

| candidate | n | net_pts | PF | avg_pts_per_trade |
|---|---|---|---|---|
| ctrl_BE45 | 434 | 1299.41 | 1.1731 | 2.994 |
| ctrl_noBE | 407 | 1416.29 | 1.1459 | 3.480 |
| bc_BE30 | 438 | 1606.51 | 1.2193 | 3.668 |
| bc_BE45 | 434 | 1299.41 | 1.1731 | 2.994 |
| bc_BE60 | 427 | 1504.48 | 1.1891 | 3.523 |
| bc_BE75 | 422 | 154.25 | 1.0175 | 0.366 |
| bc_BE90 | 422 | 811.63 | 1.0939 | 1.923 |
| exr_050 | 430 | 1003.57 | 1.1271 | 2.334 |
| exr_075 | 413 | 1254.20 | 1.1382 | 3.037 |
| exr_100 | 407 | 1416.29 | 1.1459 | 3.480 |
| exr_125 | 407 | 1416.29 | 1.1459 | 3.480 |
| lock_075_010 | 413 | 899.94 | 1.0992 | 2.179 |
| lock_100_010 | 407 | 1416.29 | 1.1459 | 3.480 |
| lock_125_010 | 407 | 1416.29 | 1.1459 | 3.480 |
| time_30 | 424 | 1721.85 | 1.2059 | 4.061 |
| time_45 | 426 | 1418.17 | 1.1721 | 3.329 |
| time_60 | 422 | 1387.40 | 1.1611 | 3.288 |
| time_75 | 419 | 493.36 | 1.0541 | 1.177 |
| scratch_050 | 417 | 971.92 | 1.1281 | 2.331 |
| scratch_075 | 409 | 1376.36 | 1.1574 | 3.365 |

## Per-build-year detail for the shortlisted candidates

Only three of the 20 candidates have **all four build years net-positive**:
`ctrl_BE45`/`bc_BE45` (identical, canonical BE-45), `bc_BE60`, and
`scratch_050`. `time_30` has the single best aggregate net_pts/PF but 2018
is net-negative there (and across most other non-all-positive candidates).

| candidate | year | n | net_pts | PF | avg_pts/trade | median pts/trade | avg winner (pts) | avg loser (pts) | payoff ratio | max_drawdown | avg cap-norm pnl | % of pooled net pts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bc_BE60 | 2018 | 140 | 103.61 | 1.0709 | 0.740 | 0.0 | 28.985 | -30.449 | 0.952 | -317.36 | 0.0657 | 2.37 |
| bc_BE60 | 2020 | 150 | 1301.84 | 1.3819 | 8.679 | 0.0 | 82.640 | -56.810 | 1.455 | -563.16 | 0.0029 | 29.77 |
| bc_BE60 | 2023 | 137 | 99.04 | 1.0321 | 0.723 | 0.0 | 57.921 | -60.521 | 0.957 | -793.77 | 0.0651 | 2.27 |
| bc_BE60 | 2026 (partial) | 73 | 2867.86 | 2.7313 | 39.286 | 45.75 | 116.009 | -82.824 | 1.401 | -423.81 | 0.2896 | 65.59 |
| ctrl_BE45 | 2018 | 141 | 240.24 | 1.1735 | 1.704 | 0.0 | 28.505 | -30.099 | 0.947 | -235.61 | 0.0971 | 5.95 |
| ctrl_BE45 | 2020 | 156 | 971.00 | 1.3106 | 6.224 | 0.0 | 81.937 | -54.840 | 1.494 | -721.54 | -0.0161 | 24.04 |
| ctrl_BE45 | 2023 | 137 | 88.17 | 1.0294 | 0.644 | 0.0 | 58.199 | -61.151 | 0.952 | -702.32 | 0.0548 | 2.18 |
| ctrl_BE45 | 2026 (partial) | 73 | 2740.36 | 2.9494 | 37.539 | 0.746 | 112.056 | -82.689 | 1.355 | -355.12 | 0.2834 | 67.83 |
| scratch_050 | 2018 | 137 | 172.58 | 1.1229 | 1.260 | 0.0 | 29.191 | -32.645 | 0.894 | -603.39 | 0.0854 | 6.12 |
| scratch_050 | 2020 | 147 | 561.15 | 1.1682 | 3.817 | 0.0 | 72.174 | -64.158 | 1.125 | -506.01 | 0.0223 | 19.89 |
| scratch_050 | 2023 | 133 | 238.19 | 1.0837 | 1.791 | 0.0 | 57.113 | -63.243 | 0.903 | -543.27 | 0.0832 | 8.44 |
| scratch_050 | 2026 (partial) | 70 | 1849.20 | 2.1364 | 26.417 | 0.0 | 108.639 | -116.233 | 0.935 | -372.38 | 0.2417 | 65.55 |
| time_30 (best aggregate, but 2018 negative) | 2018 | 138 | -202.84 | 0.8854 | -1.470 | 0.0 | 28.505 | -34.051 | 0.837 | -530.51 | 0.0430 | -4.51 |
| time_30 | 2020 | 149 | 949.20 | 1.2518 | 6.370 | 0.0 | 76.101 | -60.791 | 1.252 | -661.54 | 0.0198 | 21.12 |
| time_30 | 2023 | 137 | 975.50 | 1.3457 | 7.120 | 0.0 | 62.252 | -62.709 | 0.993 | -459.49 | 0.1324 | 21.70 |
| time_30 | 2026 (partial) | 73 | 2772.92 | 2.5776 | 37.985 | 45.75 | 119.227 | -87.886 | 1.357 | -372.38 | 0.2782 | 61.69 |

Cross-candidate note: in every candidate, the pooled net points are
overwhelmingly dominated by 2026-partial (~60-68% of pooled net_pts in the
four rows above), consistent with the full-year-ex-2026 table showing much
thinner (though still generally positive) PF once 2026 is excluded. 2018 and
2023 are consistently the weakest, thinnest-edge years across nearly the
entire candidate set -- this is a property of the underlying signal/years,
not of any one management mechanism.

## Provisional winner selection (pre-perturbation)

Weighing more than aggregate net points:
- Only `bc_BE45`/`ctrl_BE45`, `bc_BE60`, and `scratch_050` have all 4 build
  years individually net-positive -- the bar used in Stage B/prior Stage C.
- Among those three, `bc_BE60` has the highest aggregate net_pts (4372.34)
  and PF (1.4548), the highest full-year-ex-2026 PF (1.1891) and net_pts
  (1504.48) of the three, and a materially better per-trade average (8.745,
  vs 7.968 for BE45 and 5.793 for scratch_050).
- `bc_BE60`'s tradeoff remains a larger max_drawdown (-793.77) than BE45
  (-721.54) or scratch_050 (-603.39), concentrated in the 2023 fold.
- `time_30` has the best headline aggregate net_pts/PF of any candidate but
  is excluded from consideration as a clean winner because 2018 is
  net-negative (-202.84) -- it fails the "helps more than one build year
  individually" / "all years positive" bar.

Provisional pick (pending perturbation): `bc_BE60` (be_bars=60), matching
the prior session's choice.

## Mandatory perturbation validation

Bar-count perturbation is +/-15 and +/-30 around be_bars=60, i.e. exactly
the already-swept `bc_BE30` (-30), `bc_BE45` (-15), `bc_BE75` (+15),
`bc_BE90` (+30) candidates. Full detail: `outputs/og_build_years/stage_c_perturbation.json`.

| Offset | Candidate | 2018 net_pts | 2020 net_pts | 2023 net_pts | 2026 net_pts | All years positive? | ex-2026 PF | ex-2026 avg pts/trade | aggregate max_drawdown |
|---|---|---|---|---|---|---|---|---|---|
| -30 | bc_BE30 | -20.01 | 996.37 | 630.15 | 2731.17 | **No** (2018 negative) | 1.2193 | 3.668 | -542.05 |
| -15 | bc_BE45 | 240.24 | 971.00 | 88.17 | 2740.36 | Yes | 1.1731 | 2.994 | -721.54 |
| 0 (winner) | bc_BE60 | 103.61 | 1301.84 | 99.04 | 2867.86 | Yes | 1.1891 | 3.523 | -793.77 |
| +15 | bc_BE75 | -113.87 | 237.81 | 30.31 | 2222.73 | **No** (2018 negative) | **1.0175** | **0.366** | -932.60 |
| +30 | bc_BE90 | -11.86 | 453.91 | 369.57 | 3005.71 | **No** (2018 negative) | 1.0939 | 1.923 | -768.14 |

**Verdict: `bc_BE60` does NOT pass the mandatory robustness bar cleanly.**

- Both the -30 (BE30) and +30 (BE90) neighbors flip 2018 net-negative.
- The +15 (BE75) neighbor shows a severe, discontinuous collapse rather than
  a smooth decay: ex-2026 PF drops from 1.1891 to 1.0175 (essentially
  breakeven) and ex-2026 avg pts/trade collapses from 3.523 to 0.366 --
  nearly a 90% reduction -- while aggregate max_drawdown simultaneously
  worsens from -793.77 to -932.60.
- 2018 is fragile across the *entire* bar-count neighborhood (near-zero or
  negative at every tested value except BE45/BE60), which suggests the
  apparent "all years positive at exactly BE60" result may be sitting on a
  narrow, non-generalizing peak rather than reflecting a robust management
  edge.
- The mechanism therefore fails the "neighbours stay positive on
  all/nearly-all build years" and "no discontinuous change" criteria from
  the mandatory validation bar.

No other candidate in the full 20-candidate sweep does better on this test:
`ctrl_BE45`/`bc_BE45` (the -15 neighbor) is itself one of only three
all-positive candidates, but has lower aggregate net_pts/PF/avg-trade than
BE60, and its own neighborhood (BE30 at -15 relative to it, BE75 at +30
relative to it) shows the same fragility pattern. `scratch_050`'s natural
neighbor `scratch_075` is NOT all-years-positive (2018 -43.72), so
scratch's own two-point "sweep" also does not show a clean, validated
plateau.

## Final Stage C selection and honest caveat

**Nothing in this sweep passes the mandatory perturbation bar cleanly.**
Per the task's fallback instruction, we select the most defensible option
with caveats stated explicitly rather than overstating confidence:

**Provisional (non-robust) pick: `be_bars = 60`, `be_extra_lock = 0.0`**
(unchanged from the prior session's freeze), for these reasons:
- It is one of only three candidates (of 20) with all four build years
  individually net-positive.
- Among those three it has the best aggregate and full-year-ex-2026
  PF/net_pts/avg-trade.
- Its failure mode under perturbation (BE30/BE75/BE90 degrade or flip) is
  shared by the entire bar-count family, including the canonical BE45 -- so
  this is not evidence that BE60 specifically is worse than the alternative
  bar-count values; it is evidence that **no single bar-count value in this
  family has been shown to be robustly, individually better than its
  neighbors** on this data. The choice of exactly 60 over 45 remains a real,
  material, un-de-risked assumption.
- **Caveat, stated explicitly:** this selection should NOT be presented as a
  validated, robust finding. 2018 and 2023 net expectancy is thin-to-flat
  under essentially every bar-count value tested (near zero at BE45/BE60,
  negative at BE30/BE75/BE90), meaning the aggregate "all 4 years positive"
  result for BE60 is not a strong signal and could plausibly flip with a
  different data draw, execution-cost assumption, or minor mechanism change.
  A future session should treat `be_bars` as still-open pending either (a) a
  genuine fold-based LOBYO re-selection (not yet done, see summary doc) or
  (b) evidence from a different management family (e.g. `scratch_050`, which
  is also all-positive but not yet perturbation-tested on its own axis
  beyond the two tested trigger levels) that is more stable under
  perturbation.

Raw outputs: `outputs/og_build_years/stage_c_full_sweep_results.csv`,
`outputs/og_build_years/stage_c_full_sweep_raw_summary.json`,
`outputs/og_build_years/stage_c_perturbation.json`,
`outputs/og_build_years/stage_c_*_build_years_trades.csv` (per-candidate
trade-level detail).

---

## SUPERSEDED — see above

# OG Stage C — Management (BE/exit-management) candidates (build years only) [ORIGINAL, INSUFFICIENT VERSION]

Scope: `OG_BUILD_YEARS` only = {2018, 2020, 2023, 2026-partial}. Carries forward
the Stage B freeze (`sal_enabled=False`). No metric below includes
2019/2021/2022/2024/2025 trade outcomes.

## Candidates tested

| Label | be_bars | be_extra_lock | Description |
|---|---|---|---|
| BE45_lock0 | 45 | 0.0 | Canonical BE-45 (baseline candidate) |
| BE30_lock0 | 30 | 0.0 | Earlier BE trigger |
| BE60_lock0 | 60 | 0.0 | Later BE trigger |
| BE45_lock2 | 45 | 2.0 | Canonical BE-45 + 2pt profit lock beyond entry once armed |

Command: `python3 scripts/og_stage_c_management.py` (uses
`src/og_build_variant_engine.run_variant` with `sal_enabled=False` carried
from Stage B).

## Build-year aggregate results

| Candidate | n | net_pts | PF | win_rate | avg_trade | max_drawdown |
|---|---|---|---|---|---|---|
| BE45_lock0 | 507 | 4039.77 | 1.4533 | 0.3886 | 7.968 | -721.54 |
| BE30_lock0 | 512 | 4337.67 | 1.4891 | 0.3809 | 8.472 | -542.05 |
| BE60_lock0 | 500 | 4372.34 | 1.4548 | 0.4100 | 8.745 | -793.77 |
| BE45_lock2 | 507 | 3954.65 | 1.4437 | 0.6667 | 7.800 | -711.54 |

(Note: BE45_lock2's much higher "win_rate" is an artifact of counting any
locked-in-profit BE exit as a "win" under `pnl>0`; it is not directly
comparable to the other rows' win-rate definition without re-deriving BE
semantics, so it is not used as a deciding metric here.)

## Per-build-year breakdown

### BE30_lock0
| Year | n | net_pts | PF | max_drawdown |
|---|---|---|---|---|
| 2018 | 144 | -20.01 | 0.9863 | -414.06 |
| 2020 | 155 | 996.37 | 1.3150 | -542.05 |
| 2023 | 139 | 630.15 | 1.2333 | -512.83 |
| 2026 (partial) | 74 | 2731.17 | 2.7715 | -345.00 |

### BE60_lock0
| Year | n | net_pts | PF | max_drawdown |
|---|---|---|---|---|
| 2018 | 140 | 103.61 | 1.0709 | -317.36 |
| 2020 | 150 | 1301.84 | 1.3819 | -563.16 |
| 2023 | 137 | 99.04 | 1.0321 | -793.77 |
| 2026 (partial) | 73 | 2867.86 | 2.7313 | -423.81 |

(BE45_lock0 per-year figures are in `docs/OG_STAGE_B_SAL.md`'s SAL_off table.)

## Selection rationale

- BE30_lock0 has the best aggregate PF (1.4891) but **2018 is net-negative**
  (-20.01) — it fails the "all build years positive" bar that Stage B used.
- BE60_lock0 has the highest aggregate net_pts (4372.34) and **is the only
  candidate other than canonical BE45 with all 4 build years net-positive**
  (103.61 / 1301.84 / 99.04 / 2867.86), and it also has the highest per-trade
  average (8.745) and highest win rate (0.4100) among the directly comparable
  candidates.
- Its tradeoff is a larger aggregate max drawdown (-793.77, driven by the 2023
  fold specifically) than BE30 or BE45 — a real cost, but not disqualifying
  given every year still nets positive and the drawdown is concentrated in a
  single build year rather than being systemic.
- BE45_lock2's altered "win" semantics for locked BE exits make it not
  directly comparable on this metric set; its net_pts is also the lowest of
  the four, so it does not warrant using a nonstandard BE definition.

**Frozen decision: `be_bars = 60`, `be_extra_lock = 0.0`** (a later BE trigger
than canonical BE-45, no extra profit-lock threshold).

Raw outputs: `outputs/og_build_years/stage_c_*_build_years_trades.csv`,
`outputs/og_build_years/stage_c_management_results.json`.
