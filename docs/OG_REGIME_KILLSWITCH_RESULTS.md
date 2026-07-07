# OG Regime Kill-Switch — Backtest Results

## HONESTY CAVEAT — READ FIRST

**This entire study is a retrospective fit on already-viewed data.** The
locked validation years (2019/2021/2022/2024/2025) and the external years
(2013/2014/2015) were both already run and diagnosed in this research line
before this kill-switch study began
(`docs/OG_VALIDATION_RESULTS_DUAL_CONFIG.md` -> `DUAL_CONFIG_FAIL`;
`docs/OG_EXTERNAL_2013_2015_RESULTS.md` -> `EXTERNAL_DUAL_NO_SUPPORT`). Any
threshold or window that "looks good" below was selected by looking at
exactly the years it needs to detect trouble in. **This is not a fresh,
preregistered, out-of-sample validation of a kill-switch rule** — it is
monitoring-mechanism research conducted on data that has already been
opened. Nothing below should be read as "this kill-switch passed
validation." A genuinely fair test would require fresh future data the
selected rule has never seen. Treat every number here as diagnostic evidence
about *whether this class of mechanism is worth carrying forward*, not as
proof that a specific threshold will work live.

## Data assembled

Full chronological trade sequences (see
`scripts/og_regime_killswitch_assemble.py`,
`outputs/og_regime_killswitch/{config}_full_chronological_trades.csv`):

| Config | n_trades | Span | Years present | Gap |
|---|---|---|---|---|
| OG_PRIMARY_150R | 1349 | 2013-01-07 .. 2026-06-05 | 2013,2014,2015,2018,2019,2020,2021,2022,2023,2024,2025,2026 | 2016,2017 absent (never computed in this line, not fabricated) |
| OG_OPERATIONAL_100R | 1355 | 2013-01-07 .. 2026-06-05 | same | same |

No duplicate `(level_id, entry_time)` pairs found across the three source
extracts (external / build-years / validation) per config — verified
programmatically in the assembly script (hard assertion, not eyeballed).

## Mechanism families tested

See `docs/OG_REGIME_KILLSWITCH_MECHANISMS.md` for full specifications. Full
per-variant results: `outputs/og_regime_killswitch/killswitch_summary.csv`
(62 rows: 2 baselines + 30 non-baseline variants x 2 configs) and
`killswitch_summary_full.json` (adds per-bad-period and per-good-period
breakdowns and flat-run statistics for every row).

### Baseline (always-on, no kill-switch)

| Config | n | net_pts | total_R | PF_pts | PF_R | avg_R/trade | max_dd_R |
|---|---|---|---|---|---|---|---|
| PRIMARY_150R | 1349 | 6270.87 | 39.65 | 1.278 | 1.076 | 0.0294 | -28.90 |
| OPERATIONAL_100R | 1355 | 6244.43 | 11.31 | 1.299 | 1.023 | 0.0084 | -45.91 |

### Mechanism 1 (rolling PF) — best variants per config

| Config | window | threshold | re-entry | net_pts | total_R | PF_R | avg_R/trade | max_dd_R | n_flat | n_runs |
|---|---|---|---|---|---|---|---|---|---|---|
| PRIMARY_150R | 100 | 1.10 | symmetric | 6004.89 | **69.63** | **1.234** | **0.0516** | **-14.53** | 512 | 8 |
| OPERATIONAL_100R | 100 | 1.10 | symmetric | 6738.19 | **62.24** | **1.249** | **0.0459** | **-10.97** | 575 | 20 |

These are the best rolling-PF variants by PF_R for each config, and in fact
the best-performing variant across **all four mechanism families** for both
configs. Full 24-variant grid per config is in the CSV; qualitatively,
`window=100` with `threshold=1.0-1.1` dominates most other combinations, and
`window=200` performs worse or even negative (it reacts too slowly and stays
flat through parts of the good periods without fully avoiding the bad ones).

### Mechanism 2 (rolling diagnostics) — overlay, not a standalone switch

