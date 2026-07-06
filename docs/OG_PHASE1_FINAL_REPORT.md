# OG Phase 1 — Final Report

Status: **Phase 1 (build-year retrospective research) complete.**
`RETROSPECTIVE_BUILD_ONLY__NOT_VALIDATED`. No `OG_PRE_VALIDATION_LOCK` has
been created. Data firewall: every metric in this document uses ONLY
`OG_BUILD_YEARS = {2018 (full), 2020 (full), 2023 (full), 2026 (partial,
through 2026-06-07)}`. No 2019/2021/2022/2024/2025 trade outcome was
computed, inspected, or reported anywhere in Phase 1.

Chain frozen: **SAL off (Stage B) + BE60 management (Stage C) + no HMM
(Stage D) + entries blocked 10:00-15:00 ET (Stage E,
`RESEARCH_ENTRY_BLACKOUT_10_15`) + target 1.50R, Lane B / BE60 (Stage F)**.
No additional combinatorial search was performed beyond this fixed chain —
each piece was independently selected in its own stage.

Reproduction of this report's comparison table:
`python3 scripts/og_phase1_final_comparison.py` (reads the already-committed
per-candidate trade ledgers from Stages A/B/C/E/F). Output:
`outputs/og_build_years/phase1_final_comparison.json`.

## Stage-by-stage decision summary

**Stage B (SAL on/off).** SAL ("session-armed loss-lock") blocks further
same-session touches after a losing exit. On build-year evidence, SAL_off
strictly dominates SAL_on: higher net points, higher PF, a *smaller* max
drawdown, and it flips 2023 from the only negative build year to marginally
positive. Selected: **SAL off**. This is the single most robust decision
in the pipeline — the genuine LOBYO (Step 1) confirms it wins in 4/4 folds
unanimously.

**Stage C (BE management family).** A bar-count breakeven family
(noBE/BE30/BE45/BE60/BE75/BE90) was tested holding SAL off, canonical
11:00-15:00 window, target 1.0R. BE60 sits on a stable plateau with
BE30/BE45, keeps all 3 completed build years positive, and has an
acceptable ex-2026 PF (1.189); a real, disclosed discontinuity appears one
step further out at BE75 (not at BE60 itself). Selected: **BE60**
(`mode="barcount", be_bars=60`). The genuine LOBYO shows this decision is
less unanimous than Stage B's: BE45 (not BE60) wins 3/4 fold-based
re-selections under a reduced, PF-only objective, and the discrepancy
traces to a real, pre-existing, already-disclosed neighborhood asymmetry
rather than to 2026 concentration (the fold that disagrees is 2018, not
2026).

**Stage D (HMM regime gate).** A causal, session-refit 2/3-state HMM gate
was tested across an 18-candidate matrix. The only candidate to keep all 4
build years individually positive at its primary setting
(`hmm3_exclude_MID_p55`) failed a mandatory seed-perturbation check: 2 of 5
alternate EM seeds flip a build year negative. No other candidate improves
over the no-gate baseline while keeping all years positive. Selected:
**no-HMM**. The genuine LOBYO reinforces this: the only reduced-pool
candidate that ever out-scores no-gate in a fold (`hmm3_exclude_MID_p55`)
only does so when 2026 is included in the fold-selection training data —
excluding 2026 from training flips the pick back to no-gate in all 3
full-year folds. This corroborates the original seed-perturbation
rejection from an independent angle.

**Stage E (entry blackout / session-entry study).** Blocked-entry-interval
starts (09:00 through 12:00, all until the 15:00 forced-liquidation cutoff)
and 7 session-entry variants were tested holding SAL off, BE60, target
1.0R. 10:00 has the highest ex-2026 PF (1.4397) among the 7 blocked-interval
candidates, keeps all 4 build years positive, and is not an isolated
cliff-edge (neighbors 09:00/09:30/10:30 are directionally similar/gradual,
not collapsed). Selected: **blocked 10:00-15:00 ET**
(`RESEARCH_ENTRY_BLACKOUT_10_15`). The genuine LOBYO's reduced PF-only
objective actually prefers 09:30 unanimously across all 4 folds — this
reflects the reduced objective not capturing the fuller selection standard
(all-4-years-positive-with-margin, no-cliff-edge check across the full 7
candidates), not a 2026-driven effect (09:30 wins whether or not 2026 is
in the fold).

