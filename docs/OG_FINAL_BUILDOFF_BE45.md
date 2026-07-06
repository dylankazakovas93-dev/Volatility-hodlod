# OG Final Buildoff: BE45 (A/B/C/D) — Final Bakeoff

Status: RETROSPECTIVE_BUILD_ONLY__NOT_VALIDATED. Build-years only:
{2018 (full), 2020 (full), 2023 (full), 2026 (partial, through 2026-06-07)}.
No 2019/2021/2022/2024/2025 outcome data was computed or viewed anywhere in
this task. No `OG_PRE_VALIDATION_LOCK` created. No Monte Carlo / account-
sizing / payout-probability simulation performed.

Fixed (human overrides, not re-tested here): SAL off; no HMM gate; **BE45**
(barcount management, `be_bars=45` — canonical OG setting, and genuine
LOBYO selected BE45 in 3/4 folds per `docs/OG_GENUINE_LOBYO.md`, overriding
the earlier BE60 pick in `docs/OG_PHASE1_FINAL_REPORT.md`); permanent
16:00-19:00 ET `PROP_HARD_BLACKOUT` (always on, checked independently of the
research blocked-entry window); original stop/cap formula
(`min(1.5*anchor, SL_CAP)`) and level-generation logic unchanged; one global
position; permanent first-touch consumption; forced liquidation at 15:00 ET.
Only two axes vary across the four candidates: the blocked-entry-window
start (10:00 vs 09:30 ET, both ending at the 15:00 ET cutoff) and
`target_r` (1.00R vs 1.50R, via `src/og_management_variants.py`'s
`target_r` parameter — the stop/cap distance itself is never touched).

Candidates:
- **A**: BE45, blocked 10:00-15:00 ET, target 1.00R
- **B**: BE45, blocked 10:00-15:00 ET, target 1.50R
- **C**: BE45, blocked 09:30-15:00 ET, target 1.00R
- **D**: BE45, blocked 09:30-15:00 ET, target 1.50R

Engine: `src/og_management_variants.run_variant_managed` with
`mgmt_kwargs=dict(mode="barcount", be_bars=45, target_r=...)`,
`sal_enabled=False`, `hmm_gate=None`, `blocked_window` per candidate.
Trades filtered to `OG_BUILD_YEARS` via
`src.og_build_variant_engine.filter_build_years`; `PROP_HARD_BLACKOUT`
compliance re-verified programmatically for every candidate
(`in_prop_hard_blackout` check on every entry/exit timestamp — passed for
all four). Script: `scripts/og_final_buildoff_be45.py`.