Written to `outputs/og_regime_killswitch/{config}_rolling_diagnostics.csv`
for windows {50,100,150,200}. Inspecting the trailing win-rate and
trailing-avg-R columns around the 2014-2015, 2019, and 2024 windows shows
both are depressed simultaneously (not a pure win-rate story or a pure
payoff story) — consistent with the earlier validation/external docs'
characterization of these as broad regime deteriorations rather than a
single failure mode. No separate kill-switch was built from this overlay,
per the reasoning in the mechanisms doc (redundant with rolling PF for a
fixed-target-R strategy).

### Mechanism 3 (CUSUM) — best variant per config

| Config | k | h | cooldown | net_pts | total_R | PF_R | avg_R/trade | max_dd_R | n_flat | n_runs |
|---|---|---|---|---|---|---|---|---|---|---|
| PRIMARY_150R | 0.497 | 2.236 | 30 | 4606.14 | 38.41 | 1.090 | 0.0285 | -29.69 | 242 | 9 |
| OPERATIONAL_100R | 0.426 | 1.916 | 50 | 3590.65 | 25.37 | 1.104 | 0.0187 | -20.64 | 644 | 13 |

CUSUM helps directionally (PF_R and avg_R/trade both improve vs. baseline
for both configs) but is clearly weaker than rolling PF at every comparable
cooldown, and for PRIMARY_150R the best CUSUM total_R (38.4) is still below
the best rolling-PF total_R (69.6). It also produces a worse max_dd_R for
PRIMARY_150R (-29.69 vs baseline -28.90 — essentially a wash) because its
reset-after-alarm recursion needs a large sustained shift before firing.

### Mechanism 4 (non-winning streak vs. build-year baseline) — weak/negative

| Config | percentile | threshold_len | net_pts | total_R | PF_R | avg_R/trade | max_dd_R | n_flat |
|---|---|---|---|---|---|---|---|---|
| PRIMARY_150R | 90 | 7.0 | 2442.79 | -10.78 | 0.962 | -0.0080 | -34.95 | 649 |
| PRIMARY_150R | 95 | 8.85 | 2029.04 | -19.03 | 0.937 | -0.0141 | -39.92 | 597 |
| PRIMARY_150R | 99 | 11.34 | 4966.40 | 14.95 | 1.038 | 0.0111 | -30.55 | 326 |
| OPERATIONAL_100R | 90 | 5.0 | 3742.22 | 8.38 | 1.026 | 0.0062 | -39.71 | 483 |
| OPERATIONAL_100R | 95 | 7.0 | 4308.50 | -8.04 | 0.980 | -0.0059 | -57.58 | 237 |
| OPERATIONAL_100R | 99 | 8.06 | 5360.69 | 2.27 | 1.005 | 0.0017 | -55.16 | 127 |

This mechanism **does not clearly help and sometimes actively hurts**
(PF_R below 1.0, worse than baseline, at the 90th/95th percentile for
PRIMARY_150R and 95th for OPERATIONAL_100R). Non-winning streaks in this
strategy are apparently not a reliable leading indicator distinct from what
rolling PF already captures — a build-year-length-7-8 non-winning streak is
common enough in normal operation that gating on it mostly just adds
whipsaw and unnecessary flat time without preferentially avoiding the
2014-2015/2019/2024 windows. Not selected for either config.

## Bad-period-avoidance breakdown for the selected mechanism (rolling PF, window=100, threshold=1.10, symmetric re-entry)

### PRIMARY_150R

| Period | Baseline total_R | With kill-switch total_R | Baseline max_dd_R | With kill-switch max_dd_R | n_flat_trades (of n in period) |
|---|---|---|---|---|---|
| 2014-2015 | -17.10 | **-8.35** | -28.90 | -9.21 | 182 / 229 |
| 2019 | -22.61 | **-9.29** | -25.86 | -12.54 | 64 / 124 |
| 2024 | -12.98 | **-2.15** | -15.63 | -5.00 | 96 / 117 |

### OPERATIONAL_100R

| Period | Baseline total_R | With kill-switch total_R | Baseline max_dd_R | With kill-switch max_dd_R | n_flat_trades (of n in period) |
|---|---|---|---|---|---|
| 2014-2015 | -30.38 | **-1.90** | -37.52 | -2.90 | 209 / 229 |
| 2019 | -24.51 | **-5.65** | -25.86 | -5.65 | 81 / 124 |
| 2024 | -12.02 | **-3.15** | -14.88 | -5.00 | 91 / 117 |

