# Stage F — Target / RR (Reward:Risk) Study

Status: COMPLETE. **Decision: `RR_SELECTED` — 1.50R, Lane B (BE60).**

## Scope and held-constant parameters

Build years only: **{2018 (full), 2020 (full), 2023 (full), 2026 (partial)}**.
No metric below includes 2019/2021/2022/2024/2025 trade outcomes. No
`OG_PRE_VALIDATION_LOCK`. No Monte Carlo, no prop-account simulation.

Held constant across every candidate:
- SAL off (Stage B freeze).
- Stage E's selected blocked entry interval, `RESEARCH_ENTRY_BLACKOUT_10_15`
  (`blocked_window=(600, 900)`, i.e. entries blocked 10:00-15:00 ET) --
  supersedes the earlier 10:00-16:00 label per `docs/OG_STAGE_E_WINDOWS_COMPLETE.md`.
- Original stop distance/cap logic unchanged: `cap = min(1.5*anchor, SL_CAP)`.
  Stage F **never** changes the stop; only the target distance moves.
- Forced liquidation 15:00 ET (`session_cutoff()`, unchanged).
- `PROP_HARD_BLACKOUT` (16:00-19:00 ET) always on, unconditional, checked
  inside `run_variant_managed` and independently re-verified for every
  candidate below (all pass).

## Implementation

A new optional parameter, `target_r` (default `1.0`), was added to
`src.og_management_variants.simulate_managed`. It scales the target distance
as `target_dist = target_r * cap` (previously hard-coded to `cap`, i.e.
`target_r=1.0`); the stop (`orig_stop`, breakeven/management stops) is
untouched. `src/strict_engine.py` was not modified. `run_variant_managed`
itself required no changes: `target_r` is forwarded automatically through
its existing `**mgmt_kwargs` passthrough to `simulate_managed`.

**Sanity check**: re-running the frozen Stage E BE60 candidate
(`mode="barcount", be_bars=60, target_r=1.0`, blocked_window 10:00-15:00)
reproduces `net_pts(ALL) = 5011.09` exactly, matching
`docs/OG_STAGE_E_WINDOWS_COMPLETE.md`'s 10:00 row — confirming `target_r=1.0`
is a true no-op and no other stage's numbers were altered.

Two lanes per RR:
- **Lane A — no management**: `mode="none"` (raw TP/SL, no BE/lock/scratch
  mechanism at all), new target only.
- **Lane B — BE60**: `mode="barcount", be_bars=60` (exact Stage C mechanism,
  unchanged), new target only.

RRs tested: 0.75, 1.00, 1.25, 1.50, 2.00 (`target_r` = per-trade stop
distance `cap`, fixed at entry, multiplied by the stated RR).

Reproduction: `python3 scripts/og_stage_f_rr_complete.py` (requires
`outputs/og_build_years/_cache.pkl`). Outputs:
`outputs/og_build_years/stage_f_rr_complete.csv` (full per-candidate,
per-year metric table), `stage_f_rr_complete_raw.json`,
`stage_f_excursion_diagnostic.csv`, `stage_f_mgmt_interaction.csv`, and
per-candidate build-year trade ledgers `stage_f_<candidate>_build_years_trades.csv`.

## Full 10-candidate table (ALL / ALL_ex2026)

