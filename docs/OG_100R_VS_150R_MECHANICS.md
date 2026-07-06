# Why OG_PRIMARY_150R and OG_OPERATIONAL_100R differ: paired-trade mechanics

Both configs share the identical signal population under this window+BE45
(same level generation, same anchor/cap, same entry gating) — the only
thing that varies is `target_r`. This document matches trades across the
two ledgers on `level_id` (identical entry-gating logic within a fixed
window+BE45, so the same entries qualify for both configs almost always)
and explains, mechanically, why the pooled results differ. Source:
`outputs/og_build_years/final_buildoff_paired_trade_analysis.csv`
(pair `A_vs_B_10_15`, i.e. `OG_OPERATIONAL_100R` vs `OG_PRIMARY_150R`),
already computed by the final bakeoff and re-verified in this session
against the two committed ledgers (no re-simulation performed).

## Matched population

404 `level_id`s common to both `OG_OPERATIONAL_100R` (407 total) and
`OG_PRIMARY_150R` (404 total); 3 `level_id`s appear only in
`OG_OPERATIONAL_100R`, 0 appear only in `OG_PRIMARY_150R`. The 3
singleton `level_id`s are boundary/session-cutoff edge cases where the
differing target changed whether an entry was still open at a session
boundary — not evidence of a differing entry-gating population.

## Category breakdown (net R effect = hi[1.50R] − lo[1.00R])

| category | count | net R effect |
|---|---|---|
| hit 1.00R profitable under 1.00R config, scratched/lost under 1.50R config | 37 | -47.00 |
| hit both 1.00R and 1.50R excursion (both would TP) | 113 | +56.50 |
| hit 1.00R, never reached 1.50R excursion | 48 | -52.48 |
| BE45 (under 1.50R) exited before an eventual 1.50R target would have been reached | 27 | -27.00 |
| BE45 avoided an eventual full stop-loss | 0 | 0.00 |
| cutoff exit caused specifically by the larger 1.50R target (would have been TP under 1.00R) | 11 | -5.48 |

**"BE45 avoided an eventual full stop-loss" is structurally always 0**:
BE arming (`be_bars=45`) depends only on price action relative to
entry/cap, not on `target_r` (see `docs/OG_DUAL_CONFIG_SPECIFICATION.md`
§3). If the 1.50R trade reaches its BE-arm checkpoint before the
(identical) stop distance is hit, the 1.00R trade on the same entry
reaches that same arm at the same bar and was never at risk of a pure SL
either. A same-entry BE-vs-SL mismatch across target variants would
indicate a bug; none was observed.

**The 113 trades that reach both excursions are the true source of
`OG_PRIMARY_150R`'s edge** over `OG_OPERATIONAL_100R` — entries that
"would have made the larger target anyway," each contributing an extra
0.5R (in absolute terms, 1.50R vs 1.00R, i.e. +0.50R * cap per trade,
summing to +56.50 net R across the 113). The cost side: 48 trades hit
1.00R but never reach 1.50R excursion (net -52.48R vs the 1.00R config's
outcome on the same entries), 37 trades that were profitable at the 1.00R
target instead get scratched or turn into losses under the larger target
(-47.00R), 27 trades get exited early by BE45 under the 1.50R config
before an eventual 1.50R hit that never materializes on the actual price
path examined here (-27.00R), and 11 trades that would have been a clean
TP under 1.00R instead run into the 15:00 ET cutoff under 1.50R (-5.48R).
These categories are diagnostic and overlapping by construction, not a
strict partition of the full pnl difference — the candidate-level
`net_pts`/`avg_R` figures in `docs/OG_PRIMARY_150R_BUILD_RESULTS.md` and
`docs/OG_OPERATIONAL_100R_BUILD_RESULTS.md` are the authoritative totals,
not a sum of this table. But the wider-excursion trades' larger absolute
R gain when they land does net out ahead in the pooled totals: completed
years cap_norm_R_total is 37.24R for `OG_PRIMARY_150R` vs 24.80R for
`OG_OPERATIONAL_100R`, and avg R/trade is 0.1067 vs 0.0709.