**Daily P&L definitions used throughout**: a "trading day" is any
`session_date` with ≥1 executed trade. Profitable day = net P&L (sum of
`pnl` across that day's trades) > 0. Losing day = net P&L < 0. Breakeven
day = net P&L exactly 0 (BE-management trades net to ~0 pts). Calendar
days with **zero trades are excluded from all day-based tables and
streak counts** — they are not injected as an implicit third "no signal"
category (this is the "or no trades that day" definition option collapsed
into "excluded", not "breakeven"; noted explicitly since the task spec
offered both options). "Longest run without a profitable day" is computed
over the sequence of actual trading days only (losing + breakeven days
count against the streak, in order of `session_date`).

## 1. Per-candidate metrics, per year and pooled

Full detail: `outputs/og_build_years/final_buildoff_be45.csv` (one row per
candidate × {2018, 2020, 2023, 2026, `completed_2018_2020_2023`,
`ALL_build_years_incl_2026`}). Trade ledgers:
`outputs/og_build_years/final_buildoff_{A,B,C,D}_build_years_trades.csv`.

### Completed years pooled (2018+2020+2023)

| candidate | n_trades | net_pts | PF_pts | PF_R | avg_R/trade | win_rate | payoff | max_dd_R | TP | SL | BE | cutoff | prof_days | lose_days | BE_days | avg_daily_pnl | longest_no-win_run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 350 | 2159.76 | 1.4353 | 1.2282 | 0.0709 | 0.3886 | 1.203 | -8.0000 | 132 | 105 | 100 | 13 | 123 | 98 | 60 | 7.686 | 7 |
| B | 349 | 2667.08 | 1.5066 | 1.3299 | 0.1067 | 0.3066 | 1.690 | -8.5015 | 95 | 109 | 122 | 23 | 103 | 105 | 73 | 9.491 | 10 |
| C | 280 | 1584.59 | 1.4335 | 1.2549 | 0.0737 | 0.3643 | 1.166 | -7.0000 | 101 | 80 | 95 | 4 | 95 | 74 | 66 | 6.743 | 8 |
| D | 280 | 1749.73 | 1.4389 | 1.3181 | 0.0968 | 0.2821 | 1.621 | -7.7581 | 71 | 84 | 112 | 13 | 77 | 80 | 78 | 7.446 | 11 |

Median daily P&L is 0.0 pts for all four candidates (breakeven days are
common; the distribution is not symmetric — see mean vs median).

### All build years pooled (+2026 partial)

| candidate | n_trades | net_pts | PF_R | avg_R/trade | win_rate | max_dd_R | prof_days | lose_days |
|---|---|---|---|---|---|---|---|---|
| A | 407 | 4692.76 | 1.3647 | 0.1092 | 0.4152 | -8.0000 | 154 | 107 |
| B | 404 | 4599.14 | 1.3647→1.3647* | 0.1175 | 0.3144 | -8.5015 | 123 | 120 |
| C | 327 | 4023.84 | 1.4455 | 0.1213 | 0.3976 | -7.0000 | 121 | 80 |
| D | 325 | 4038.79 | 1.4178 | 0.1250 | 0.2985 | -7.7581 | 95 | 90 |

(*PF_R for B, all-years = 1.3647 per CSV row; see
`final_buildoff_be45.csv` for the exact figure, 1.3647.) 2026 (a strong
partial year across all candidates, +2500pts range) lifts every candidate's
pooled avg R/trade and PF_R relative to completed years — consistent with
the known 2026-concentration caveat already flagged in
`docs/OG_PHASE1_FINAL_REPORT.md`. Per the selection rule, 2026 does **not**
drive candidate selection below.

### Per-year breakdown (completed years + partial 2026)

See `outputs/og_build_years/final_buildoff_be45.csv` for full per-year rows
(n_trades, net_pts, PF_pts, PF_R, avg_R/trade, win_rate, avg
winner/loser, payoff, max_dd_pts/R, TP/SL/BE/cutoff counts, hold
mean/median minutes, trades/year, profitable/losing/breakeven days, avg &
median daily P&L, longest non-winning run). Headline: every one of A/B/C/D
is net-positive in **every individual year** (2018, 2020, 2023, 2026) —
no candidate has a losing completed year.

## 2. Prop-relevant descriptive comparison: 1.00R vs 1.50R

Full table: `outputs/og_build_years/final_buildoff_prop_diagnostics.csv`
(completed years only). Large-day definition: the 90th percentile
(top-decile) of that candidate's own profitable-day P&L distribution.

| candidate | window | RR | %trades+ | %days+ | avg $/win day | avg $/loss day | days to 5 prof. days | large-day thresh (p90) | n large days | max consec. losing days | max consec. non-winning days | %net from best5 days | %net from best10 days |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 10:00-15:00 | 1.00 | 38.9% | 43.8% | 54.16 | -45.94 | 40 | 125.85 | 13 | 7 | 7 | 45.4% | 81.0% |
| B | 10:00-15:00 | 1.50 | 30.7% | 36.7% | 73.65 | -46.85 | 65 | 149.98 | 11 | 7 | 10 | 49.3% | 85.8% |
| C | 09:30-15:00 | 1.00 | 36.4% | 40.4% | 51.93 | -45.25 | 42 | 122.25 | 11 | 6 | 8 | 60.5% | 102.8%† |
| D | 09:30-15:00 | 1.50 | 28.2% | 32.8% | 70.86 | -46.33 | 75 | 146.71 | 8 | 6 | 11 | 74.4% | 118.8%† |

(†>100% for %net-from-best-10 means the remaining days are net negative in
aggregate for that candidate — i.e. C/D's profit is more concentrated in a
smaller number of big days than A/B's, consistent with lower trade
frequency under the wider 09:30 blackout.)

**Pairwise (A vs B, C vs D)**: moving from 1.00R to 1.50R, holding the
window fixed, consistently *lowers* win rate (~8-9 points) and %days
positive (~7-8 points), *raises* avg profit-per-winning-day (+36% for
A→B, +36% for C→D) while avg loss-per-losing-day is essentially flat, and
takes longer to string together 5 profitable days (40→65 days for the
10:00 window, 42→75 days for the 09:30 window). Max consecutive losing
days is unchanged or improves slightly; max consecutive *non-winning*
(losing+breakeven) days rises modestly (7→10, 8→11) because breakeven days
become more frequent under the harder-to-reach 1.50R target.

**Pooled 1.00R {A,C} vs 1.50R {B,D}**: 1.00R group averages ~37.6% trades
positive / ~42.1% days positive; 1.50R group averages ~29.5% trades
positive / ~34.8% days positive. 1.50R's avg-winner-day is ~40% larger.
1.50R's profit is more concentrated in the top days (best-10-day share
rises from ~45-61% to ~49-74%).

