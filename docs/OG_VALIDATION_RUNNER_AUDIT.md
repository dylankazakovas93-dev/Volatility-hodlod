# OG validation runner audit (Step 3, pre-execution)

Performed against `scripts/og_validation_dual_config.py` at commit
`7a704ae871cc782c4b83e4e2409a81133ac14bc1` (`OG_DUAL_VALIDATION_RUNNER_LOCK`).
**No validation-year data was accessed to produce this audit.**

## Configuration integrity

Ran `v.load_config()` + `v.assert_configs_only_differ_in_target_r()` +
`v.resolve_effective_params()` against the real committed config files:

```
PRIMARY params:   {'be_bars': 45, 'blocked_window': (600, 900), 'target_r': 1.5}
SECONDARY params: {'be_bars': 45, 'blocked_window': (600, 900), 'target_r': 1.0}
```

- `OG_PRIMARY_150R` resolves to `target_r=1.50`: **PASS**
- `OG_OPERATIONAL_100R` resolves to `target_r=1.00`: **PASS**
- Every other effective parameter identical (`be_bars`, `blocked_window`,
  plus the full `COMPARE_KEYS` diff over `data`, `level_generation`,
  `stop_calc`, `one_global_position`, `no_overlap`, `no_stacking`,
  `no_same_minute_reentry`, `permanent_touch_consumption`, `tie_order`,
  `intrabar_ambiguity`, `forced_liquidation_time_et`, `prop_hard_blackout`,
  `entry_blackout`, `sal_enabled`, `management`, `hmm_gate`): **PASS**
  (`assert_configs_only_differ_in_target_r` raised nothing)
- Both configs' `expected_build_ledger.sha256` verified against the
  actual committed files
  (`outputs/og_build_years/final_buildoff_A_build_years_trades.csv`,
  `outputs/og_build_years/final_buildoff_B_build_years_trades.csv`):
  **PASS** (hashes match exactly what's recorded in each YAML; also
  independently re-verified via `sha256sum` in this session).
- Both configs' `source.introducing_commit`
  (`ebc98d31ac5dbd4e89f474ebba6d3b03c523254d`) verified as an ancestor of
  the lock commit `dad3da69aad401243544f80974f6d7506fefb7e2` via
  `git merge-base --is-ancestor`: **PASS**

## Execution integrity

`python -m pytest tests/test_prop_hard_blackout.py tests/test_strategy_invariants.py tests/test_og_stage_a_invariants.py -q`
→ **45 passed**. These tests (unmodified, same command as the pre-validation
lock) cover: one global position, no overlap/no stacking, no same-minute
exit-then-reentry, permanent first-touch consumption / no retry after
blocked touches, oldest-level-first (`tie_order="age"`) simultaneous
ordering, SAL-off behavior, BE45 mechanism, no-HMM path, entry blackout
10:00-15:00 ET, forced exit 15:00 ET, PROP_HARD_BLACKOUT 16:00-19:00 ET
(also independently asserted inside `run_variant_managed` itself and again
in `run_one_config()`), the original stop-cap formula
(`min(1.5*anchor, SL_CAP)`), conservative TP/SL ambiguity handling, and
causal completed-bar-only information (no lookahead). **All PASS.**

## Year firewall

Programmatic checks in `scripts/og_validation_dual_config.py`:

- `VALIDATION_YEARS == frozenset({2019, 2021, 2022, 2024, 2025})`: **PASS**
- `VALIDATION_YEARS & BUILD_YEARS == set()`: **PASS**
- `VALIDATION_YEARS & BANNED_YEARS == set()` (2013-2015 never referenced): **PASS**
- `main()` raises `ValidationFailClosed` for any `--years` argument not
  exactly equal to the locked set (verified by
  `test_years_outside_locked_set_fails_closed`,
  `test_banned_years_fail_closed_even_if_superset`): **PASS**
- `run_one_config()` raises `ValidationFailClosed` if any build year
  (2018/2020/2023/2026) or banned year (2013-2015) appears in the
  post-filter ledger, or if any year outside the requested set appears:
  **PASS** (structural test coverage;
  see `tests/test_validation_runner_structure.py`)

## Gate integrity

Parsed `docs/OG_VALIDATION_PROTOCOL_DUAL_CONFIG.md` §4 (11 numbered
criteria) and `docs/OG_PRE_VALIDATION_DUAL_CONFIG_LOCK.json`
(`validation_gate.criteria_count=11`,
`validation_gate.family_labels=[DUAL_CONFIG_FAMILY_PASS,
PRIMARY_ONLY_PASS, SECONDARY_ONLY_PASS, DUAL_CONFIG_FAIL]`) and diffed them
programmatically: 11 criteria in the markdown match the JSON's declared
count, and the family-verdict labels match exactly between the two
documents. **PASS.** Neither document was modified by this audit.

## Overall audit result: ALL CHECKS PASS

Runner is authorized to proceed to Step 4 (single locked execution).
