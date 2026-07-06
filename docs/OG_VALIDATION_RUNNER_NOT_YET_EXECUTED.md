# OG validation runner lock — not yet executed

This commit (`OG_DUAL_VALIDATION_RUNNER_LOCK`) adds
`scripts/og_validation_dual_config.py`, its structural test suite
(`tests/test_validation_runner_structure.py`), the output schema, metric
calculation code, and the pass/fail gate code (`evaluate_gate()`).

**As of this commit, validation-year outcomes have NOT been generated.**
No command in this commit's history has computed a real P&L, R, or trade
outcome for 2019, 2021, 2022, 2024, or 2025. All engine invocations
exercised while building and testing this runner used either:

- the real committed config files (`configs/OG_PRIMARY_150R.yaml`,
  `configs/OG_OPERATIONAL_100R.yaml`) for schema/hash/field validation only
  (no engine simulation triggered by loading a YAML file), or
- fully synthetic, fabricated OHLCV fixtures (year 2030, made up prices),
  or
- direct calls to `evaluate_gate()` / `filter_build_years()` on synthetic
  in-memory DataFrames.

`outputs/og_validation/` does not exist prior to Step 4 of the task
sequence. The exact, single, locked reproduction command that will be run
next (Step 4, under separate human-visible sign-off already granted by the
task authorizing this specific runner) is:

```
python3 scripts/og_validation_dual_config.py \
  --years 2019 2021 2022 2024 2025 \
  --config configs/OG_PRIMARY_150R.yaml \
  --config configs/OG_OPERATIONAL_100R.yaml \
  --out-dir outputs/og_validation/
```

No variation of this command (different years, different target_r, extra
flags) is authorized. See `docs/OG_VALIDATION_PROTOCOL_DUAL_CONFIG.md` §4-§8
and `docs/OG_PRE_VALIDATION_DUAL_CONFIG_LOCK.json` for the locked gate and
protocol this runner implements.
