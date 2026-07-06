# OG Build-Four-Years — Final Frozen Configuration & Robustness Summary

> **STATUS NOTE (Phase 1 rigor follow-up, in progress, not complete):** a
> human reviewer judged the Phase 1 result below (Stages B-E) to be
> prematurely concluded -- too few candidates per stage, and a pseudo-LOBYO
> (`scripts/og_lobyo.py`) that re-evaluates one already-chosen config per
> year rather than genuinely re-selecting per fold. This follow-up work item
> requires: (1) a permanent `PROP_HARD_BLACKOUT` 16:00-19:00 ET rule --
> **done**, see `docs/OG_PROP_HARD_BLACKOUT.md` and
> `tests/test_prop_hard_blackout.py`; (2) renaming the Stage E
> "10:00-16:00" selection to `RESEARCH_ENTRY_BLACKOUT_10_16` -- **done**,
> see `docs/OG_STAGE_E_WINDOWS.md`; (3) a full preregistered Stage C management
> family sweep -- **done**, see `docs/OG_STAGE_C_MANAGEMENT.md` (20
> candidates + mandatory perturbation; the perturbation did NOT pass
> cleanly, honest caveats documented, provisional `be_bars=60` retained
> pending future fold-based LOBYO); (4) a full Stage D HMM matrix (3-feature,
> 2/3-state, confidence-gated, perturbation-validated) -- **not done**; (5) a
> full Stage E blackout-window matrix -- **not done**; (6) genuine
> fold-based LOBYO for Stages B/C/D/E -- **not done**. The content below this
> note is the *original*, reviewer-flagged Phase 1 result and should be
> treated as superseded/incomplete pending that follow-up work. See the
> final report for an honest breakdown of what could and could not be
> completed in the available session.

Branch: `research/og-build-four-years`, built from
`research/og-stage-a-independent-verification` (commit `f972581`).

Scope of every metric in this document: `OG_BUILD_YEARS` only = {2018, 2020,
2023, 2026-partial through 2026-06-07}. No metric anywhere in this document,
or anywhere computed during Stages B-E, includes 2019/2021/2022/2024/2025
trade outcomes.

## Final combined frozen configuration

| Parameter | Frozen value | Stage | Canonical value |
|---|---|---|---|
| `sal_enabled` | **False** (SAL disabled) | B | True |
| `be_bars` | **60** | C | 45 |
| `be_extra_lock` | 0.0 (unchanged, no extra profit lock) | C | n/a (0.0) |
| HMM regime gate | **None** (no-HMM) | D | n/a (none in canonical) |
| Blocked entry window (ET) | **10:00-16:00** | E | 11:00-15:00 |
| Session cutoff | 15:00 ET (unchanged) | (not tested) | 15:00 ET |
| Level generation (sigma_mult, offset, IB minutes, line_days, etc.) | unchanged | (not tested) | see `configs/nq_current_config.yaml` |
| Stop cap / R:R / anchor | unchanged (1.5x anchor, cap 200, 1:1 R:R) | (not tested) | unchanged |
| tie_order | "age" (oldest level first, unchanged) | (not tested) | "age" |

All values not listed as tested in Stages B-E are unchanged from
`configs/nq_current_config.yaml` (the canonical Stage-A-verified baseline).

## Stage-by-stage selection (see individual stage docs for full detail)

- **Stage B (SAL):** `docs/OG_STAGE_B_SAL.md` — froze SAL off. SAL_off gave
  4/4 build years positive, higher net_pts (4039.77 vs 3499.15) and PF
  (1.4533 vs 1.4191) than SAL_on (which had 2023 negative).
- **Stage C (management):** `docs/OG_STAGE_C_MANAGEMENT.md` — froze
  `be_bars=60`. Highest net_pts (4372.34) and, with canonical BE-45, the only
  candidate with all 4 build years positive.
- **Stage D (HMM):** `docs/OG_STAGE_D_HMM.md` — froze no-HMM. Both HMM
  candidates tested either underperformed or collapsed trade count/robustness
  (best-PF candidate had a net-negative 2023 fold on ~18 trades).
- **Stage E (windows):** `docs/OG_STAGE_E_WINDOWS.md` — froze blocked window
  10:00-16:00 ET. Dominated canonical on every metric and (with one marginal
  exception) every build year.

## Aggregate build-year results, final combined configuration

| Slice | n | net_pts | PF | win_rate | avg_trade | max_drawdown |
|---|---|---|---|---|---|---|
| All 4 build years | 400 | 5011.09 | 1.7852 | 0.4375 | 12.528 | -563.16 |
| Excl. partial 2026 (full years 2018/2020/2023 only) | 343 | 2307.78 | 1.4397 | 0.4111 | 6.728 | -563.16 |
| Excl. single best build year (2026) | 343 | 2307.78 | 1.4397 | 0.4111 | 6.728 | -563.16 |
| Partial 2026 only (**partial**, through 2026-06-07) | 57 | 2703.30 | 3.3838 | 0.5965 | 47.426 | -402.75 |

