# NQ Phase 0 Final Canonical Engine Reconciliation

## Scope

Only Phase 0 was performed. No configuration grid, parameter search,
walk-forward selection, master holdout, bootstrap, ES research, or alternate
configuration testing was run.

## Authoritative Reference

Repository: `https://github.com/dylankazakovas93-dev/Volatility-hodlod`

Branch: `strict-one-position-reconciliation`

Commits verified:

- Final documentation commit: `306aa310e63814e5a55f40ced7d47532d3147bc7`
- Source-code commit: `8943c9cd18e586c1e185778d60809e4c5b12289e`
- Output commit: `1dd090df20e26c0c03fb117bc99f7803dd8d015f`

## Canonical Artifact Verification

At `306aa310e63814e5a55f40ced7d47532d3147bc7`:

| Artifact | Rows | SHA-256 |
|---|---:|---|
| `outputs/nq_strict_executed.csv` | 1,107 | `b9419b1be06310a179ec7c7fb05f6c4a4189ab9951ebfe3f5e42be19f4a0e56a` |
| `outputs/nq_eligible_1841.csv` | 1,841 | `610e3b60f3bcd86b8caa23f484f0dde1e4d576ef84bdd6f3ff0a2ce9e6e1d416` |
| `outputs/nq_strict_yearly.csv` | 9 | `adca71291b2df18c1389bbbcbe5b94bab5795ca40a5f770c2b274c035db56015` |
| `data/vxn_daily_2018_2026.csv` | 2,139 | `76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e` |

Canonical result recorded in `outputs/nq_strict_summary.json`:

- eligible candidates: 1,841
- executed trades: 1,107
- net: +6,648.17 points
- PF: 1.2924
- average trade: +6.006 points
- max drawdown: -1,290.29 points
- TP / SL / BE / cutoff: 394 / 333 / 281 / 99
- negative years: 2019, 2023, 2024

## Source Rerun Status

Required command:

```bash
python3 scripts/reconcile_strict_one_position.py \
  --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
  --vxn data/vxn_daily_2018_2026.csv \
  --out-dir outputs
```

Status: blocked. The canonical bars file is not tracked in the cloned branch
and was not found locally.

Missing file:

`data/nq_1m/nq_continuous_2018_2026_1m.csv`

Expected properties:

- rows: 2,964,655
- SHA-256: `3d0228fcc17a40933d4fdc3983a8153e5bb6445ed9e743919b3eb5c516e53880`

## Test Status

Command:

```bash
python3 -m pytest tests/test_nq_strict_invariants.py -v
```

Result in the cloned authoritative branch:

- 15 passed
- 3 failed

The three failures are all caused by the missing canonical bars file:

- `test_canonical_bar_count`
- `test_canonical_data_hashes`
- `test_eligible_candidate_gate`

The generated-output and state-invariant tests pass.

## Codex Independent Local Replay

Codex branch:

`codex/nq-strict-reconciliation`

Latest Codex commit:

`7072136639f089b031ddc040b5ec9fbc4c1971cc`

Codex local replay remains explicitly noncanonical because it used a different
local bars file:

- local bars rows: 2,965,023
- local bars SHA-256: `018e84c9edeabed942dce7bb0904943e36b9fd68c6cc4fc5dda1f40b733251ba`
- local eligible candidates after cutoff fix: 1,834
- local executed trades: 1,116
- local net: +8,757.72
- local PF: 1.3805

The prior 1,117-count inconsistency was resolved. The extra row was:

- `level_id`: `472:upper`
- touch: `2019-11-03 21:37:00-05:00`
- exit: `no_path`
- PnL: `0.0`
- cause: cutoff timestamp was earlier than touch timestamp across the DST/session boundary.

The independent engine now requires `cutoff > touched_at`, so that row is
skipped rather than executed.

## Row-Level Comparison Against Canonical Executed Ledger

Comparison output:

- `outputs/codex_vs_claude1_summary.json`
- `outputs/codex_vs_claude1_differences.csv`

Summary:

- matched rows: 1,032
- canonical-only rows: 62
- implementation-only rows: 71
- same entry with different exit: 7
- same exit with different P&L: 6
- total P&L effect, canonical minus Codex local: -2,109.5531 points
- first chronological divergence: Codex-only `4_upper`, touch `2018-01-09 12:29:00+00:00`, exit `BE`, PnL `0.0`

Because the input bars differ, this is a comparison against committed canonical
outputs, not an independent canonical-data rerun.

## Final Phase 0 Status

`FAILED REPRODUCTION`

Reason: canonical generated artifacts verify, but the canonical bars file is
not available in the repository clone or local disk, so the exact source rerun,
canonical input hash verification, and 18/18 invariant test pass cannot be
completed in this environment.

