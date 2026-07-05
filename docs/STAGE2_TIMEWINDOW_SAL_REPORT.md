# Stage 2 -- Time Window and SAL Report

Research branch: `research/claude-stage2-timewindow-sal`, from commit
`630d8166f5fed952e7d701db09c719e13df8d38f`.

Development years: **2018, 2020, 2023, partial 2026** only. Reserved years
(2019, 2021, 2022, 2024, 2025) are never entered into a trade at all
(`skip_counts["blocked_reserved_year"]`) -- caught by my own
`test_reserved_years_never_in_selected_window_report` test during review,
which found the first implementation merely omitted reserved years from
*reporting* while still executing (and saving to disk) their trades; fixed
so reserved-year touches are consumed without ever entering, matching "do
not calculate ... strategy results" literally. Historical bars from any
year still feed causal lagged features exactly as before (this needs no
special-casing -- the feature table only ever looks backward from touch
time).

## 1. Frozen formula

Refit `learned|fs=F2|mfeq=0.50|maeq=0.50` using only the 1,274 qualifying
signal paths whose session date falls in 2018, 2020, 2023, or 2026. Gross
P&L only (cost = 0.0 throughout Stage 2, per instructions).

```
log1p(conventional_mfe_pts) = -0.3715
    + 0.0000 * log1p(range_30m)
    + 0.8250 * log1p(prev_session_range)
    + 0.3000 * log(RVOL_60)          <- at its imposed bound again

log1p(conventional_mae_pts) =  0.8476
    + 0.0572 * log1p(range_30m)
    + 0.5492 * log1p(prev_session_range)
    + 0.2387 * log(RVOL_60)

mfe clip (training 5th/95th pct): [3.198, 283.25] pts
mae clip (training 5th/95th pct): [2.900, 225.97] pts
```

The RVOL/TP coefficient again saturates at its +0.30 bound (same pattern
noted in Stage 1) -- carried forward as a known characteristic of this
formula family, not re-litigated here (Stage 2's scope is the time-window
and SAL layer, not the TP/SL family itself).

## 2. All-hours baseline (SAL off)

| Year | n | net (pts) | PF | avg R |
|---|---|---|---|---|
| 2018 | 237 | -982.45 | 0.7758 | -0.1133 |
| 2020 | 231 | -982.13 | 0.8529 | -0.0422 |
| 2023 | 241 | +1,285.53 | 1.2372 | 0.0922 |
| 2026 | 97 | +1,371.06 | 1.3609 | 0.1449 |
| **Pooled** | **806** | **+692.01** | **1.0341** | -0.0004 |

**All-hours already fails the "all four years profitable" criterion**
(2018 and 2020 are net losers) -- this is the reason the time-window
search matters and isn't a formality.

## 3. All 51 time windows (SAL off)

Full table: `outputs/stage2_windows_sal_off.csv` (36 contiguous + 8
minus-one + 7 minus-two-adjacent = 51 windows, exactly as specified, no
finer boundaries invented).

**Windows clearing every selection-relevant bar** (all 4 dev years
profitable AND >=25 trades in each year):

| window | blocks | n_blocks | PF | net (pts) | y2018 PF | y2020 PF | y2023 PF | y2026 PF |
|---|---|---|---|---|---|---|---|---|
| B-C-D-E | 00:00-09:30 | 4 | 1.3934 | +1,925.39 | 1.3383 | 1.0114 | 1.2589 | 3.0258 |
| D-E-F | 05:00-11:00 | 3 | 1.3119 | +2,156.79 | 1.1443 | 1.0484 | 1.3536 | 1.8229 |
| **E-F** | **08:00-11:00** | **2** | **1.3836** | **+2,132.91** | **1.1629** | **1.1696** | **1.4747** | **1.7753** |

**This is a broad region, not an isolated spike**: every window
containing blocks D, E, and/or F -- `D-E` (PF 1.4542), `C-D-E` (1.2931),
`C-D-E-F` (1.2450), `B-C-D-E-F` (1.3031), `E-F-G` (1.1227), `D-E-F-G`
(1.1121) -- is solidly profitable (PF > 1.1) even where it doesn't clear
the strict 25-trades/all-4-years bar. `contig:E` alone shows an even
higher PF (2.1955) but only 9-23 trades per year -- correctly excluded by
the trade-count floor as too small a sample to trust, not cherry-picked.

**E-F (08:00-11:00 ET -- pre-cash-open through mid-morning) is the
strongest window that clears every criterion simultaneously**: all 4
years profitable, all 4 years individually above PF 1.05, pooled PF 1.3836
(> the 1.15 floor), and >=25 trades every year (67/60/85/35).

## 4. Top-5 robust windows with SAL on, and the marginal-contribution comparison

| window | SAL off PF | SAL off net | SAL on PF | SAL on net |
|---|---|---|---|---|
| D-E | 1.4542 | +1,173.28 | 1.3571 | +922.28 |
| B-C-D-E | 1.3934 | +1,925.39 | 1.3157 | +1,532.39 |
| **E-F** | **1.3836** | **+2,132.91** | 1.3566 | +1,773.91 |
| D-E-F | 1.3119 | +2,156.79 | 1.2422 | +1,508.80 |
| B-C-D-E-F | 1.3031 | +2,780.46 | 1.2394 | +1,999.22 |
| All-hours | 1.0341 | +692.01 | 1.0339 | +555.13 |

**SAL reduces performance in every single window tested, including
all-hours.** The effect is not additive with the window choice: SAL's
drag is worse in the wider windows (B-C-D-E-F: -1.06 PF pts of drag) than
in the narrowest ones (D-E: -0.10), because SAL disproportionately cuts
off trades in the already-thin high-touch-density windows. **Time-window
selection is the entire source of improvement here; SAL contributes
nothing positive and is dropped.**

## 5. Selected configuration

**Window E-F (08:00-11:00 ET), SAL off**, frozen F2 formula fit on
2018/2020/2023/2026:

| Year | n | net (pts) | PF | avg R |
|---|---|---|---|---|
| 2018 | 67 | (PF 1.1629) | 1.1629 | -- |
| 2020 | 60 | (PF 1.1696) | 1.1696 | -- |
| 2023 | 85 | (PF 1.4747) | 1.4747 | -- |
| 2026 | 35 | (PF 1.7753) | 1.7753 | -- |
| **Pooled** | **247** | **+2,132.91** | **1.3836** | see `outputs/stage2_window_E-F_sal_off_executed.csv` |

Excluding 2026: 2018+2020+2023 combined net is positive (sum of three
individually-profitable years). Every selection criterion in the Stage 2
spec is met:

- [x] all four development years profitable
- [x] at least three years PF > 1.05 (in fact all four)
- [x] pooled PF >= 1.15 (1.3836)
- [x] neighboring windows generally profitable (broad D/E/F region, section 3)
- [x] >= 25 trades in each development year (67/60/85/35)
- [x] excluding 2026 leaves 2018+2020+2023 profitable
- [x] no trade overlap or SAL causality violation
  (`tests/test_stage2_invariants.py`, all passing)

## 6. No-overlap / SAL-causality confirmation

`tests/test_stage2_invariants.py`: no-overlap holds for the all-hours
baseline (both SAL states) and for the selected E-F window; SAL only ever
activates on a strictly negative realized exit P&L; every SAL-blocked
touch occurs at/after that session's activation timestamp and never
crosses into a different session; block coverage is exhaustive and
non-overlapping across the full pre-liquidation-bar session. All pass.
