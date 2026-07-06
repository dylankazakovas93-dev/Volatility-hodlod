# OG VXN Exploratory Filter — Results

Phase: `POST_VALIDATION_EXPLORATORY_REDEVELOPMENT`. Protocol:
`docs/OG_VXN_EXPLORATORY_PROTOCOL.md` (written and committed before this
matrix was run). Runner: `scripts/og_vxn_exploratory.py`. Full outputs:
`outputs/og_vxn/vxn_candidate_summary.csv` (14 rows, one per candidate),
`outputs/og_vxn/vxn_per_year.csv` (126 rows: 14 candidates x 9 years),
`outputs/og_vxn/vxn_mechanism_buckets.csv`, per-candidate trade ledgers
`outputs/og_vxn/{base}__{filter}_trades.csv`.

2019/2021/2022/2024/2025 are labeled `FORMER_VALIDATION__NOW_DEVELOPMENT`
throughout -- never "OOS" for any candidate below, since these filters
are being chosen with knowledge of how those years perform. 2013-2015 was
never accessed.

## Determinism

The full 14-candidate matrix was run twice (`outputs/og_vxn/` and a
scratch rerun). All 14 ledger SHA-256 hashes were byte-identical between
runs (`outputs/og_vxn/ledger_hashes.json` vs the scratch rerun's
equivalent) -- confirmed programmatically, zero diffs.

## Combined redevelopment sample (2018-2026, all years pooled) — full 14-row table

| Base | Filter | n_trades | % of base retained | net_pts | PF_pts | total_R | PF_R | avg R/trade | win rate |
|---|---|---|---|---|---|---|---|---|---|
| PRIMARY_150R | NO_VXN_FILTER | 1034 | 100.0% | 6316.56 | 1.2998 | 36.6241 | 1.0944 | 0.0354 | 0.2921 |
| PRIMARY_150R | GE_20 | 671 | 64.9% | 5628.62 | 1.3526 | 31.8818 | 1.1257 | 0.0475 | 0.2966 |
| PRIMARY_150R | GE_25 | 386 | 37.3% | 4176.68 | 1.4601 | 21.6823 | 1.1551 | 0.0562 | 0.2876 |
| PRIMARY_150R | GE_30 | 179 | 17.3% | 1413.39 | 1.2810 | 2.1035 | 1.0314 | 0.0118 | 0.2737 |
| PRIMARY_150R | LE_20 | 364 | 35.2% | 628.32 | 1.1217 | 3.7423 | 1.0276 | 0.0103 | 0.2830 |
| PRIMARY_150R | LE_25 | 648 | 62.7% | 2139.89 | 1.1785 | 14.9418 | 1.0602 | 0.0231 | 0.2948 |
| PRIMARY_150R | LE_30 | 855 | 82.7% | 4903.18 | 1.3057 | 34.5206 | 1.1075 | 0.0404 | 0.2959 |
| OPERATIONAL_100R | NO_VXN_FILTER | 1040 | 100.0% | 6506.04 | 1.3347 | 28.7552 | 1.0791 | 0.0276 | 0.3856 |
| OPERATIONAL_100R | GE_20 | 675 | 64.9% | 5963.89 | 1.4104 | 30.4829 | 1.1303 | 0.0452 | 0.3970 |
| OPERATIONAL_100R | GE_25 | 388 | 37.3% | 4156.71 | 1.4964 | 18.9993 | 1.1449 | 0.0490 | 0.3892 |
| OPERATIONAL_100R | GE_30 | 180 | 17.3% | 1504.78 | 1.3202 | 2.2674 | 1.0361 | 0.0126 | 0.3667 |
| OPERATIONAL_100R | LE_20 | 366 | 35.2% | 482.53 | 1.0972 | -2.7277 | 0.9791 | -0.0075 | 0.3634 |
| OPERATIONAL_100R | LE_25 | 652 | 62.7% | 2349.33 | 1.2124 | 9.7559 | 1.0420 | 0.0150 | 0.3834 |
| OPERATIONAL_100R | LE_30 | 860 | 82.7% | 5001.26 | 1.3394 | 26.4877 | 1.0882 | 0.0308 | 0.3895 |

(GE_20/25/30 = `VXN_PREV_CLOSE_GE_{20,25,30}`; LE_20/25/30 =
`VXN_PREV_CLOSE_LE_{20,25,30}`. Full per-candidate detail including avg
winner/loser, payoff ratio, max drawdown pts/R, TP/SL/BE/cutoff counts,
profitable/losing/breakeven day counts, longest non-winning-day run,
best-year and net-excluding-best-year is in
`outputs/og_vxn/vxn_candidate_summary.csv`.)

## By-group breakdown (net_pts / total_R), required for the robustness check

