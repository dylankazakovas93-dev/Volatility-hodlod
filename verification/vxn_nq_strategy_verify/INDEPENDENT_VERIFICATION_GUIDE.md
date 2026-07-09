# Independent Verification Guide — OG_OPERATIONAL_100R

## Prerequisites

1. Python 3.12+ with `pandas>=2.0`, `numpy>=1.24`, `pytest>=7.0`, `PyYAML>=6.0`
2. NQ 1-minute continuous bars file at `data/nq_1m/nq_continuous_2018_2026_1m.csv`
   - SHA-256: `9f427eb053b6c63e50f79baf666f239f851558d1558e706fc126cbe69f3a5af4`
   - 2,964,655 rows, span 2018-01-01 to 2026-06-07
   - Rebuild from raw Databento archives via `scripts/build_nq_continuous.py`
3. VXN daily data at `data/vxn_daily_2018_2026.csv`
   - SHA-256: `76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e`

## Quick Verification

```bash
cd /path/to/Volatility-hodlod
pip install pandas numpy pytest PyYAML
python -m pytest reproduction/og_operational_100r/ -v
./verification/vxn_nq_strategy_verify/reproduce_and_verify.sh
```

## What the Verification Script Checks

1. Repository branch is correct
2. NQ data file exists and SHA-256 matches
3. VXN data file exists and SHA-256 matches
4. OG_OPERATIONAL_100R.yaml config SHA-256 matches
5. Every file in the package matches its ARTIFACT_HASHES.sha256 entry
6. All 98 tests pass
7. Benchmark metrics are regenerated and compared against expected values
8. Output hash matches the frozen `gated_benchmark.csv`
9. Determinism: re-run produces identical hash

## How to Verify Without NQ Data

If NQ data is absent, the verification script will fail at step 2. The NQ data is required for all fidelity tests — there is no "skip NQ" mode.

## Package Integrity

SHA-256 of `ARTIFACT_HASHES.sha256`: computed at package creation time and recorded in the commit. Run `sha256sum verification/vxn_nq_strategy_verify/ARTIFACT_HASHES.sha256` to verify the manifest itself is untampered.