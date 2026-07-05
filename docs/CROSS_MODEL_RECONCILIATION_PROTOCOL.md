# Cross-Model Reconciliation Protocol

For Claude 2 and Codex: this is how to independently reproduce and verify the
strict one-position NQ reconciliation, and how to compare your own ledger
against ours row-by-row rather than trusting a summary number.

## 1. Fetch the branch

```
git fetch origin strict-one-position-reconciliation
git checkout strict-one-position-reconciliation
```

Confirm you're on the commit that contains `scripts/reconcile_strict_one_position.py`
with `configs/nq_canonical_strict.yaml` present.

## 2. Verify data hashes

```
sha256sum data/nq_1m/nq_continuous_2018_2026_1m.csv data/vxn_daily_2018_2026.csv
```

Compare against `configs/nq_canonical_strict.yaml` -> `data.bars_sha256` /
`data.vxn_sha256`, and the bars row count:

```
python3 -c "print(sum(1 for _ in open('data/nq_1m/nq_continuous_2018_2026_1m.csv')) - 1)"
```

Expected: `2964655`. If any of these differ, **stop** — you do not have the
canonical dataset and no downstream number will match. Report the mismatch
as `data mismatch`, not as a strategy disagreement.

## 3. Run the reproduction command

```
python3 scripts/reconcile_strict_one_position.py \
    --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
    --vxn  data/vxn_daily_2018_2026.csv \
    --out-dir outputs
```

Runtime is roughly 1-2 minutes. It will print a `GATE 1` check first; if that
fails (`raw eligible candidates != 1841`), stop and report the failure before
looking at any P&L number.

Then run the invariant suite:

```
python3 -m pytest tests/test_nq_strict_invariants.py -v
```

All 18 tests must pass. If pytest/pandas/pyyaml aren't installed in your
environment: `python3 -m pip install pytest pandas pyyaml`.

## 4. Verify output hashes

```
sha256sum outputs/nq_physical_first_touches.csv outputs/nq_eligible_1841.csv \
          outputs/nq_strict_executed.csv outputs/nq_strict_skipped.csv \
          outputs/nq_strict_yearly.csv outputs/nq_edge_case_sensitivities.csv
```

Compare against the `output_hashes` block in `outputs/nq_strict_summary.json`
committed alongside this doc. If your locally-regenerated hashes match ours
exactly, your environment reproduces the canonical result bit-for-bit — stop
here, you're done, no further comparison needed.

If they **don't** match (e.g. you're running your own independently-built
engine rather than this exact script), proceed to row-by-row comparison.

## 5. Row-by-row ledger comparison

Row identity is defined as the 4-tuple:

```
(level_id, physical_first_touch_timestamp, side, origin_session)
```

Run:

```
python3 scripts/compare_strict_ledgers.py \
    --reference outputs/nq_strict_executed.csv \
    --comparison <path_to_your_ledger.csv>
```

Your ledger CSV must have at least these columns: `level_id`, `entry_time`
(the physical first-touch timestamp), `side`, `session_date`, `exit_reason`,
`pnl`. If your column names differ, pass `--comparison-columns` to remap
(see `--help`).

The script reports:

- matched rows (identical entry/exit/pnl)
- rows only in reference (yours is missing them — likely an eligibility-gate
  or first-touch mismatch on your side)
- rows only in comparison (you have extra rows — likely a `LINE_DAYS`/expiry
  or touch-detection mismatch on your side; this was the root cause of the
  previously-unreproduced 3,093-trade claim)
- same entry but different exit (position-state, SAL-state, BE-timing, or
  fill-policy mismatch)
- same entry/exit but different P&L (fill-policy or numerical-precision
  mismatch)
- first 100 detailed row-level differences
- aggregate P&L effect by difference category

## 6. Classify every differing row

Every row that doesn't match must be bucketed into exactly one of:

| Category | What it means |
|---|---|
| `data_mismatch` | Your bars/VXN file hash or row count differs from canonical |
| `first_touch_mismatch` | Your touch-detection logic (or window) finds a different first physical touch for the same level side |
| `eligibility_gate_mismatch` | You applied the anchor/cutoff/entry-window gates differently |
| `simultaneous_touch_ordering` | Same timestamp, different tie-break choice |
| `position_state_mismatch` | Your single-position enforcement disagrees on whether a position was open |
| `sal_state_mismatch` | Your SAL activation/reset timing disagrees |
| `be_timing_mismatch` | Your bar-45 conditional-BE arming logic disagrees |
| `fill_policy_mismatch` | Your gap-through / touch-bar fill assumption differs |
| `same_bar_policy_mismatch` | Your same-bar exit/re-entry rule differs |
| `numerical_precision_only` | Same trade, PnL differs by < 0.01 pts (float rounding) |
| `unexplained` | None of the above account for the difference — flag this explicitly, do not silently drop it |

Do not report an aggregate PF/net difference without this row-level
classification — a single number cannot tell you *why* two engines diverge,
and the entire point of this protocol is to stop trusting summary numbers
without proof.

## 7. What "reproduced" means

You have reproduced this package only if:

1. Your data hashes match (step 2).
2. `GATE 1` passes (1,841 eligible candidates) on your run.
3. All 18 invariant tests pass on your run.
4. Either your output hashes match ours exactly (step 4), **or** your
   independently-built ledger's row-by-row comparison (step 5-6) shows zero
   `unexplained` differences and every classified difference is documented
   with its aggregate P&L effect.

Report your result using the same 8-point structure as our final response
(gate pass/fail, trade count, net, PF, cost-adjusted table, output hashes,
test pass count, and any change to the profitability conclusion). Do not
report a new PF number without this structure — it will not be treated as
comparable.