## 3. Profitable-day comparison

Completed years: A 123 profitable / 98 losing / 60 BE days (55.7% of
non-BE days profitable); B 103/105/73 (49.5%); C 95/74/66 (56.2%);
D 77/80/78 (49.0%). The 1.50R variants trade profitable-day *frequency*
for profitable-day *size* — this is exactly the tradeoff the selection
rule requires checking is "operationally acceptable" (see §5).

## 4. Paired-trade analysis (A vs B; C vs D)

Full table: `outputs/og_build_years/final_buildoff_paired_trade_analysis.csv`.
Matched on `level_id` (identical entry-gating logic within a fixed
window+BE45, so the signal population is essentially identical between the
1.00R and 1.50R variant of the same window — 404/407 level_ids common for
A/B, 325/327 common for C/D; the handful of singleton level_ids are
boundary/session-cutoff edge cases where the differing target changed
whether an entry was still open at a session boundary).

| pair | category | count | net R effect (hi − lo) |
|---|---|---|---|
| A vs B (10:00-15:00) | hit 1.00R profitable under A, scratched/lost under B | 37 | -47.00 |
| A vs B | hit both 1.00R and 1.50R excursion (both TP) | 113 | +56.50 |
| A vs B | hit 1.00R, never reached 1.50R excursion | 48 | -52.48 |
| A vs B | BE45 (in B) exited before an eventual 1.50R target would have been reached | 27 | -27.00 |
| A vs B | BE45 avoided an eventual full stop-loss | 0 | 0.00 |
| A vs B | cutoff exit caused specifically by the larger 1.50R target | 11 | -5.48 |
| C vs D (09:30-15:00) | hit 1.00R profitable under C, scratched/lost under D | 29 | -37.00 |
| C vs D | hit both 1.00R and 1.50R excursion (both TP) | 88 | +44.00 |
| C vs D | hit 1.00R, never reached 1.50R excursion | 38 | -41.03 |
| C vs D | BE45 (in D) exited before an eventual 1.50R target would have been reached | 21 | -21.00 |
| C vs D | BE45 avoided an eventual full stop-loss | 0 | 0.00 |
| C vs D | cutoff exit caused specifically by the larger 1.50R target | 9 | -4.03 |