| candidate | scope | n | net_pts | PF_pts | PF_R | avg_R/trade | max_dd_pts | max_dd_R | win_rate | avg_win | avg_loss | payoff | TP | SL | BE | cutoff | hold_med(min) | hold_mean(min) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Lane A 0.75R | ALL | 386 | 3712.89 | 1.4990 | 1.2963 | 0.1052 | -624.75 | -12.3016 | 0.6244 | 46.279 | -51.313 | 0.902 | 236 | 132 | 0 | 18 | 96.0 | 179.4 |
| Lane A 0.75R | ex2026 | 331 | 1660.25 | 1.2783 | 1.2017 | 0.0749 | -624.75 | -12.3016 | 0.6073 | 37.939 | -45.888 | 0.827 | 196 | 118 | 0 | 17 | 95.0 | 182.3 |
| Lane B 0.75R | ALL | 401 | 3507.95 | 1.5756 | 1.2695 | 0.0785 | -618.04 | -13.6552 | 0.4963 | 48.251 | -49.950 | 0.966 | 197 | 113 | 80 | 11 | 71.0 | 133.3 |
| Lane B 0.75R | ex2026 | 344 | 1429.44 | 1.2882 | 1.1591 | 0.0484 | -618.04 | -13.6552 | 0.4738 | 39.199 | -45.504 | 0.861 | 161 | 101 | 72 | 10 | 71.0 | 132.8 |
| Lane A 1.00R | ALL | 382 | 5071.08 | 1.6166 | 1.3480 | 0.1415 | -621.14 | -9.6963 | 0.5681 | 61.271 | -49.847 | 1.229 | 206 | 148 | 0 | 28 | 136.5 | 222.7 |
| Lane A 1.00R | ex2026 | 328 | 2290.72 | 1.3446 | 1.2482 | 0.1054 | -621.14 | -9.6963 | 0.5488 | 49.658 | -44.916 | 1.106 | 171 | 133 | 0 | 24 | 136.5 | 223.6 |
| **Lane B 1.00R** | **ALL** | **400** | **5011.09** | **1.7852** | **1.3573** | **0.1124** | **-563.16** | **-9.5677** | **0.4375** | **65.103** | **-48.349** | **1.347** | **168** | **122** | **93** | **17** | **79.0** | **158.4** |
| **Lane B 1.00R** | **ex2026** | **343** | **2307.78** | **1.4397** | **1.2168** | **0.0718** | **-563.16** | **-9.5677** | **0.4111** | **53.587** | **-44.101** | **1.215** | **136** | **110** | **83** | **14** | **79.0** | **156.1** |
| Lane A 1.25R | ALL | 377 | 4450.47 | 1.4739 | 1.2986 | 0.1369 | -832.73 | -9.9807 | 0.5119 | 71.716 | -51.037 | 1.405 | 172 | 165 | 0 | 40 | 188.0 | 260.6 |
| Lane A 1.25R | ex2026 | 324 | 2288.07 | 1.3125 | 1.2658 | 0.1242 | -605.24 | -8.4463 | 0.5031 | 58.963 | -45.483 | 1.296 | 148 | 145 | 0 | 31 | 181.5 | 255.3 |
| Lane B 1.25R | ALL | 398 | 4074.82 | 1.5786 | 1.2739 | 0.0918 | -752.35 | -7.7737 | 0.3618 | 77.204 | -49.947 | 1.546 | 130 | 129 | 113 | 26 | 89.0 | 180.8 |
| Lane B 1.25R | ex2026 | 342 | 2515.17 | 1.4600 | 1.2465 | 0.0842 | -553.54 | -7.7737 | 0.3567 | 65.432 | -44.452 | 1.472 | 112 | 113 | 97 | 20 | 87.5 | 173.7 |
| Lane A 1.50R | ALL | 375 | 4926.03 | 1.5048 | 1.2945 | 0.1450 | -780.40 | -9.3984 | 0.4747 | 82.492 | -49.531 | 1.665 | 149 | 176 | 0 | 50 | 226.0 | 285.0 |
| Lane A 1.50R | ex2026 | 322 | 2628.33 | 1.3506 | 1.2667 | 0.1335 | -681.50 | -9.3984 | 0.4658 | 67.504 | -43.588 | 1.549 | 128 | 154 | 0 | 40 | 217.5 | 279.5 |
| **Lane B 1.50R** | **ALL** | **398** | **4903.34** | **1.6934** | **1.3264** | **0.1103** | **-674.80** | **-8.7396** | **0.3241** | **92.829** | **-49.452** | **1.877** | **112** | **130** | **126** | **30** | **103.5** | **193.6** |
| **Lane B 1.50R** | **ex2026** | **342** | **2771.47** | **1.5042** | **1.2685** | **0.0926** | **-548.66** | **-8.7396** | **0.3129** | **77.272** | **-43.973** | **1.757** | **94** | **114** | **110** | **24** | **99.5** | **187.6** |
| Lane A 2.00R | ALL | 375 | 2684.28 | 1.2426 | 1.1807 | 0.0991 | -1055.87 | -22.2967 | 0.4080 | 89.862 | -49.841 | 1.803 | 104 | 194 | 0 | 77 | 301.0 | 331.3 |
| Lane A 2.00R | ex2026 | 322 | 1738.31 | 1.2115 | 1.1932 | 0.1065 | -1016.15 | -22.2967 | 0.4068 | 76.007 | -43.030 | 1.766 | 93 | 168 | 0 | 61 | 289.5 | 322.6 |
| Lane B 2.00R | ALL | 398 | 2640.48 | 1.3444 | 1.1365 | 0.0497 | -948.78 | -17.2186 | 0.2487 | 104.118 | -49.466 | 2.105 | 71 | 140 | 144 | 43 | 124.0 | 224.4 |
| Lane B 2.00R | ex2026 | 342 | 1406.64 | 1.2399 | 1.0939 | 0.0349 | -743.66 | -17.2186 | 0.2398 | 88.649 | -43.427 | 2.041 | 61 | 123 | 125 | 33 | 122.0 | 214.4 |