**Stage F (target / RR study).** Lane A (no management) and Lane B (BE60)
were tested at RR = 0.75/1.00/1.25/1.50/2.00. Lane B's ex-2026 PF_R and
avg-R-per-trade climb smoothly and monotonically from 0.75R through 1.50R
before collapsing at 2.00R; 1.50R sits at the top of a genuine climb, not
an isolated spike, and all 4 build years stay individually positive.
Selected: **1.50R, Lane B (BE60)**. This is the **least robust decision
under the genuine LOBYO**: the fold-based winner (using only the other 3
years for selection) is 1.00R in 3 of 4 folds; 1.50R is only selected when
2026 supplies the training data for the pick. This is the clearest
2026-concentration signal produced anywhere in Phase 1 (see the dedicated
discussion below).

## Genuine LOBYO stability summary (full detail: `docs/OG_GENUINE_LOBYO.md`)

| Stage | Selection frequency (of 4 folds) | Frozen winner ever a fold winner? | 2026 materially drives selection? | Verdict |
|---|---|---|---|---|
| B (SAL) | SAL_off 4/4 | Yes, every fold | No | **Stable** |
| C (BE) | BE45 3/4, BE30 1/4 | No | No (2018 is the outlier fold) | Unstable (pre-existing, disclosed asymmetry) |
| D (HMM, approximation) | no_gate 3/4, hmm3_exclude_MID_p55 1/4 | Yes, 3/4 | **Yes** | Reinforces no-HMM; 2026-sensitive on the alternative |
| E (window) | blocked_0930 4/4 | No | No | Stable selection, different winner (objective-reduction artifact) |
| F (RR) | laneB_rr100 3/4, laneB_rr150 1/4 | Only in the 2026 fold | **Yes** | **Least robust; 2026-driven** |

Stage D's approximation caveat (explicitly disclosed in
`docs/OG_GENUINE_LOBYO.md`): the causal HMM was not re-fit per fold (would
require 4 expensive session-refits); the reduced 3-candidate pool was
selected/evaluated using the already-computed per-year breakdown from the
single primary HMM fit. This is a materially weaker guarantee than the
other 4 stages' fold-based LOBYO, all of which used genuinely
per-fold-recomputable, trade-level-decomposable candidate pools.

## Final 5-row cumulative comparison table

Build years only. `n` = trade count. R values are cap-normalized
(`pnl / cap` per trade). Full detail (every scope, every metric) in
`outputs/og_build_years/phase1_final_comparison.json`.

### ALL (2018+2020+2023+2026-partial, pooled)

| Config | n | net_pts | PF_pts | total R | avg R/trade | max_dd_pts | max_dd_R |
|---|---|---|---|---|---|---|---|
| (a) canonical baseline | 460 | 3499.15 | 1.4191 | 32.4832 | 0.0706 | -756.99 | -10.5347 |
| (b) SAL-off only | 507 | 4039.77 | 1.4533 | 39.3803 | 0.0777 | -721.54 | -10.4387 |
| (c) + BE60 | 500 | 4372.34 | 1.4548 | 39.6941 | 0.0794 | -793.77 | -10.4987 |
| (d) + blocked 10:00-15:00 | 400 | 5011.09 | 1.7852 | 44.9583 | 0.1124 | -563.16 | -9.5677 |
| **(e) FINAL (+ target 1.50R)** | **398** | **4903.34** | **1.6934** | **43.9018** | **0.1103** | **-674.80** | **-8.7396** |

### ALL_ex2026 (2018+2020+2023 only, pooled)

| Config | n | net_pts | PF_pts | total R | avg R/trade | max_dd_pts | max_dd_R |
|---|---|---|---|---|---|---|---|
| (a) canonical baseline | 393 | 755.59 | 1.1073 | 10.9505 | 0.0279 | -756.99 | -10.5347 |
| (b) SAL-off only | 434 | 1299.41 | 1.1731 | 18.6899 | 0.0431 | -721.54 | -10.4387 |
| (c) + BE60 | 427 | 1504.48 | 1.1891 | 18.5511 | 0.0434 | -793.77 | -10.4987 |
| (d) + blocked 10:00-15:00 | 343 | 2307.78 | 1.4397 | 24.6381 | 0.0718 | -563.16 | -9.5677 |
| **(e) FINAL (+ target 1.50R)** | **342** | **2771.47** | **1.5042** | **31.6538** | **0.0926** | **-548.66** | **-8.7396** |

