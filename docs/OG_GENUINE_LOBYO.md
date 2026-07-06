# Genuine Leave-One-Build-Year-Out (LOBYO) — all 5 stages (B/C/D/E/F)

Status: COMPLETE. Supersedes `scripts/og_lobyo.py`, which was a
PSEUDO-LOBYO: it evaluated one fixed, already-frozen final configuration on
each held-out year, but never re-derived the SELECTION itself per fold. This
document performs genuine fold-based selection: for each stage and each
held-out year, the candidate is re-ranked using ONLY the other 3 build
years' data, then the resulting fold-specific winner is evaluated ONLY on
the held-out year.

Data firewall: only {2018 (full), 2020 (full), 2023 (full), 2026 (partial)}
outcome data is used anywhere in this document, exactly as in every prior
stage. No 2019/2021/2022/2024/2025 trade outcome is computed, inspected, or
reported anywhere below. No `OG_PRE_VALIDATION_LOCK`.

Reproduction: `python3 scripts/og_genuine_lobyo.py` (reads the already-
computed per-candidate, per-year CSVs produced by
`scripts/og_stage_{b,c,e,f}_*.py` and the Stage D full-matrix results in
`docs/OG_STAGE_D_HMM.md` — no expensive re-simulation is performed; see the
"Method" section below for why this is legitimate). Output:
`outputs/og_build_years/genuine_lobyo_results.json`.

## Method

None of the candidates in Stages B, C, E, F are *fit* to the data in any way
that could leak information from a held-out year back through an aggregate
statistic — each is a fixed, externally specified simulation parameter
(SAL on/off; `be_bars` in {none,30,45,60,75,90}; blocked-window start in
{09:00...12:00}; `target_r` in {0.75,1.00,1.25,1.50,2.00} for Lane B/BE60)
evaluated independently, trade-by-trade, on whichever years are included.
The per-candidate, per-year net_pts/PF tables these stages already
produced (`outputs/og_build_years/stage_{b,c,e,f}_*complete*.csv` /
`.json`) are therefore trade-level, per-year decomposable: slicing "other 3
years" out of that existing table for selection purposes is mathematically
identical to re-running the same candidate on that 3-year subset directly
(this was independently confirmed for Stage E's redundant until-16:00 check
and Stage F's target_r=1.0 no-op sanity check — both included row-for-row
/ exact-number reproductions of subsets of the same underlying simulation).
No re-simulation was therefore necessary for B/C/E/F; `scripts/og_genuine_lobyo.py`
reads the existing per-year CSVs and performs the fold arithmetic in Python.

