# OG Dual-Config Validation Protocol

Status: this document is a **protocol** — it fixes what will happen in a
future, separate validation task. **It does not run validation now.** No
2019/2021/2022/2024/2025 outcome data has been accessed, computed, or
viewed anywhere in the creation of this document or any other artifact in
this task. No Monte Carlo / account-sizing / payout-probability simulation
has been run.

## 1. Classification

- **Primary test**: `OG_PRIMARY_150R` (`configs/OG_PRIMARY_150R.yaml`).
  Determines whether the research-selected strategy (the preregistered
  winner of the 4-candidate bakeoff, `docs/OG_FINAL_BUILDOFF_BE45.md`)
  passes locked validation.
- **Secondary, independent test**: `OG_OPERATIONAL_100R`
  (`configs/OG_OPERATIONAL_100R.yaml`). Determines whether the
  lower-variance operational version independently passes the *same*
  locked validation. **This is not a fallback replacement for the
  primary** — it is tested in its own right, on its own merits, against
  the identical gate.

## 2. Outcome-handling rules

- **If primary fails and secondary passes**: report the primary failure
  honestly. Report the secondary's independent pass. Do not rewrite
  history to claim the primary passed. Do not select
  `OG_OPERATIONAL_100R` (or any other configuration) *using
  validation-year performance* as a replacement research line — its
  independent pass stands on its own, on the same preregistered gate it
  was always going to be tested against.
- **If both pass**: both may proceed to external 2013-2015 testing and any
  later Prop Lab comparison. They remain two separate, independently
  reported results throughout — never pooled.
- **If only one passes**: only the passing configuration may proceed
  (to 2013-2015 testing / Prop Lab). The failing one stops.
- **If neither passes**: stop the research line. No further parameter
  search, no new candidate, no re-targeting of `target_r` to "chase" the
  gate.
- **Multiple-testing safeguard**: the two configs are always reported
  separately, never pooled into a single combined strategy result. The
  better of the two validation-year results is never chosen post hoc.
  Each config must independently satisfy every one of the criteria in §3
  using the exact same gate — no per-config gate adjustment.

## 3. Family-level interpretation labels

- `DUAL_CONFIG_FAMILY_PASS` — both configs independently pass every
  criterion in §4.
- `PRIMARY_ONLY_PASS` — `OG_PRIMARY_150R` passes, `OG_OPERATIONAL_100R`
  does not.
- `SECONDARY_ONLY_PASS` — `OG_OPERATIONAL_100R` passes, `OG_PRIMARY_150R`
  does not.
- `DUAL_CONFIG_FAIL` — neither config passes.
- There is no marginal-pass category. A config either satisfies every
  criterion in §4 or it does not.

## 4. The validation gate (verbatim, applied independently to each config)

A configuration passes locked validation if and only if **all** of the
following hold, computed against the pooled 5 locked validation years
(2019, 2021, 2022, 2024, 2025):

1. All execution invariants pass (no overlap, no lookahead, deterministic
   rerun — see §6).
2. Pooled net points positive.
3. Pooled total cap-normalized R positive.
4. Pooled PF (points) >= 1.15.
5. Pooled PF (R) >= 1.05.
6. Average R/trade positive.
7. At least 3 of the 5 validation years positive in total R.
8. At least 3 of the 5 validation years have PF (points) > 1.05.
9. Total R remains positive excluding the single best validation year.
10. At least 250 validation trades.
11. No single year supplies more than 80% of pooled positive net points.

**These gates must not be altered after viewing validation-year results.**
This document fixes them before any validation-year data is touched.

## 5. Validation runner

**What exists today**: the build-year engine and harness this gate will
reuse are already committed and unmodified —
`src/og_management_variants.py::run_variant_managed` (the config-driving
simulation) and `src/og_build_variant_engine.py` (`run_variant()`,
`filter_build_years()`/year-filtering, `in_prop_hard_blackout()`). The
bakeoff script `scripts/og_final_buildoff_be45.py` demonstrates the exact
invocation pattern already used for both configs (`CANDIDATES["A"]` and
`CANDIDATES["B"]`), just filtered to `OG_BUILD_YEARS` instead of the
validation years.

**What is deferred (not built or run in this task)**: a dedicated
validation-runner script that (a) points the same engine/config pair at
the year filter `{2019, 2021, 2022, 2024, 2025}` instead of
`OG_BUILD_YEARS`, and (b) computes and reports the §4 gate criteria
directly. This is expected to be a straightforward reuse of
`scripts/og_final_buildoff_be45.py`'s structure with the year filter and
candidate set changed (`CANDIDATES = {"PRIMARY": ...OG_PRIMARY_150R
params..., "OPERATIONAL": ...OG_OPERATIONAL_100R params...}`,
`filter_build_years(ex_df, years={2019,2021,2022,2024,2025})`), but it has
**not been written or run** in this task, and must not be, per the data
firewall. A human must explicitly authorize creating and running that
runner before any validation-year data is touched.

## 6. Invariant tests

Reference: `tests/test_prop_hard_blackout.py` (9 tests),
`tests/test_strategy_invariants.py`, `tests/test_og_stage_a_invariants.py`.
Verified passing in this session (build-year context only, no
validation-year data involved):

```
python -m pytest tests/test_prop_hard_blackout.py tests/test_strategy_invariants.py tests/test_og_stage_a_invariants.py -q
45 passed
```

These must pass again (unmodified) as part of any future validation run,
in addition to the deterministic-rerun check already demonstrated for the
canonical engine in `docs/OG_STAGE_A_VERIFICATION_REPORT.md` §4.3.

## 7. Reproduction commands (build-year artifacts already produced; not to be re-run against validation years)

```
python3 scripts/og_final_buildoff_be45.py
# regenerates outputs/og_build_years/final_buildoff_{A,B,C,D}_build_years_trades.csv
# and outputs/og_build_years/final_buildoff_be45.csv, restricted to OG_BUILD_YEARS
# = {2018, 2020, 2023, 2026(partial)} only.
```

## 8. Exact next command once a human authorizes validation

Not run in this task. Once authorized, the next command is expected to be
a new, dedicated validation-runner script (to be written at that time,
under explicit human sign-off) analogous to:

```
python3 scripts/og_validation_dual_config.py \
    --years 2019 2021 2022 2024 2025 \
    --config configs/OG_PRIMARY_150R.yaml \
    --config configs/OG_OPERATIONAL_100R.yaml \
    --out-dir outputs/og_validation/
```

`scripts/og_validation_dual_config.py` does not exist yet. No such command
has been run in this task, and no output referenced by that path exists.