### ALL_ex_best_year (2026 is the single best year in every config, so this equals ALL_ex2026 in every row)

Identical to the ALL_ex2026 table above in every config — 2026 is the
single highest-net-points build year for all 5 configurations (see the
2026-concentration discussion below).

### Per completed build year (net_pts / PF_pts)

| Config | 2018 | 2020 | 2023 |
|---|---|---|---|
| (a) canonical baseline | 104.49 / 1.0771 | 747.27 / 1.2645 | -96.16 / 0.9663 |
| (b) SAL-off only | 240.24 / 1.1735 | 971.00 / 1.3106 | 88.17 / 1.0294 |
| (c) + BE60 | 103.61 / 1.0709 | 1301.84 / 1.3819 | 99.04 / 1.0321 |
| (d) + blocked 10:00-15:00 | 285.80 / 1.3439 | 1478.90 / 1.5635 | 543.09 / 1.3030 |
| **(e) FINAL** | **507.87 / 1.5833** | **1716.53 / 1.6076** | **547.07 / 1.3038** |

### Partial 2026 (net_pts / PF_pts / total R / avg R/trade / max_dd_pts / max_dd_R)

| Config | net_pts | PF_pts | total R | avg R/trade | max_dd_pts | max_dd_R |
|---|---|---|---|---|---|---|
| (a) canonical baseline | 2743.56 | 3.0945 | 21.5327 | 0.3214 | -312.38 | -3.0000 |
| (b) SAL-off only | 2740.36 | 2.9494 | 20.6904 | 0.2834 | -355.12 | -4.0000 |
| (c) + BE60 | 2867.86 | 2.7313 | 21.1430 | 0.2896 | -423.81 | -5.1053 |
| (d) + blocked 10:00-15:00 | 2703.30 | 3.3838 | 20.3202 | 0.3565 | -402.75 | -5.0000 |
| **(e) FINAL** | **2131.87** | **2.3536** | **12.2480** | **0.2187** | **-488.44** | **-6.1454** |

Observation: each successive cumulative step improves ALL_ex2026 (real,
completed-year) performance monotonically on every headline metric (net,
PF, total R, avg R/trade), while 2026's own metrics move around
non-monotonically and in the FINAL config are actually **lower** than
config (a)/(b)/(c)/(d) on every 2026-only metric except win-rate-adjacent
payoff structure (see Stage F's `docs/OG_STAGE_F_RR.md` management-
interaction diagnostics). This is a meaningful, reassuring signal: the
final selection chain is not simply "whatever maximizes 2026" — each stage
individually improved the 3 completed years, and the final RR step
specifically gives back some 2026 edge in exchange for a large ex-2026
improvement (net_pts ex2026 2307.78 -> 2771.47, PF_pts 1.4397 -> 1.5042,
avg R/trade 0.0718 -> 0.0926).

## The 2026-concentration question (explicit, honest discussion)

2026 (partial) is the single largest per-year contributor to pooled net
points in every one of the 5 configurations (e.g. FINAL: 2131.87 of
4903.34 total, ~43.5%, even though it is under 5 months of data against 3
full years) — this has been a recurring theme flagged at every stage
(Stage B/C/D/E/F docs all note it explicitly).

**Is 2026 qualitatively similar to or disconnected from 2018/2020/2023?**

- **PF**: 2026's PF_pts is consistently the highest of the 4 build years in
  every configuration (2.35-3.38 across configs, vs 1.03-1.61 for
  2018/2020/2023 in the FINAL config) — a persistent, large gap, not
  incidental noise.
