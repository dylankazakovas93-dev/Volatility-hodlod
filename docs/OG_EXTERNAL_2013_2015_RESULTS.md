# OG External 2013-2015 Diagnostic Results

Phase label: `POST_VALIDATION_EXTERNAL_DIAGNOSTIC_2013_2015`. Diagnostic
only. Does **not** amend, reverse, or reinterpret the locked-validation
verdict `DUAL_CONFIG_FAIL` (`docs/OG_VALIDATION_RESULTS_DUAL_CONFIG.md`,
commit `add8f30`).

Produced by exactly one execution of
`scripts/og_external_2013_2015_dual_config.py` (runner-lock commit
`13db0fb014e8c1af6e6d45638f9bd09d77e81082`):

```
python3 scripts/og_external_2013_2015_dual_config.py --years 2013 2014 2015 \
  --config configs/OG_PRIMARY_150R.yaml --config configs/OG_OPERATIONAL_100R.yaml \
  --bars data/external_2013_2015/normalized/nq_continuous_2013_2015_1m.csv \
  --vxn data/external_2013_2015/normalized/vxn_daily_2012warmup_2015.csv \
  --out-dir outputs/og_external_2013_2015/
```

Deterministic-rerun check: the same command was re-run into a scratch
directory. `primary_150r_trades.csv` and `operational_100r_trades.csv`
were byte-identical between the two runs (verified with `diff`); the only
difference in `gate_results.json` was the `ledger_path` string, which
necessarily differs because it records the (different) `--out-dir`. Ledger
sha256:
- `primary_150r_trades.csv`: `ecd80629a36114ba6a86915e4cc3a807736f7619b63bfbdcac1ba92a7c3ec5b0`
- `operational_100r_trades.csv`: `5929f1ec49984661b6cdd41ee60d0e466dc3aa3f615856b7a14d1928a478bce5`

## First eligible traded date

`2013-01-07` (first executed trade date under identical eligibility
mechanics for both configs; 2013-01-01 through 2013-01-04 sessions did not
produce an executed trade under the existing gates -- this is read directly
off the produced ledger, not re-derived).

## Pooled 2013-2015 results

| metric | OG_PRIMARY_150R | OG_OPERATIONAL_100R |
|---|---|---|
| eligible trades | 315 | 315 |
| net points | -45.69 | -261.61 |
| PF (points) | 0.9690 | 0.8193 |
| total cap-normalized R | 3.0254 | -17.4414 |
| PF (R) | 1.0232 | 0.8618 |
| avg R/trade | 0.0096 | -0.0554 |
| win rate | 0.3048 | 0.3556 |
| avg winner (pts) | 14.889 | 10.591 |
| avg loser (pts) | -10.846 | -11.052 |
| payoff ratio | 1.3728 | 0.9583 |
| max drawdown (pts) | -318.36 | -385.17 |
| max drawdown (R) | -28.8973 | -37.5226 |
| TP / SL / BE / cutoff | 84 / 127 / 83 / 21 | 107 / 123 / 72 / 13 |
| mean holding (min) | 129.57 | 106.99 |
| median holding (min) | 63.0 | 58.0 |
| profitable days | 91 | 101 |
| losing days | 114 | 109 |
| breakeven days | 61 | 56 |
| longest non-winning-day run | 15 | 10 |