| Base | Filter | Orig-build net_pts | Orig-build total_R | Former-val net_pts | Former-val total_R |
|---|---|---|---|---|---|
| PRIMARY_150R | NO_VXN_FILTER | 4599.14 | 47.4737 | 1717.42 | -10.8496 |
| PRIMARY_150R | GE_20 | 4087.47 | 35.5022 | 1541.15 | -3.6204 |
| PRIMARY_150R | GE_25 | 2361.92 | 19.6999 | 1814.75 | **1.9825** |
| PRIMARY_150R | GE_30 | 885.82 | 4.2250 | 527.56 | -2.1215 |
| PRIMARY_150R | LE_20 | 511.67 | 11.9715 | 116.65 | -8.2292 |
| PRIMARY_150R | LE_25 | 2237.22 | 27.7738 | -97.33 | -12.8321 |
| PRIMARY_150R | LE_30 | 3713.32 | 43.2487 | 1189.86 | -8.7281 |
| OPERATIONAL_100R | NO_VXN_FILTER | 4692.76 | 44.4520 | 1813.28 | -15.6968 |
| OPERATIONAL_100R | GE_20 | 4407.25 | 34.6266 | 1556.64 | -4.1436 |
| OPERATIONAL_100R | GE_25 | 2257.19 | 15.2222 | 1899.52 | **3.7771** |
| OPERATIONAL_100R | GE_30 | 884.63 | 3.0943 | 620.15 | -0.8268 |
| OPERATIONAL_100R | LE_20 | 285.52 | 9.8254 | 197.01 | -12.5531 |
| OPERATIONAL_100R | LE_25 | 2435.57 | 29.2297 | -86.24 | -19.4739 |
| OPERATIONAL_100R | LE_30 | 3808.13 | 41.3577 | 1193.13 | -14.8699 |

**`VXN_PREV_CLOSE_GE_25` is the only filter that produces positive total R
in BOTH the original-build group AND the former-validation group, for
BOTH bases.** Every other filter leaves the former-validation group's
total R negative (all six other filters), even where net points stay
positive.

## Individual-year detail

Full per-year table (all 9 years x 14 candidates): `outputs/og_vxn/vxn_per_year.csv`.
Key rows reproduced here for the baseline and the three `GE_*` filters
(the only family with a candidate that clears the by-group total-R check):

### OG_PRIMARY_150R

| Year | NO_VXN_FILTER net/R | GE_20 net/R | GE_25 net/R | GE_30 net/R |
|---|---|---|---|---|
| 2018 | 620.93 / 20.19 | 366.75 / 12.00 | 211.69 / 5.00 | 104.62 / 3.00 |
| 2019 | -415.82 / -22.61 | -295.90 / -10.91 | -83.81 / -2.50 | 21.56 / 0.50 |
| 2020 | 1401.01 / 2.72 | 1053.72 / 1.01 | 1071.66 / 1.26 | 953.70 / 2.23 |
| 2021 | 941.74 / 17.05 | 863.40 / 14.20 | 240.38 / -0.90 | 225.00 / 1.50 |
| 2022 | 1303.00 / 4.88 | 1303.00 / 4.88 | 1090.94 / 1.88 | 784.75 / -0.12 |
| 2023 | 645.14 / 14.33 | 734.94 / 12.26 | 229.69 / 7.37 | 0.00 / 0.00 |
| 2024 | -441.80 / -12.98 | -135.87 / -3.73 | 140.88 / 2.00 | -200.00 / -1.00 |
| 2025 | 330.29 / 2.81 | -193.48 / -8.07 | 426.38 / 1.50 | -303.75 / -3.00 |
| 2026 (partial) | 1932.07 / 10.23 | 1932.07 / 10.23 | 848.88 / 6.08 | -172.50 / -1.00 |

### OG_OPERATIONAL_100R

| Year | NO_VXN_FILTER net/R | GE_20 net/R | GE_25 net/R | GE_30 net/R |
|---|---|---|---|---|
| 2018 | 319.92 / 14.30 | 112.12 / 6.00 | 63.75 / 2.00 | 69.75 / 2.00 |
| 2019 | -500.01 / -24.52 | -346.71 / -11.91 | -105.38 / -3.00 | 0.00 / 0.00 |
| 2020 | 1345.31 / 0.76 | 1094.24 / 0.11 | 1079.93 / -0.64 | 987.38 / 2.09 |
| 2021 | 559.90 / 5.41 | 599.86 / 6.07 | 86.77 / -2.96 | 201.52 / 1.44 |
| 2022 | 1499.88 / 7.74 | 1499.88 / 7.74 | 1358.50 / 5.74 | 922.38 / 1.74 |
| 2023 | 494.53 / 9.74 | 667.88 / 8.87 | 291.38 / 6.87 | 0.00 / 0.00 |
| 2024 | -433.72 / -12.02 | -190.50 / -2.73 | 209.50 / 3.00 | -200.00 / -1.00 |
| 2025 | 687.24 / 7.69 | -5.89 / -3.31 | 350.12 / 1.00 | -303.75 / -3.00 |
| 2026 (partial) | 2533.00 / 19.65 | 2533.00 / 19.65 | 822.12 / 7.00 | -172.50 / -1.00 |

