# Reproducibility — NQ Strict Reconciliation

## Exact reproduction command

```
python3 scripts/reconcile_strict_one_position.py \
    --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
    --vxn  data/vxn_daily_2018_2026.csv \
    --out-dir outputs
```

## Environment

- Git SHA at time of run: see `outputs/nq_strict_summary.json` -> `git_sha`
- Data file hashes: `DATA_MANIFEST.md`
- No random seeds are used anywhere in this pipeline — it is a deterministic
  rebuild from source bars + a fixed rule set. Re-running against the same
  data files and the same commit must reproduce every number in
  `docs/NQ_STRICT_RECONCILIATION.md` exactly.

## What the script does, in order

1. Rebuilds `nq_cond_be45.build_ledger()`'s raw candidate population and
   checks it against the frozen gate value 1,841. If this does not match,
   the script exits with a nonzero status before computing any P&L —
   profitability numbers are never reported against an unreconciled
   candidate population.
2. Computes the physical first-touch table for every level-side under the
   primary (conservative) edge-case rules (`outputs/nq_physical_first_touches.csv`).
3. Runs the causal, single-global-position, time-aware-SAL state machine
   (`run_strict`) once as PRIMARY, then once per edge-case sensitivity with
   exactly one rule flipped from PRIMARY at a time.
4. Writes every output CSV/JSON listed in `DATA_MANIFEST.md` and prints the
   git SHA + file hashes to stdout.

## Verifying independently

```
sha256sum data/nq_1m/nq_continuous_2018_2026_1m.csv data/vxn_daily_2018_2026.csv
```

Compare against `DATA_MANIFEST.md`. If the hashes differ, the data files are
not the canonical ones and results should not be compared against
`docs/NQ_STRICT_RECONCILIATION.md`.