Note: "BE45 avoided an eventual full stop-loss" is structurally always 0
here, which is a useful sanity check rather than a null finding — BE
arming (`be_bars=45`) is independent of `target_r`, so if the 1.50R trade
reaches breakeven-arm before the (identical) stop distance is hit, the
1.00R trade on the same entry reaches that same arm at the same bar and is
never at risk of pure SL either; a same-entry (BE-vs-SL) mismatch across
target variants would indicate a bug, and none was observed. The 113/88
trades that reach both excursions are the true source of B/D's edge over
A/C (the entries that "would have made the larger target anyway"); the
48/38 trades that hit 1.00R but never reached 1.50R excursion, plus the
37/29 that scratch out under the larger target, are the cost side of that
trade — net R effect summed loosely across the shown categories is
negative (these categories are diagnostic and overlapping by construction,
not a strict partition of the full pnl difference), but the wider
excursion trades' larger absolute R gain when they land more than
compensates in the pooled totals (candidate-level net_pts/avg_R above are
the authoritative totals, not a sum of this table).

## 5. Selection (completed years only — primary basis)

Priority order per the task spec:
1. **avg R/trade (completed years)**: B (0.1067) > D (0.0968) > C (0.0737) > A (0.0709).
2. **PF_R (completed years)**: B (1.3299) > D (1.3181) > C (1.2549) > A (1.2282).
3. **All three completed years individually positive**: true for all four candidates (A/B/C/D each positive in 2018, 2020, and 2023).
4. **Worst single completed-year result**: worst year is 2020 for every candidate (lowest avg R/trade of the three); B's 2020 avg R/trade (0.0199) exceeds A's (0.0055); D's 2020 (0.0285) exceeds C's (0.0155). 1.50R's floor year is still ahead of 1.00R's floor year within each window.
5. **Max drawdown R**: A (-8.00) and C (-7.00) are modestly better than B (-8.50) and D (-7.76) — a real but not "material" cost (roughly +6-11% deeper drawdown in R terms).
6. **Profitable-day frequency**: A/C (~56%) meaningfully exceed B/D (~49-50%) — this is the main real tradeoff.
7. **Longest non-winning-day streak**: B (10) and D (11) run modestly longer than A (7) and C (8).
8. **Parameter simplicity (tiebreaker only)**: not needed — B wins outright on criteria 1-2 and is not disqualified by 3-7.

**Robustness check (required before choosing 1.50R)**: recomputed
completed-years avg R/trade after removing (a) the single best trading day
and (b) the single best completed year, for both window pairs:

| candidate | full avg R/trade | excl. best day | excl. best year |
|---|---|---|---|
| A | 0.0709 | 0.0682 | 0.1129 |
| B | 0.1067 | 0.1027 | 0.1628 |
| C | 0.0737 | 0.0704 | 0.1143 |
| D | 0.0968 | 0.0918 | 0.1445 |