"Excluded warmup sessions": the 2012-06-01..2012-12-31 VXN rows exist only
as a causal lookup and produced zero traded rows in either ledger (both
ledgers' `year` column contains only 2013/2014/2015 -- verified by the
runner's fail-closed no-2012-leak assertion, which did not fire).

## Year-by-year

| config | year | trades | net pts | PF pts | total R | PF R | avg R/trade | win rate | max DD pts | max DD R | profit/loss/BE days |
|---|---|---|---|---|---|---|---|---|---|---|---|
| PRIMARY_150R | 2013 | 86 | 115.21 | 1.4842 | 20.1281 | 1.7723 | 0.2340 | 0.3721 | -49.50 | -5.0000 | 30/22/22 |
| PRIMARY_150R | 2014 | 109 | -104.86 | 0.7934 | -15.6199 | 0.7155 | -0.1433 | 0.2752 | -167.79 | -19.9783 | 28/47/18 |
| PRIMARY_150R | 2015 | 120 | -56.04 | 0.9232 | -1.4827 | 0.9700 | -0.0124 | 0.2833 | -233.25 | -12.4190 | 33/45/21 |
| OPERATIONAL_100R | 2013 | 86 | 57.21 | 1.2536 | 12.9373 | 1.5377 | 0.1504 | 0.4302 | -53.79 | -4.0000 | 34/19/21 |
| OPERATIONAL_100R | 2014 | 109 | -182.41 | 0.6379 | -23.3153 | 0.5674 | -0.2139 | 0.3028 | -216.91 | -27.4149 | 30/46/17 |
| OPERATIONAL_100R | 2015 | 120 | -136.41 | 0.8101 | -7.0635 | 0.8537 | -0.0589 | 0.3500 | -194.51 | -11.1077 | 37/44/18 |

Only 2013 is positive in every metric for both configs; 2014 and 2015 are
both negative in net points, PF (points), and total R for both configs.

## Monthly diagnostics (descriptive; see `outputs/og_external_2013_2015/monthly_summary.csv` for all 36 months x 2 configs)

**OG_PRIMARY_150R**: best month 2015-12 (+50.79 pts), worst month 2015-03
(-48.00 pts). Pooled net excluding the best month: -96.48 pts (i.e. more
negative than the pooled total -- the best single month is propping up an
otherwise worse result). Best-3-months sum = 37.6% of total *positive*
monthly net points. 20 positive months / 16 negative months out of 36.

**OG_OPERATIONAL_100R**: best month 2015-06 (+48.75 pts), worst month
2015-09 (-62.91 pts). Pooled net excluding the best month: -310.35 pts.
Best-3-months sum = 56.0% of total positive monthly net points. 12 positive
months / 24 negative months out of 36.

Neither figure implies any parameter selection or optimization; these are
purely descriptive concentration checks required by the protocol's gate
criterion 13.

## Paired 1.00R vs 1.50R comparison (matched on shared `level_id`)

All 315 `level_id`s are shared between the two ledgers (both configs touch
identical levels/times; only the target distance differs).

| metric | value |
|---|---|
| shared level IDs | 315 |
| trades where 1.00R hits TP but 1.50R doesn't | 23 |
| trades where both hit TP | 84 |
| trades where 1.50R hits TP but 1.00R doesn't | 0 (mechanically impossible: 1.00R's target is closer) |
| trades where 1.50R produces a larger cutoff gain (both cutoff) | 0 |
| trades where 1.50R converts a 1.00R winner into BE/cutoff/loss | 16 |
| net R gained from 1.50R's larger winners | +42.0459 R |
| net R lost from 1.50R's lower target-hit rate | -21.5791 R |
| win-rate difference (150R - 100R) | -0.0508 |
| profitable-day-rate difference (150R - 100R) | -0.0376 |
| max-drawdown-pts difference (150R - 100R) | +66.81 (150R's drawdown is 66.81 pts *shallower*, i.e. less negative) |
| longest non-winning-day streak, 150R | 15 |
| longest non-winning-day streak, 100R | 10 |
| streak difference (150R - 100R) | +5 |

No winner is picked from this comparison per protocol; both configs are
net negative in points pooled 2013-2015, and 1.50R's larger per-winner size
does not fully offset its lower hit rate on this window (net R effect of
switching target from 1.00R to 1.50R on the shared trade set: +42.05 R
gained - 21.58 R lost on the sub-populations where the two diverge, but
`OG_OPERATIONAL_100R`'s pooled total_R is still more negative overall
because its baseline win-rate/PF differ from `OG_PRIMARY_150R` beyond just
the shared-trade divergence set -- both are reported, neither is declared
better).

## External-support gate result (13 criteria, applied independently)

**OG_PRIMARY_150R: NO_EXTERNAL_SUPPORT** (7 of 13 pass)

| # | criterion | value | pass |
|---|---|---|---|
| 1 | invariants pass | -- | PASS |
| 2 | deterministic rerun byte-identical | -- | PASS |
| 3 | pooled net points positive | -45.69 | FAIL |
| 4 | pooled total R positive | 3.0254 | PASS |
| 5 | pooled PF points >= 1.10 | 0.9690 | FAIL |
| 6 | pooled PF R > 1.00 | 1.0232 | PASS |
| 7 | avg R/trade positive | 0.0096 | PASS |
| 8 | >=2/3 years positive total R | 1/3 | FAIL |
| 9 | >=2/3 years PF pts > 1.00 | 1/3 | FAIL |
| 10 | pooled R positive excl. best year | -17.10 | FAIL |
| 11 | >=150 eligible trades | 315 | PASS |
| 12 | no year > 80% of pooled positive net pts | 100% (2013 supplies all positive net pts) | FAIL |
| 13 | not entirely from one month | 15.7% max share | PASS |

**OG_OPERATIONAL_100R: NO_EXTERNAL_SUPPORT** (5 of 13 pass)

| # | criterion | value | pass |
|---|---|---|---|
| 1 | invariants pass | -- | PASS |
| 2 | deterministic rerun byte-identical | -- | PASS |
| 3 | pooled net points positive | -261.61 | FAIL |
| 4 | pooled total R positive | -17.4414 | FAIL |
| 5 | pooled PF points >= 1.10 | 0.8193 | FAIL |
| 6 | pooled PF R > 1.00 | 0.8618 | FAIL |
| 7 | avg R/trade positive | -0.0554 | FAIL |
| 8 | >=2/3 years positive total R | 1/3 | FAIL |
| 9 | >=2/3 years PF pts > 1.00 | 1/3 | FAIL |
| 10 | pooled R positive excl. best year | -30.38 | FAIL |
| 11 | >=150 eligible trades | 315 | PASS |
| 12 | no year > 80% of pooled positive net pts | 100% (2013 supplies all positive net pts) | FAIL |
| 13 | not entirely from one month | 22.1% max share | PASS |

## Family-level classification

**`EXTERNAL_DUAL_NO_SUPPORT`** -- neither config clears the fixed
13-criterion external-support gate on the 2013-2015 window. This is a
diagnostic finding about an out-of-sample-by-construction historical
window; it does not reverse `DUAL_CONFIG_FAIL` from the locked 2019/2021/
2022/2024/2025 validation, and it is not pooled with any other year group
(see comparison doc).