Every one of the three previously-diagnosed bad periods is substantially
softened (losses cut roughly by half to nearly all the way to flat) under
this mechanism, for both configs, driven by extended flat stretches
(8 flat runs for PRIMARY_150R over the full history, 20 for
OPERATIONAL_100R — i.e. it is not one lucky single trigger coinciding with
one bad year by chance; it fires and holds through much of each of the
three separate bad windows independently).

## Good-period cost breakdown

### PRIMARY_150R

| Period | Baseline total_R | With kill-switch total_R | n_flat_trades (of n) |
|---|---|---|---|
| 2013 | 20.13 | 20.13 | 0 / 86 (never triggered) |
| 2018/2020/2023/2026 (build) | 47.47 | 42.85 | 55 / 404 |
| 2021/2022/2025 (validation) | 24.74 | **26.43** (improved) | 115 / 389 |

### OPERATIONAL_100R

| Period | Baseline total_R | With kill-switch total_R | n_flat_trades (of n) |
|---|---|---|---|
| 2013 | 12.94 | 12.94 | 0 / 86 (never triggered) |
| 2018/2020/2023/2026 (build) | 44.45 | 37.05 | 50 / 407 |
| 2021/2022/2025 (validation) | 20.84 | **22.95** (improved) | 144 / 392 |

The build-year cost is real but modest (roughly 10-17% of build-year total_R
given up to unnecessary flat time), and is more than offset in the pooled
totals by the much larger bad-period improvement; the mechanism did not
trigger at all in 2013 (the one external year that was actually positive),
and it slightly *improved* the 2021/2022/2025 validation-year total despite
those years being net positive at baseline — evidence it is not simply
"always flat = safer," it is responding to real trailing-PF deterioration
that also exists briefly within otherwise-good years.

## Selection criteria (stated before selecting)

Per the task's instructions, the selection prioritizes: (1) PF_R and avg
R/trade improvement over raw points, (2) the improvement must hold across
all three previously-diagnosed bad periods, not just one, (3) the mechanism
must not meaningfully damage the good-period (build-year) outcome, and
(4) triggering must look like a genuine, generalizable response to trailing
deterioration (multiple independent flat runs spread across the bad
periods) rather than one lucky window that happens to overlap a bad year's
exact boundary.

## Final selection

**Rolling PF, window=100 trades, threshold=1.10, symmetric re-entry** is
selected as the best-performing mechanism+parameter combination for **both**
`OG_PRIMARY_150R` and `OG_OPERATIONAL_100R`:

- PF_R improves from 1.076 -> 1.234 (PRIMARY_150R) and 1.023 -> 1.249
  (OPERATIONAL_100R).
- avg R/trade improves from 0.029 -> 0.052 (PRIMARY_150R) and 0.008 -> 0.046
  (OPERATIONAL_100R).
- max_dd_R shrinks from -28.90 -> -14.53 (PRIMARY_150R) and -45.91 -> -10.97
  (OPERATIONAL_100R).
- All three bad periods are meaningfully softened, independently, via 8
  (PRIMARY_150R) / 20 (OPERATIONAL_100R) distinct flat runs — not a single
  coincidental overlap.
- The good-period build-year cost is real (10-17% of build-year total_R)
  but smaller than the bad-period benefit, and the 2021/2022/2025
  validation-year outcome is not hurt (slightly improved).

CUSUM (cooldown=30-50) is a distant second — directionally correct but
weaker on every metric — and the non-winning-streak mechanism does not
clearly earn its keep (PF_R below 1.0 at several parameter settings) and is
**not selected** for either config.

**Reiterating the caveat: this selection is a retrospective best-fit choice
among the 24 rolling-PF variants tried, made after already knowing which
years were bad. It has not been tested on any data unseen by this research
line. If this mechanism is ever taken forward operationally, it should be
tested going forward on genuinely new data before being trusted, exactly
like the underlying strategy itself was supposed to be.**