("Excl. best build year" and "excl. partial 2026" coincide here because 2026
is both the single best year by net_pts and the partial year.)

## Per-build-year results, final combined configuration

| Year | n | net_pts | PF | win_rate | avg_trade | max_drawdown |
|---|---|---|---|---|---|---|
| 2018 (full) | 112 | 285.80 | 1.3439 | 0.3929 | 2.552 | -139.08 |
| 2020 (full) | 131 | 1478.90 | 1.5635 | 0.4046 | 11.289 | -563.16 |
| 2023 (full) | 100 | 543.09 | 1.3030 | 0.4400 | 5.431 | -378.11 |
| 2026 (partial, through 2026-06-07) | 57 | 2703.30 | 3.3838 | 0.5965 | 47.426 | -402.75 |

**Positive build years: 4 of 4** (in net points). No R-multiple concept
exists in this engine/ledger (no stop-risk-normalized field is computed by
either canonical engine or this variant module) — R sub-metrics are
intentionally omitted rather than invented, per instructions.

## Parameter-neighborhood stability

Small perturbations around the frozen configuration (each holding the other
3 frozen params fixed), evaluated on all 4 build years:

| Perturbation | n | net_pts | PF | max_drawdown |
|---|---|---|---|---|
| **Frozen (be_bars=60, window 10-16, no-HMM, SAL off)** | 400 | 5011.09 | 1.7852 | -563.16 |
| be_bars=45 (vs 60) | 407 | 4692.76 | 1.7737 | -721.54 |
| be_bars=75 (vs 60) | 394 | 3728.61 | 1.5299 | -546.66 |
| window 9:00-17:00 (wider than 10-16) | 308 | 3728.16 | 1.8334 | -460.79 |
| window 10:30-15:30 (narrower than 10-16) | 460 | 3866.08 | 1.4362 | -1038.69 |
| SAL back on (vs off) | 366 | 4208.83 | 1.7073 | -657.04 |

All perturbations remain solidly net-positive with PF > 1.4 — no
perturbation flips the sign of the result or produces a qualitatively
different outcome. The frozen point is a local optimum among the tested
perturbations but the neighborhood is not a cliff-edge: nearby parameter
choices give directionally similar, still-profitable results, which is the
robustness property being checked for.

## Leave-one-build-year-out (LOBYO) validation

For each full build year, the frozen configuration is evaluated on the
held-out year alone and confirmed to still perform in the same direction on
the remaining full years (see `outputs/og_build_years/final_lobyo_results.json`
for exact figures; `scripts/og_lobyo.py` to reproduce).

### Full-year folds (2018, 2020, 2023)

| Held-out year | Held-out net_pts | Held-out PF | Other-2-full-years net_pts | Other-2-full-years PF |
|---|---|---|---|---|
| 2018 | 285.80 | 1.3439 | 2021.99 (2020+2023) | 1.4578 |
| 2020 | 1478.90 | 1.5635 | 828.89 (2018+2023) | 1.3160 |
| 2023 | 543.09 | 1.3030 | 1764.69 (2018+2020) | 1.5107 |

**Every held-out full year is individually net-positive** under the frozen
configuration, and in every fold the remaining 2 full years are also net
positive with PF > 1.3 — the selection does not depend on any single year's
inclusion.

### Partial-2026 fold (kept separate — not directly comparable to full-year folds)

| Held-out (2026, partial) | net_pts | PF | Other full years (2018+2020+2023) net_pts | PF |
|---|---|---|---|---|
| 2026-partial | 2703.30 | 3.3838 | 2307.78 | 1.4397 |

2026's result is strong but on a partial year with a small (n=57), likely
favorable-regime sample; it is reported separately and not blended into the
full-year LOBYO conclusion, consistent with the task's instruction to keep
partial-2026 clearly distinguished.

## Data-firewall confirmation

Every strategy-outcome metric (trades, PF, net points, drawdown, exit-reason
counts) computed anywhere in Stages B, C, D, E, or this final summary was
filtered to `{2018, 2020, 2023, 2026}` only, using
`src.og_build_variant_engine.filter_build_years` as the single enforcement
point. No table or JSON output in this branch includes 2019, 2021, 2022,
2024, or 2025 trade-level or yearly outcomes. The only place the full
chronological bar stream was used unfiltered was for causal/rolling input
construction (Stage D's HMM feature fitting on 60-minute price returns),
which is explicitly permitted by the task's data-firewall rule and produced
no outcome metric.

## Raw outputs backing this document

- `outputs/og_build_years/final_frozen_build_years_trades.csv`
- `outputs/og_build_years/final_robustness_report.json`
- `outputs/og_build_years/final_lobyo_results.json`
- Stage-level raw outputs referenced in each stage doc.

## What this branch does NOT do

This branch stops after Stage E. It does not create an
`OG_PRE_VALIDATION_LOCK` commit, and it does not view or compute any trade
outcome for 2019, 2021, 2022, 2024, or 2025. That is reserved for a
separate, human-authorized phase.