## Net R gained from larger winners vs. net R lost from reduced target-hit frequency

- Net R **gained** from the 113 trades that hit both excursions (the
  larger winners): **+56.50R**.
- Net R **lost** from reduced target-hit frequency and its downstream
  effects (48 hit-1.00R-never-1.50R, 37 scratched/lost, 27 BE45-exited-
  early, 11 cutoff-caused): **-47.00 - 52.48 - 27.00 - 5.48 = -131.96R**
  summed across these (overlapping, diagnostic) categories.
- These two figures are not directly subtractable into the pooled
  difference (the categories overlap and are not a strict partition — see
  above), but the direction is consistent with the pooled totals: despite
  the much larger nominal "cost" total, `OG_PRIMARY_150R`'s pooled
  completed-years total R (37.24R) exceeds `OG_OPERATIONAL_100R`'s
  (24.80R) because the 113 "both-hit" trades' *actual* pnl impact (not
  just their R-multiple label) is large in absolute points terms
  (avg_winner_pts 74.13 for B vs 52.36 for A), and because the diagnostic
  "cost" categories partly overlap with trades that are still net
  profitable or breakeven, not pure losses.

## Win-rate and profitable-day-rate differences (completed years)

| metric | OG_OPERATIONAL_100R (A) | OG_PRIMARY_150R (B) | difference (B - A) |
|---|---|---|---|
| win_rate | 0.3886 | 0.3066 | -0.0820 |
| profitable_days / (profitable+losing) | 123/(123+98)=55.7% | 103/(103+105)=49.5% | -6.2 pts |
| avg_daily_pnl | 7.686 | 9.491 | +1.805 |
| max_dd_R | -8.0000 | -8.5015 | -0.5015 (deeper) |
| longest_no-win_run | 7 | 10 | +3 days |
| avg winner (pts) | 52.359 | 74.130 | +21.771 |
| avg loser (pts) | -43.519 | -43.874 | -0.355 (essentially flat) |

`OG_PRIMARY_150R` trades winning-day *frequency* for winning-day *size*:
lower win rate and %days-positive, but a materially larger average winner
and higher average daily P&L; loss size is essentially unchanged. Max
drawdown is modestly deeper for `OG_PRIMARY_150R` (-8.50R vs -8.00R) and
its longest non-winning-day streak is longer (10 vs 7 days).

## Three lenses — these can and do rank differently

- **Strategy expectancy (per-trade / per-R)**: `OG_PRIMARY_150R` wins.
  Higher completed-years avg R/trade (0.1067 vs 0.0709) and PF_R (1.3299
  vs 1.2282); this is the primary basis on which it won the preregistered
  bakeoff.
- **Daily smoothness**: `OG_OPERATIONAL_100R` wins. Higher win rate,
  higher %profitable-days, shallower drawdown, shorter longest
  non-winning-day streak, and profit that is less concentrated in a
  handful of best days (45.4% vs 49.3% of net points from the best 5
  days, per `docs/OG_FINAL_BUILDOFF_BE45.md` §2).
- **Prop-account usability**: likely favors `OG_OPERATIONAL_100R` under
  typical funded-account rules that reward consistency (minimum
  profitable-days requirements, maximum-drawdown limits, day-to-day
  variance caps) — though this has not been formally tested against any
  specific prop-firm ruleset in this task (no Prop Lab / account-sizing
  simulation was run here, per the data firewall).

These three lenses do not have to agree, and here they do not:
`OG_PRIMARY_150R` is primary because it wins on strategy expectancy (the
preregistered selection criterion), while `OG_OPERATIONAL_100R` is
retained precisely because it may be preferable on the other two lenses.
Neither ranking overrides the other; both configs proceed to validation
independently (`docs/OG_VALIDATION_PROTOCOL_DUAL_CONFIG.md`).
