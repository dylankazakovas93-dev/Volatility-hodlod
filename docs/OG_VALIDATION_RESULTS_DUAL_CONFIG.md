# OG Dual-Config Validation Results

Executed under `docs/OG_VALIDATION_PROTOCOL_DUAL_CONFIG.md` and
`docs/OG_PRE_VALIDATION_DUAL_CONFIG_LOCK.json`, at runner commit
`b92b40221c953d5377f2ed4da51f5f87b6d12117`
(`OG_DUAL_VALIDATION_RUNNER_LOCK`). Command run exactly once (plus one
deterministic byte-for-byte rerun into a scratch directory, confirmed
identical, then discarded):

```
python3 scripts/og_validation_dual_config.py \
  --years 2019 2021 2022 2024 2025 \
  --config configs/OG_PRIMARY_150R.yaml \
  --config configs/OG_OPERATIONAL_100R.yaml \
  --out-dir outputs/og_validation/
```

No argument variation was used. No 2013-2015 data was accessed. No
Monte Carlo / Prop Lab / account-sizing simulation was run.

All metrics below were **recomputed directly from the saved ledger CSVs**
(`outputs/og_validation/OG_PRIMARY_150R_validation_trades.csv`,
`outputs/og_validation/OG_OPERATIONAL_100R_validation_trades.csv`), not
merely copied from the runner's in-process JSON -- the recomputation
matched the runner's own `validation_gate_results.json` exactly.

## Per-year and pooled metrics

### OG_PRIMARY_150R (target_r = 1.50)

| Year | n_trades | net_pts | total_R | PF_pts |
|---|---|---|---|---|
| 2019 | 124 | -415.82 | -22.6113 | 0.7206 |
| 2021 | 131 | 941.74 | 17.0524 | 1.3782 |
| 2022 | 125 | 1303.00 | 4.8785 | 1.4338 |
| 2024 | 117 | -441.80 | -12.9832 | 0.8766 |
| 2025 | 133 | 330.29 | 2.8139 | 1.0906 |
| **Pooled** | **630** | **1717.42** | **-10.8496** | **1.1209** (PF_R = 0.9579) |

Average R/trade (pooled): **-0.0172** (negative)
Total R excluding best year (2021): **-27.90**
Max single-year share of pooled positive net points: **50.6%** (2022)

### OG_OPERATIONAL_100R (target_r = 1.00)

| Year | n_trades | net_pts | total_R | PF_pts |
|---|---|---|---|---|
| 2019 | 124 | -500.01 | -24.5150 | 0.6463 |
| 2021 | 133 | 559.90 | 5.4139 | 1.2325 |
| 2022 | 125 | 1499.88 | 7.7375 | 1.5463 |
| 2024 | 117 | -433.72 | -12.0228 | 0.8699 |
| 2025 | 134 | 687.24 | 7.6897 | 1.1981 |
| **Pooled** | **633** | **1813.28** | **-15.6968** | **1.1356** (PF_R = 0.9353) |

Average R/trade (pooled): **-0.0248** (negative)
Total R excluding best year (2022): **-23.43**
Max single-year share of pooled positive net points: **54.6%** (2022)

## Gate checklist — OG_PRIMARY_150R

| # | Criterion | Value | Pass |
|---|---|---|---|
| 1 | All execution invariants pass (no overlap/no lookahead, deterministic rerun) | 45/45 invariant tests pass; byte-identical rerun | PASS |
| 2 | Pooled net points positive | 1717.42 | PASS |
| 3 | Pooled total cap-normalized R positive | -10.85 | **FAIL** |
| 4 | Pooled PF (points) >= 1.15 | 1.1209 | **FAIL** |
| 5 | Pooled PF (R) >= 1.05 | 0.9579 | **FAIL** |
| 6 | Average R/trade positive | -0.0172 | **FAIL** |
| 7 | At least 3 of 5 years positive in total R | 3 (2021, 2022, 2025) | PASS |
| 8 | At least 3 of 5 years PF (points) > 1.05 | 3 (2021, 2022, 2025) | PASS |
| 9 | Total R positive excluding best year | -27.90 | **FAIL** |
| 10 | At least 250 validation trades | 630 | PASS |
| 11 | No single year > 80% of pooled positive net points | 50.6% | PASS |