`avg_R/trade` = `cap_norm_R_avg`. `PF_R` = profit factor computed on
cap-normalized R values (pnl/cap), not raw points. Full detail (all years,
`ALL_ex_best_year`, hold p25/p75, `% pooled profit by year`) is in
`outputs/og_build_years/stage_f_rr_complete.csv`.

### Per-year net points (build years only)

| candidate | 2018 | 2020 | 2023 | 2026 |
|---|---|---|---|---|
| Lane A 0.75R | 19.05 | 830.49 | 810.71 | 2052.64 |
| Lane B 0.75R | 144.98 | 799.42 | 485.03 | 2078.51 |
| Lane A 1.00R | 95.92 | 1146.75 | 1048.05 | 2780.36 |
| Lane B 1.00R | 285.80 | 1478.90 | 543.09 | 2703.30 |
| Lane A 1.25R | 197.06 | 1150.87 | 940.15 | 2162.40 |
| Lane B 1.25R | 369.87 | 1582.52 | 562.78 | 1559.65 |
| **Lane B 1.50R** | **507.87** | **1716.53** | **547.07** | **2131.87** |
| Lane A 1.50R | 418.31 | 1226.08 | 983.94 | 2297.70 |
| Lane A 2.00R | 303.50 | 310.71 | 1124.10 | 945.97 |
| Lane B 2.00R | 314.74 | 843.17 | 248.73 | 1233.84 |

Every one of the 10 candidates keeps all 4 build years individually
net-positive.

## Excursion diagnostic (computed once, reused across all 10 candidates)

This is a property of trade *paths* (entries + the raw stop distance `cap`),
not of which RR/lane is later selected, so it was computed once using the
canonical BE60 target=1.0R (Stage E frozen) trade population as the
reference entry set (`n=400`). For each trade, the raw per-trade OHLC path
was walked bar-by-bar from the bar after the touch bar, tracking maximum
favorable excursion (MFE, in R = favorable points / `cap`) **until the
original stop or the session cutoff was reached** — target and management
were ignored entirely for this diagnostic (no re-simulation of any managed
outcome):

| Favorable excursion threshold | Trades reaching it | % of 400 |
|---|---|---|
| +0.50R | 288 | 72.00% |
| +0.75R | 244 | 61.00% |
| +1.00R | 216 | 54.00% |
| +1.25R | 183 | 45.75% |
| +1.50R | 158 | 39.50% |
| +2.00R | 110 | 27.50% |

This shows the underlying signal population has real, gradually-decaying
excursion depth well past 1.0R — 39.5% of trades reach +1.5R and 27.5% reach
+2.0R before their raw stop/cutoff, which is consistent with (though does
not by itself prove) the observed Lane B improvement from 1.00R through
1.50R before collapsing at 2.00R once management/exit-timing interactions
are taken into account.

## Management-interaction diagnostics (Lane B only, read-only)

For each RR, two counterfactuals were computed on the exact same entries as
the actual Lane B trade (never altering any P&L number reported above):
(a) `mode="none"` with the same `target_r` (no management, same target) --
isolates what BE60 changed relative to a plain stop/target outcome on the
same entry; (b) the Lane B RR=1.00 baseline trade on the matching entry --
isolates what a *larger* target changed relative to the frozen 1.0R
candidate.

| RR | n mgmt (BE) exits | avoided full stop | sacrificed full target | reached this RR's target after mgmt exit | baseline-1R TP -> cutoff | baseline-1R TP -> mgmt exit |
|---|---|---|---|---|---|---|
| 0.75 | 80 | 24 | 48 | 48 | 0 | 0 |
| 1.00 | 93 | 32 | 48 | 48 | 0 | 0 |
| 1.25 | 113 | 44 | 51 | 51 | 9 | 20 |
| 1.50 | 126 | 55 | 45 | 45 | 13 | 33 |
| 2.00 | 144 | 64 | 37 | 37 | 26 | 51 |

Reading this: at every RR, a large share of BE60's management exits (roughly
40-55%) *did* avoid what would otherwise have been a full stop-out on the
same entry (`avoided_full_stop`); a comparable share sacrificed what would
otherwise have reached the (then-current) target (`sacrificed_full_target`
== `reached_this_rr_target_after_mgmt_exit`, since both counts are driven by
the same no-management counterfactual reaching TP). As RR increases, more of
the frozen 1.0R baseline's TP trades get converted -- by the wider target
alone -- into either a cutoff exit (13 at 1.50R, 26 at 2.00R) or a
management (BE) exit instead of a full TP (33 at 1.50R, 51 at 2.00R). This
conversion accelerates sharply between 1.50R and 2.00R (roughly 2x for both
counts), consistent with the sharp collapse in Lane B's win rate (0.3129 ->
0.2398 ex2026) and avg R/trade (0.0926 -> 0.0349 ex2026) seen in the main
table at 2.00R.