## 2019 and 2024 diagnosis (explicit, both configs)

**2019** (a locked-validation weak year for both bases, net_pts negative,
total_R deeply negative under `NO_VXN_FILTER`): `GE_20` improves it
(smaller loss, still negative) for both bases. `GE_25` improves it
further -- net_pts still slightly negative (-83.81 / -105.38) but total_R
shrinks to a small -2.5R / -3.0R from -22.6R / -24.5R, and trade count
drops to just 5 trades per base for the year. **`GE_30` actually flips
2019 barely positive/flat for PRIMARY_150R** (net +21.56, R +0.50) and
exactly flat for OPERATIONAL_100R (0/0), but on only 2 trades per base --
not a meaningful sample, this is noise on a near-empty bucket, not a real
fix. **Diagnosis: 2019's badness under `NO_VXN_FILTER` is concentrated
in a large number of lower/mid-VXN trades; raising the VXN floor removes
most of them and shrinks the loss roughly proportionally to how many
trades are removed, but does not turn 2019 into a genuinely good year at
any threshold with a meaningful trade count.**

**2024** (the other locked-validation weak year): `GE_20` meaningfully
improves it (net -441.80 -> -135.87 for 150R; -433.72 -> -190.50 for
100R; total_R -12.98R -> -3.73R / -12.02R -> -2.73R). **`GE_25` flips
2024 clearly positive for both bases** (140.88 / 2.00R for 150R; 209.50 /
3.00R for 100R), on 5 trades per base. **`GE_30` flips 2024 negative
again** (-200.00 / -1.00R, on just 1 trade per base -- a single losing
trade, not a real signal). **Diagnosis: 2024's badness is concentrated in
lower-VXN trades; `GE_25` genuinely removes most of the damage and turns
the small remaining sample net positive, but the sample is tiny (5
trades) and the further threshold (`GE_30`) reverses it on an even
smaller, single-trade sample** -- this is exactly the instability pattern
the neighboring-threshold robustness check (criterion 8, below) is
designed to catch.

## Mechanism diagnostic summary

See `docs/OG_VXN_MECHANISM_DIAGNOSTIC.md` for the full table and
reasoning. Headline: average original stop cap in the `>=30` VXN bucket is
**90.78 points** vs **44.61 points** in the `<20` bucket (+103.5%), while
avg R/trade in those same two buckets is only 0.0122 vs 0.0041 (both
close to flat) -- **the raw-point improvement visible in the `GE_*`
filter family is substantially a stop-cap-scaling artifact, not a clean
R-normalized edge.** The one bucket with a real R-normalized edge
(`25-30`: avg R/trade 0.0875, PF_R 1.26) is a **non-monotonic spike**
between two much weaker neighboring buckets, consistent with a
sample-specific effect rather than a genuine, generalizable
volatility-regime edge.

**Answer to the required question: is the apparent raw-point edge merely
a stop-cap/volatility-scaling effect, or does R-normalized expectancy
genuinely improve too?** Mostly the former. `GE_25` does show a real (if
modest) positive total_R in both analysis groups for both bases -- that
part is not purely a scaling artifact. But the mechanism-bucket table
shows expectancy does not rise smoothly with VXN level (it peaks at
`25-30` and falls at `>=30`), and the robustness checklist below shows
`GE_25`'s advantage does not survive scrutiny against its own neighboring
thresholds. The honest read is: raw points are meaningfully inflated by
cap scaling everywhere in the `GE_*` family, and the modest R-normalized
improvement that does show up is concentrated in a narrow,
non-monotonic, and neighbor-inconsistent band rather than a robust
volatility-regime effect.

## Robustness checklist (applied per `docs/OG_VXN_EXPLORATORY_PROTOCOL.md`)

Evaluated against the strongest-looking candidate, `VXN_PREV_CLOSE_GE_25`,
for both bases (the only filter in the entire matrix with positive total
R in both the original-build group and the former-validation group):