**OG_PRIMARY_150R: FAIL** (criteria 3, 4, 5, 6, 9 fail — 5 of 11 criteria fail)

## Gate checklist — OG_OPERATIONAL_100R

| # | Criterion | Value | Pass |
|---|---|---|---|
| 1 | All execution invariants pass (no overlap/no lookahead, deterministic rerun) | 45/45 invariant tests pass; byte-identical rerun | PASS |
| 2 | Pooled net points positive | 1813.28 | PASS |
| 3 | Pooled total cap-normalized R positive | -15.70 | **FAIL** |
| 4 | Pooled PF (points) >= 1.15 | 1.1356 | **FAIL** |
| 5 | Pooled PF (R) >= 1.05 | 0.9353 | **FAIL** |
| 6 | Average R/trade positive | -0.0248 | **FAIL** |
| 7 | At least 3 of 5 years positive in total R | 3 (2021, 2022, 2025) | PASS |
| 8 | At least 3 of 5 years PF (points) > 1.05 | 3 (2021, 2022, 2025) | PASS |
| 9 | Total R positive excluding best year | -23.43 | **FAIL** |
| 10 | At least 250 validation trades | 633 | PASS |
| 11 | No single year > 80% of pooled positive net points | 54.6% | PASS |

**OG_OPERATIONAL_100R: FAIL** (criteria 3, 4, 5, 6, 9 fail — 5 of 11 criteria fail)

## Family-level verdict

**`DUAL_CONFIG_FAIL`** — neither configuration passes the locked
validation gate. Per protocol §2, the research line stops here: no further
parameter search, no new candidate, no re-targeting of `target_r` to
"chase" the gate, and neither configuration proceeds to 2013-2015 testing
or Prop Lab comparison.

## Honest assessment

Both configs pass the "shape" criteria (7, 8, 10, 11: enough trades,
enough years profitable, no single year dominating) but fail every
R-normalized profitability criterion (3, 5, 6, 9) and narrowly fail the
points-based profit factor gate (4: 1.1209 and 1.1356, both just under the
1.15 threshold). This is not a marginal or ambiguous result to spin either
way:

- **Net points are positive** for both configs (+1717 and +1813 pts pooled)
  — on raw points alone this would look like a mild pass. But **R-normalized
  performance is negative** for both (-10.85R and -15.70R pooled, average
  R/trade -0.017 and -0.025). The discrepancy comes from 2019 and 2024
  being the two worst years by R (large stops relative to points lost),
  dragging cap-normalized R negative even while points stayed positive.
  This is exactly the kind of gap the R-normalized gates (3, 5, 6, 9) were
  designed to catch, and they did their job.
- The failure is not close to a coin-flip: PF_R is meaningfully below 1.0
  for both configs (0.958 and 0.935), meaning R-weighted losers outweighed
  R-weighted winners over the pooled validation years, not just barely.
  Criterion 9 (total R excluding best year) is deeply negative for both
  (-27.9R and -23.4R), showing the "3 of 5 years positive" result was
  driven by two very strong years (2021/2022) rather than broad
  consistency, and removing either's best year makes the picture clearly
  unprofitable.
- Points-based PF (criterion 4) missed narrowly (1.1209 vs 1.15 required,
  1.1356 vs 1.15 required) — this is the one criterion where "close" is a
  fair characterization, but it doesn't change the outcome since criteria
  3/5/6/9 fail by much wider margins.
- The two configs perform very similarly to each other on this gate (both
  fail the same 5 criteria, in the same direction), which is unsurprising
  since they differ only in `target_r` and share the same touch population,
  entry timing, and BE45 management. Neither is meaningfully more salvage
  -able than the other on this validation slice.
- This result should be read as: the build-year-selected strategy (winner
  of a 4-candidate bakeoff on 2018/2020/2023/2026) did not generalize to
  the held-out validation years on an R-normalized basis, despite
  remaining nominally profitable in raw points. That is a genuine,
  informative out-of-sample result, not a bug or a data problem — the
  engine invariants all passed, the deterministic rerun was byte-identical,
  and the per-year breakdown is internally consistent (e.g. 2019 and 2024
  are bad years for both configs, 2021/2022/2025 are good years for both,
  which is expected given they share the same touch population).

No further action is authorized per the protocol: both configs stop here.