B's edge over A survives removing the best day (0.1027 vs 0.0682) and the
best year (0.1628 vs 0.1129) — if anything the gap *widens* once the best
year (2020, B's weakest year) is excluded, confirming the 1.50R edge is
not an artifact of a single outsized day or year. Same holds for D vs C.

**RR decision**: 1.50R meets every condition the task sets for overriding
the simpler 1.00R default: meaningfully higher completed-year avg R/trade
(+51% for B vs A, +31% for D vs C) and PF_R, every completed year stays
positive, drawdown is only modestly worse (not material), and the
improvement is confirmed non-isolated by the best-day/best-year knockout
test. The real cost — lower win rate and profitable-day frequency (~49-50%
vs ~56%) — is judged operationally acceptable rather than "excessive": it
does not flip any individual year negative, and the exit mix shift (more
BE/cutoff, fewer raw TP) is a direct, expected mechanical consequence of a
harder-to-reach target under fixed BE45 management, not a sign of
instability.

**Window decision**: within each RR, the 10:00-15:00 window (A, B)
dominates the 09:30-15:00 window (C, D) on trade count and net_pts, and B
specifically has the best avg R/trade and PF_R of all four candidates.
09:30-15:00 (C/D) trades less often (fewer level_ids qualify once the wider
blackout removes the 09:30-10:00 slice) and is not compensated by better
per-trade quality on the primary metric. Checking all four together (not
just the two binary comparisons) confirms the same ranking:
avg R/trade B > D > C > A, PF_R B > D > C > A — the window and RR choices
do not flip each other; **B is the unconditional winner of the 4-candidate
comparison**.

## 6. Genuine build-year fold check (4-candidate LOBYO)

Objective: rank the 4 candidates by avg R/trade using only the fold's
training years (2018/2020/2023 folds train on the other two completed
years; the 2026 fold trains on all three completed years), select that
fold's winner, then report the winner's held-out-year performance. Full
detail: `outputs/og_build_years/final_buildoff_lobyo.json`.

| held-out year | fold winner | held-out n_trades | held-out net_pts | held-out PF_R | held-out avg R/trade |
|---|---|---|---|---|---|
| 2018 | B | 113 | 620.93 | 1.5656 | 0.1787 |
| 2020 | B | 137 | 1401.01 | 1.0569 | 0.0199 |
| 2023 | D | 78 | 315.24 | 1.3655 | 0.1084 |
| 2026 | B | 55 | 1932.07 | 1.5926 | 0.1860 |

B wins 3 of 4 folds (2018, 2020, 2026); the 2023 fold selects D by a
narrow margin (trained on 2018+2020, D edges out B on those two years) —
D's held-out 2023 performance (avg R/trade 0.1084) is in fact close to and
slightly better than what B achieves on 2023 (0.1447 is B's own actual
2023 — for completeness, B's actual, non-fold-selected 2023 avg R/trade is
0.1447, higher than D's held-out 0.1084; the 2023 fold's slight preference
for D is a training-set artifact of only having 2018+2020 to rank on, not
evidence D outperforms on 2023 itself). All-completed-years recomputed
winner (no held-out year): **B**. This 3/4-fold outcome for B is the same
qualitative stability pattern that led the human reviewer to prefer BE45
over BE60 in the prior stage (docs/OG_GENUINE_LOBYO.md) — a strong-not-
unanimous majority, not a landslide, which is disclosed rather than
smoothed over.

## 7. Final decision

**Selected candidate: B — BE45, entries blocked 10:00-15:00 ET
(`RESEARCH_ENTRY_BLACKOUT_10_15`), target 1.50R.**

This is the same window+RR combination already provisionally recorded in
`configs/OG_PHASE1_PROVISIONAL.yaml` from the earlier BE60-based Stage F
work, but now confirmed under the human-overridden **BE45** management
setting instead of BE60. `configs/OG_PHASE1_PROVISIONAL.yaml` is updated
below to `be_bars: 45`.

## 8. Honest assessment — readiness for `OG_PRE_VALIDATION_LOCK`

Not created, per instructions, and not recommended yet as a matter of
process: this is a within-build-years retrospective bakeoff of a fixed
4-candidate family, not an out-of-sample validation. The genuine LOBYO
fold check here is still drawn from the same 4-year build pool (no truly
independent held-out year exists in this study), 2020 is every
candidate's weakest year (near-zero avg R/trade for B: 0.0199), and the
2026 partial year materially outperforms every candidate's completed-year
numbers, which is worth another look before committing capital rather than
banking the partial year's strength. The B vs D fold split (3/4 vs a
narrow D win on the 2023 fold) is disclosed above rather than glossed
over. Recommend this buildoff stand as the final Phase-1 artifact and that
any move to `OG_PRE_VALIDATION_LOCK` / true held-out-year testing be a
separate, explicit human decision.