| # | Criterion | PRIMARY_150R / GE_25 | OPERATIONAL_100R / GE_25 |
|---|---|---|---|
| 1 | Improves/preserves in BOTH groups | Former-val flips from -10.85R to +1.98R (improves); orig-build total_R drops from 47.47R to 19.70R (still positive, but a large decline -- **partial pass, weakened** | Same pattern: former-val -15.70R -> +3.78R; orig-build 44.45R -> 15.22R -- **partial pass, weakened** |
| 2 | Not just deleting one losing year | 2019 stays negative under GE_25 (-83.81/-2.5R), so the improvement is not from deleting 2019 outright; but 2021 turns from a strong positive year (+17.05R/+14.20R->+240.38/-0.90R) into a near-flat/negative year -- the filter reshuffles which years are good/bad rather than uniformly improving | Same reshuffling pattern (2021 goes from +5.41R to -2.96R) |
| 3 | >=4 of 8 full years net_pts positive | 7 of 8 (all but 2019) | 7 of 8 (all but 2019) |
| 4 | >=4 of 8 full years total_R positive | 6 of 8 (2018,2020,2022,2023,2024,2025 positive; 2019,2021 negative) | 6 of 8 (2018,2023,2024,2025 clearly positive, 2020 slightly negative -0.64, 2022 positive; 2019,2021 negative -- effectively 5-6 depending on how -0.64 is counted) |
| 5 | >=300 combined trades | 386 -- PASS | 388 -- PASS |
| 6 | No single year >70% of positive net points | 25.61% (2022) -- PASS | ~similar, well under 70% -- PASS |
| 7 | Excl. best year still net positive | 3085.74 -- PASS | 2798.21 -- PASS |
| **8** | **Neighboring threshold directionally similar** | **FAIL: `GE_20` former-val total_R = -3.62R (negative), `GE_30` former-val total_R = -2.12R (negative); `GE_25` is a positive island between two negative neighbors -- a sign reversal, not a directionally-similar result** | **FAIL: `GE_20` former-val total_R = -4.14R, `GE_30` former-val total_R = -0.83R, both negative; same reversal pattern** |
| 9 | Effect present in both 1.00R and 1.50R bases | Yes, qualitatively the same pattern in both -- this criterion alone is satisfied | Yes |

**Criterion 8 fails for both bases.** Per the protocol, ALL criteria must
pass for `VXN_FILTER_PROVISIONALLY_EARNED`. `GE_25` -- the single most
promising candidate in the entire 14-row matrix on raw R-improvement --
does not clear the bar because its neighboring thresholds (`GE_20`,
`GE_30`) both show the opposite sign on former-validation total R. This
is precisely the overfitting/threshold-cherry-picking pattern the
neighbor-consistency check exists to catch, and it is corroborated
independently by the mechanism-bucket table's non-monotonic expectancy
peak at the same `25-30` band (`docs/OG_VXN_MECHANISM_DIAGNOSTIC.md`).

No other filter in the matrix comes as close to clearing the bar as
`GE_25` (every other filter fails the former-validation-group
by-group check, criterion 1, outright by leaving former-validation total R
negative). None of the six real filters clears the full robustness
checklist for either base.

## Classification

- **`OG_PRIMARY_150R`: `NO_VXN_FILTER_EARNED`.** No filter clears the
  full robustness bar. `GE_25` came closest (only candidate with positive
  total R in both analysis groups) but fails the neighboring-threshold
  consistency check (criterion 8), corroborated by a non-monotonic
  mechanism-bucket expectancy peak rather than a smooth volatility-regime
  gradient.
- **`OG_OPERATIONAL_100R`: `NO_VXN_FILTER_EARNED`.** Same reasoning,
  same failure mode, same candidate (`GE_25`) came closest and fails the
  same criterion.

No config file is created under `configs/` for either base (per the
selection rule, `NO_VXN_FILTER_EARNED` does not get a frozen config).

## Honest overall assessment

The VXN-prev-close filter family produces a real, non-trivial trade-count
reduction and a directionally consistent raw-point improvement as the
`GE_*` threshold rises, but that raw-point improvement is substantially
attributable to stop-cap scaling with realized volatility rather than a
clean per-unit-of-risk edge (see mechanism diagnostic). The one candidate
that does show a genuine R-normalized improvement across both required
analysis groups and both bases (`GE_25`) fails the neighboring-threshold
robustness check, which independently corroborates the mechanism
diagnostic's finding of a non-monotonic, likely sample-specific
expectancy spike rather than a stable regime effect. Neither base config
earns a VXN filter under the locked robustness criteria. This is a
genuine negative-but-informative result, not a data or engine problem:
execution invariants held throughout (no PROP_HARD_BLACKOUT violations
in any of the 14 runs), the deterministic rerun was byte-identical for
all 14 ledgers, and the per-year, per-group, and per-bucket breakdowns
are internally consistent with each other.

**No filtered candidate from this study is recommended to carry forward
into the still-untouched 2013-2015 test.** `GE_25` is the only candidate
worth naming as "not obviously worse than doing nothing," but it does not
meet this study's own pre-registered bar for being called a real,
generalizable filter, and carrying it forward would risk exactly the kind
of threshold-chasing this task's protocol was designed to prevent.