## Selection standard applied

Ordered neighbourhood: 0.75 / 1.00 / 1.25 / 1.50 / 2.00. Lane B (the
candidate family actually eligible for the frozen management stack) is
assessed as the primary lane; Lane A is reported for comparison only.

- **No isolated maximum**: Lane B's ex2026 PF_R rises monotonically and
  smoothly from 0.75 (1.1591) through 1.00 (1.2168), 1.25 (1.2465), to 1.50
  (1.2685) -- a genuine plateau/climb, not a spike -- before dropping at 2.00
  (1.0939). 1.50 sits at the top of a 4-point climb, not as a singleton.
- **Immediate neighbours directionally profitable**: 1.25 (PF_R 1.2465,
  PF_pts 1.4600) and 2.00 (PF_R 1.0939, PF_pts 1.2399) both remain
  profitable in every scope tested. No neighbour of 1.50 collapses to
  unprofitability.
- **Full-year-ex2026 results stay acceptable**: 1.50's ex2026 PF_pts is
  1.5042 (PF_R 1.2685), the highest of all 10 Lane B/A candidates.
- **avg R/trade stable, not spike-then-collapse**: ex2026 cap_norm_R_avg
  climbs 0.0484 -> 0.0718 -> 0.0842 -> 0.0926 across 0.75/1.00/1.25/1.50 (a
  smooth, monotonic climb), then collapses to 0.0349 at 2.00. 1.50 is the
  last point of a stable climb, not the value immediately before a
  collapse used to inflate an isolated reading.
- **Drawdown does not worsen disproportionately at the selected point**:
  max_dd_R(ALL) for 1.25/1.50/2.00 is -7.7737 / -8.7396 / -17.2186 -- a
  smooth, bounded step from 1.25 to 1.50, then a real, disclosed near-doubling
  from 1.50 to 2.00 (echoing the BE60-BE75 asymmetry disclosed in
  `docs/OG_STAGE_C_MANAGEMENT_COMPLETE.md` and the 10:00/+30/+60 asymmetry in
  `docs/OG_STAGE_E_WINDOWS_COMPLETE.md`). This is flagged explicitly, not
  smoothed over, and it argues against selecting 2.00R, not against 1.50R.
- **Cutoff exits do not dominate the exit mix at the selected point**: at
  1.50R, cutoff is 30/398 (7.5%) of Lane B ALL trades, well behind TP (112)
  and BE (126). At 2.00R cutoff rises to 43/398 (10.8%) alongside a BE share
  that now exceeds TP (144 vs 71) -- another reason 2.00R is rejected, not
  1.50R.
- **More than one build year supports the result**: all 4 build years
  (2018/2020/2023/2026) are individually net-positive for Lane B 1.50R, and
  3 of 4 years (2018, 2020, 2023) individually improve or hold versus the
  1.00R baseline (2018: 285.80 -> 507.87; 2020: 1478.90 -> 1716.53; 2023:
  543.09 -> 547.07; 2026: 2703.30 -> 2131.87, the one year that gives back
  some edge but remains strongly positive).

2.00R is rejected as the isolated/cliff-edge case here: win rate falls to
0.24-0.25, avg R/trade and PF_R both collapse, drawdown nearly doubles, and
the management-interaction diagnostics show the wider target is
increasingly converting what would have been clean 1.0R baseline TPs into
cutoffs or management scratches rather than into genuinely larger winners.

## Decision

**`RR_SELECTED`: 1.50R, Lane B (BE60 management, `mode="barcount",
be_bars=60, target_r=1.5`)**, i.e. TP distance = 1.5x the per-trade stop
distance `cap`, stop unchanged, BE60 mechanism unchanged, held on top of
Stage E's `RESEARCH_ENTRY_BLACKOUT_10_15` and Stage C's BE60 confirmation.

Carried-forward caveat (consistent with Stage C's and Stage E's disclosed
asymmetries): the neighbourhood is stable and monotonically improving from
0.75R through 1.50R, but fragile immediately beyond it at 2.00R. This should
be re-examined if any later stage perturbs the target parameter again.

Frozen going forward: `target_r=1.5` (Lane B / BE60), `blocked_window=(600,
900)` (Stage E), `mode="barcount", be_bars=60` (Stage C), no HMM (Stage D),
SAL off (Stage B), forced liquidation 15:00 ET, `PROP_HARD_BLACKOUT`
unconditional.