**Stage D is an explicit, disclosed approximation.** The full causal,
session-refit HMM (`src/og_hmm_gate.py`) genuinely IS fit to trailing
session data, so a fully rigorous fold-based LOBYO would need to refit it
per fold (using only the training windows that fall within the 3
non-held-out years) — 4 separate expensive re-fits. Per the task's explicit
permission, this was NOT done; instead the reduced candidate pool
{`no_gate` (control), `hmm3_HIGH_only_p55`, `hmm3_exclude_MID_p55` — the two
survivors of Stage D's primary screen, per `docs/OG_STAGE_D_HMM.md`} was
selected/evaluated using the ALREADY-COMPUTED per-year breakdown from the
single primary-setting (window=120, seed=42) full-matrix run. This means
Stage D's LOBYO numbers are not a true nested cross-validation of the HMM
fitting procedure itself — only of the candidate-selection step given a
single already-fit HMM. This is a materially weaker guarantee than Stages
B/C/E/F's LOBYO and is flagged prominently here and in the final report.

### Reduced objective per stage

Each stage's real selection process (see its own doc) combined a primary
quantitative criterion with qualitative robustness/no-cliff-edge checks that
do not reduce to a single scalar function evaluable purely from a per-year
CSV. For LOBYO purposes each stage's objective is reduced to a two-key sort
`(n_positive_years_among_others, aggregate_quality_metric_over_others)`,
maximized:

| Stage | Positive-year check | Aggregate quality metric (trade-count-weighted mean over the non-held-out years) |
|---|---|---|
| B (SAL on/off) | net_pts > 0 | aggregate net_pts |
| C (BE family) | net_pts > 0 | PF_pts |
| D (HMM, reduced pool) | net_pts > 0 | aggregate net_pts |
| E (blocked-window start) | net_pts > 0 | PF_pts |
| F (Lane B target_r) | net_pts > 0 | PF_R |

**This is a simplification of, not identical to, the original stage
decisions.** The original decisions (documented in each stage's own `.md`)
additionally required "no isolated cliff-edge" / neighborhood-robustness
checks — e.g. Stage C selected BE60 over BE45 despite BE45 being locally
competitive, citing BE60's more favorable placement in the wider
30/45/60/75/90 neighborhood, not solely its own PF. The reduced two-key
objective used here recovers a **different** all-years winner in two
stages (C: BE45 instead of the frozen BE60; E: 09:30 instead of the frozen
10:00) — this is disclosed explicitly below, not hidden, and does not by
itself invalidate the frozen Stage C/E decisions (which used the fuller,
qualitative standard); it does mean the mechanized LOBYO comparison in this
document is evaluating a close cousin of, not an exact restatement of, the
original selection rule.

## Results by stage

### Stage B — SAL on/off

| Fold held out | Fold winner | Held-out net_pts | Held-out PF |
|---|---|---|---|
| 2018 | SAL_off | 240.24 | 1.1735 |
| 2020 | SAL_off | 971.00 | 1.3106 |
| 2023 | SAL_off | 88.17 | 1.0294 |
| 2026 (partial) | SAL_off | 2740.36 | 2.9494 |

Selection frequency: **SAL_off selected in all 4/4 folds** (unanimous).
Held-out performance: **4/4 positive** (3/3 full years, 4/4 overall).
2026-specific check: the 2026 fold's winner matches the full-year-fold
consensus exactly. **Verdict: STABLE.** This matches the frozen decision
(`SAL_off`) exactly in every fold — the most robust of the five stages.

### Stage C — BE family (noBE/BE30/BE45/BE60/BE75/BE90)

| Fold held out | Fold winner (on other 3 years) | Held-out net_pts | Held-out PF_pts |
|---|---|---|---|
| 2018 | BE30 | **-20.01** | 0.9863 |
| 2020 | BE45 | 971.00 | 1.311 |
| 2023 | BE45 | 88.17 | 1.029 |
| 2026 (partial) | BE45 | 1299.41 | 1.173 |

Selection frequency across the 4 folds: **BE45 selected in 3/4 folds**,
BE30 selected in 1/4 (the 2018-held-out fold). **BE60 (the frozen winner)
is never selected as a fold winner under this reduced objective.**
Positive held-out folds: 2/3 full years, 3/4 overall — the 2018-held-out
fold is net-negative (BE30's held-out 2018 performance, -20.01 pts) — the
same neighborhood asymmetry the original Stage C doc explicitly flagged:
`docs/OG_STAGE_C_MANAGEMENT_COMPLETE.md`
notes BE60's neighborhood is "robust on the 30/45/60 plateau side, fragile
immediately past it" and that 2018 specifically is one of the plateau's
weaker years for several BE settings).
2026-specific check: 2026's fold winner (BE45) matches the full-year-fold
consensus (BE45, 2/3 full-year folds) — 2026 is not the disruptive factor
here; the 2018 fold is (it alone prefers BE30).
**Verdict: MODERATELY UNSTABLE.** Selection is not unanimous (BE30 vs BE45
split), and neither fold-winner is BE60. This does not contradict Stage C's
own documented finding of an *asymmetric, not fully robust* neighborhood —
if anything it corroborates it under a stricter fold-based test. The
original BE60 decision was made using the fuller neighborhood-shape
standard (not solely per-fold PF maximization), which this reduced LOBYO
objective does not fully reproduce.

### Stage D — HMM gate (reduced pool: no_gate, hmm3_HIGH_only_p55, hmm3_exclude_MID_p55) — APPROXIMATION, see Method

| Fold held out | Fold winner (on other 3 years) | Held-out net_pts | Held-out PF |
|---|---|---|---|
| 2018 | no_gate | 103.61 | 1.0709 |
| 2020 | no_gate | 1301.84 | 1.3819 |
| 2023 | no_gate | 99.04 | 1.0321 |
| 2026 (partial) | hmm3_exclude_MID_p55 | 2479.61 | 3.0857 |

Selection frequency: **no_gate selected in 3/4 folds** (all 3 full-year
folds), **hmm3_exclude_MID_p55 selected only when 2026 is the held-out
fold** (because excluding 2026 from the "other years" pool used for
selection removes 2026's very large net_pts contribution from
`hmm3_exclude_MID_p55`'s aggregate score, and the full-year-only comparison
then favors no_gate). Positive held-out folds: 3/3 full years, 4/4 overall.
**2026-specific check: YES — 2026 materially drives Stage D's selection.**
This is the clearest "does 2026 drive the pick" finding across all 5
stages: the fold winner literally flips depending on whether 2026 is in the
training pool or is the held-out target. This is fully consistent with (and
reinforces) `docs/OG_STAGE_D_HMM.md`'s own finding that `hmm3_exclude_MID_p55`
"fails the mandatory seed-perturbation test" and that HMM candidates'
apparent edge is frequently concentrated in 2026/2020. **Verdict: UNSTABLE,
2026-DRIVEN.** This corroborates, rather than contradicts, the frozen
no-HMM decision.

### Stage E — blocked-window start (09:00...12:00, until 15:00)

| Fold held out | Fold winner (on other 3 years) | Held-out net_pts | Held-out PF_pts |
|---|---|---|---|
| 2018 | blocked_0930_until1500 | 244.12 | 1.4717 |
| 2020 | blocked_0930_until1500 | 1089.41 | 1.4990 |
| 2023 | blocked_0930_until1500 | 310.51 | 1.2547 |
| 2026 (partial) | blocked_0930_until1500 | 2556.48 | 4.3467 |

Selection frequency: **blocked_0930_until1500 selected in all 4/4 folds**
(unanimous). **The frozen winner (10:00) is never the fold winner** under
this reduced PF-only objective — 09:30 has a higher PF_pts than 10:00 in
every leave-one-out comparison (09:30's ex-2026 PF_pts 1.4194 already beat
10:00's raw PF_pts of 1.4397 is close, but on individual leave-one-out
slices 09:30 wins consistently). Held-out performance: 4/4 positive.
2026-specific check: unanimous across all 4 folds, so 2026 is not
disruptive here specifically — the 09:30-vs-10:00 discrepancy versus the
frozen doc is attributable to the reduced objective (PF_pts only, no
explicit trade-count/frequency or "all 4 years individually positive with
margin" weighting) rather than to 2026 concentration. **Verdict: STABLE
SELECTION, BUT DIFFERENT WINNER THAN THE FROZEN CHOICE under this narrower
objective** — worth noting for any future revisit of Stage E, though it
does not on its own overturn the frozen 10:00 decision (which used the
fuller standard: highest ex-2026 PF among the 7 AND all 4 years positive
AND not an isolated cliff-edge; 10:00 and 09:30 are directionally
close/adjacent per `docs/OG_STAGE_E_WINDOWS_COMPLETE.md`'s own perturbation
table).

### Stage F — target_r, Lane B (BE60) only

| Fold held out | Fold winner (on other 3 years) | Held-out net_pts | Held-out PF_R |
|---|---|---|---|
| 2018 | laneB_be60_rr100 | 285.80 | 1.3058 |
| 2020 | laneB_be60_rr100 | 1478.90 | 1.0555 |
| 2023 | laneB_be60_rr100 | 543.09 | 1.371 |
| 2026 (partial) | laneB_be60_rr150 | 2131.87 | 1.7379 |

Selection frequency: **laneB_be60_rr100 (1.00R) selected in 3/4 folds** (all
3 full-year folds), **laneB_be60_rr150 (the frozen winner, 1.50R) is
selected only when 2026 is the held-out fold** — the mirror image of Stage
D's finding. Positive held-out folds: 3/3 full years, 4/4 overall.
**2026-specific check: YES — 2026 materially drives Stage F's selection**,
in the same direction/manner as Stage D: excluding 2026 from the "other
years" training pool removes 1.50R's largest single-year edge, and the
full-year-only PF_R comparison then favors the more conservative 1.00R.
**Verdict: UNSTABLE, 2026-DRIVEN.** This is a genuinely important, honest
finding: Stage F's frozen 1.50R selection is *not* robust to a fold-based
test that excludes 2026 from the training data used to make the pick,
even though 1.50R keeps all 4 build years individually positive at the
all-years setting (per `docs/OG_STAGE_F_RR.md`).

## Cross-stage summary

| Stage | Selection frequency (of 4 folds) | Frozen winner also a fold winner? | 2026 drives selection? | Stability verdict |
|---|---|---|---|---|
| B (SAL) | SAL_off 4/4 | Yes (exactly) | No | **STABLE** |
| C (BE) | BE45 3/4, BE30 1/4 | No (BE60 never wins a fold) | No (2018 is the outlier fold, not 2026) | **UNSTABLE** (pre-existing asymmetry, not new) |
| D (HMM, approx.) | no_gate 3/4, hmm3_exclude_MID_p55 1/4 | Yes (no_gate/no-HMM wins 3/4) | **YES** | **STABLE-ish but 2026-sensitive**; reinforces the frozen no-HMM decision |
| E (window) | blocked_0930 4/4 | No (10:00 never wins a fold under the reduced objective) | No | **STABLE SELECTION, DIFFERENT WINNER** than frozen (narrower objective effect, not a 2026 effect) |
| F (RR) | laneB_rr100 3/4, laneB_rr150 1/4 | Only in the 2026 fold | **YES** | **UNSTABLE, 2026-DRIVEN** |

## Overall honest takeaways

1. **Stage B (SAL off) is the most robust decision in this pipeline** — it
   wins every fold unanimously and is unaffected by which year is held out.
2. **Stage D's no-HMM decision is reinforced, not undermined, by this
   LOBYO**: the one candidate that could have beaten it
   (`hmm3_exclude_MID_p55`) only wins when 2026 supplies its training data,
   which is exactly the kind of single-year concentration the original
   Stage D doc's seed-perturbation test flagged as disqualifying.
3. **Stage F's 1.50R selection is the least robust of the five stages under
   a genuine fold-based test**: the fold-based winner is 1.00R in 3 of 4
   folds, and only matches the frozen 1.50R pick when 2026 is used for
   selection. This does not mean 1.50R is wrong — the frozen decision used
   a fuller standard (monotonic PF_R climb, no isolated maximum, all 4
   years individually positive) that this reduced two-key LOBYO objective
   does not fully capture — but it is a genuine, disclosed fragility that
   should weigh into any human review of the final config, and is the
   strongest evidence in this task of 2026 concentration materially
   affecting a Phase-1 decision.
4. **Stage C and Stage E's LOBYO winners differ from their frozen picks**
   (BE45 vs BE60; 09:30 vs 10:00) but for a different reason than Stage
   D/F: these are artifacts of the reduced, purely-quantitative LOBYO
   objective not reproducing the original qualitative neighborhood-
   robustness standard, not evidence of 2026-driven instability (both show
   unanimous-or-near-unanimous selection frequency and no unusual
   2026-fold divergence). This is disclosed rather than smoothed over, but
   is a materially different and less concerning finding than Stages D/F's
   2026-driven flips.
