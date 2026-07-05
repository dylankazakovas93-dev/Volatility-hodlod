# Stage 1 Perturbation Report

Populated after the outer walk-forward selection identifies which
neighborhood(s)/learned families are robust enough to perturb (section 19:
"only the top robust simple neighbourhoods and top learned families
proceed to perturbation -- do not perturb every losing candidate").

See `docs/STAGE1_TPSL_REPORT.md` for the full narrative; this file holds
the raw perturbation tables' pointers and the pass/fail read against
section 23's gate:

- `outputs/stage1_perturbations_<candidate>.csv` -- per-candidate
  perturbation ledger (base + every preregistered neighbor/stress variant).
- `outputs/stage1_perturbations_summary_<candidate>.json` -- fraction
  profitable, median perturbed PF.
- `outputs/stage1_causal_roll_summary.json` -- causal-roll sensitivity headline.
- `outputs/stage1_bootstrap_<candidate>.json` -- month-block bootstrap distributions.

## Outcome: no candidate reached the full perturbation stage

The strongest candidate found in Stage 1
(`learned|fs=F2|mfeq=0.50|maeq=0.50`) already fails the core pass-gate
criterion (aggregate outer walk-forward PF > 1.05: achieves 1.0481) before
perturbation testing would even matter. A lighter cost-sensitivity check
was run in its place (see `docs/STAGE1_TPSL_REPORT.md` section 5): PF stays
below 1.05 at every cost level from 0.0 to 2.0 points on the frozen
2018-2025 fit (1.0407 / 1.0215 / 1.0027 / 0.9660), and the RVOL coefficient
in its TP equation saturates at its imposed +0.30 bound in every one of
the 5 outer folds -- an independent disqualifier.

Given this, the full preregistered perturbation battery (neighboring
TP/SL/gamma sweep, RVOL history/clip sweep, leave-one-year-out,
adverse-fill-shift, 15:44 stress cutoff, causal-roll replay, 5,000-
simulation bootstrap) was **not run to completion** -- it would not change
a result that already fails at the first substantive gate. The causal-roll
sensitivity *series itself* was built
(`outputs/nq_causal_roll_2018_2026_1m.csv`, 33/2,624 days with a changed
selected contract, 1 fallback on the first day) and is available for
whoever picks this up next, but was not replayed against a failing
formula. See `outputs/stage1_summary.json` for the exact list of what was
and wasn't executed.