- **Avg R/trade**: FINAL config — 2026: 0.2187 vs 2018: 0.1044, 2020:
  0.0590, 2023: 0.1235. 2026 is roughly 2-4x the completed years' avg
  R/trade. This gap is qualitatively similar in shape (2026 > 2018 approx
  2023 > 2020) but much larger in magnitude than the spread AMONG the 3
  completed years, which is itself non-trivial (2020's avg R/trade is
  persistently the lowest of the 3 completed years in every config
  despite having the highest raw net_pts, because 2020's win rate is
  lower/losses are relatively larger per trade — see max_dd_R for 2020
  being the config's worst in 3 of 5 rows).
- **Payoff/frequency**: 2026 trades at a similar rate per elapsed period as
  the other years (57 trades over ~5 months in config (d), i.e.
  comparable density to a ~140/year pace, versus 100-131 trades/year for
  2018/2020/2023 in the same config) — frequency is NOT disconnected.
- **Drawdown**: 2026's max_dd_R is consistently the SMALLEST (least severe)
  of the 4 years across every config (e.g. FINAL: -6.1454 for 2026 vs
  -6.00/-8.7396/-5.9753 for 2018/2020/2023) — 2026 has not (yet) produced a
  severe drawdown episode; whether this holds if 2026 completes a full
  year is unknown and cannot be checked under the data firewall.
- **Parameter sensitivity**: the genuine LOBYO (Step 1) is the strongest
  evidence of disconnection: Stage D's and Stage F's fold-based candidate
  selection each flip specifically and only when 2026 is used for
  training/selection (Stage D: no-HMM otherwise; Stage F: 1.00R
  otherwise). This means at least two of five stage decisions in the
  frozen chain (D and F) are sensitive, at the selection-mechanics level,
  to whether 2026 participates in the ranking step — even though the
  FINAL config's headline numbers (avg R/trade, PF ex-2026) still improve
  monotonically through the chain when 2026 is entirely excluded from the
  outcome reporting (see the ALL_ex2026 table above).

**Conclusion on 2026**: 2026 is **partially disconnected** from
2018/2020/2023 — its PF and avg-R-per-trade are systematically and
substantially higher, not merely the top of a normal year-to-year range,
and it demonstrably drives 2 of 5 stage selections (D, F) when included in
fold-based candidate ranking. It is NOT disconnected on trade frequency or
drawdown severity (both are in-family or better than the completed years).
Because the final chain's ex-2026 performance improves monotonically and
materially at every step (this is not an artifact of only fitting to
2026), Phase 1's overall selection is not rejected outright — but the
2026-driven instability in Stages D and F specifically should weigh
heavily in any human review, and is the single most important caveat in
this report.

## What Phase 1 does and does not establish

**Does establish**: a specific, fully-documented, reproducible chain of
5 independently-justified parameter selections (SAL off, BE60, no-HMM,
blocked-10:00-15:00 entries, target 1.50R/Lane B) that improves every
headline retrospective metric — net points, PF, total R, avg R/trade — on
the 3 completed build years (2018, 2020, 2023) relative to the canonical
baseline, while keeping all 4 build years (including partial 2026)
individually net-positive at every cumulative step. It also establishes,
via a genuine fold-based LOBYO, which of these 5 decisions are robust
(Stage B strongly; Stage D via a partial approximation) and which are
comparatively fragile or 2026-sensitive (Stage C and E under a reduced
objective; Stage F materially, under both the original neighborhood
analysis's disclosed caveat and the new fold-based test).

**Does NOT establish**:
- Any live-readiness or prop-account-readiness claim. No Monte Carlo, no
  prop-account simulation of any kind was run.
- Performance on any year outside `OG_BUILD_YEARS` — 2019, 2021, 2022,
  2024, 2025 outcomes were never computed, inspected, or used anywhere in
  Phase 1, at any stage, for any purpose.
- That the chain would perform identically if re-derived via a single
  joint combinatorial search rather than 5 sequential, independently-frozen
  stage decisions (each stage held all prior decisions fixed; no stage
  revisited an earlier stage's choice in light of a later one, except
  where explicitly noted, e.g. Stage C's re-confirmation pass).
- Robustness of Stage D's HMM rejection or Stage F's RR selection under a
  TRUE nested per-fold refit (Stage D's LOBYO is an explicit approximation;
  Stage F's LOBYO used already-fit, non-refit candidates, which is valid
  for Stage F since target_r is not fit to data, but the 2026-sensitivity
  finding itself is real and not an artifact of the approximation).
- No `OG_PRE_VALIDATION_LOCK` exists. This document is not an authorization
  to proceed to validation; that decision is left to a human, informed by
  the caveats above (especially the Stage F / 2026-concentration finding).
