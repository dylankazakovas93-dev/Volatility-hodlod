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

This document is completed in the final report turn once a candidate
survives to the perturbation stage (or explicitly records that none did).
