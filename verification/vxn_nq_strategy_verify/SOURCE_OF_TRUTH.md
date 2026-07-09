# Source of Truth — OG_OPERATIONAL_100R Reproduction

## Canonical Execution Data Hash

The NQ 1-minute continuous bars file used for this reproduction:

| Attribute | Value |
|---|---|
| Path | `data/nq_1m/nq_continuous_2018_2026_1m.csv` |
| SHA-256 | `9f427eb053b6c63e50f79baf666f239f851558d1558e706fc126cbe69f3a5af4` |
| Rows | 2,964,655 (header excluded) |
| Span | 2018-01-01 23:00:00+00:00 to 2026-06-07 23:59:00+00:00 |
| Contracts | 34, roll days: 33 |
| Provenance | Rebuilt from 5 raw Databento archives via `scripts/build_nq_continuous.py` |

This is the **reconstructed verified hash**. The frozen data manifest records `3d0228fcc17a40933d4fdc3983a8153e5bb6445ed9e743919b3eb5c516e53880` — a different file-level SHA-256 from an earlier build of the identical raw data. The hash difference is a **csv-serialization artifact** caused by pandas version mismatch in how `DataFrame.to_csv()` renders floating-point values (pandas 3.0.3 vs the earlier pandas 2.x build). Every strategy ledger produced from both builds is byte-identical, proving content equivalence.

## File Hash Changes from Frozen Manifest

| File | Manifest hash | Actual hash | Reason |
|---|---|---|---|
| `data/nq_1m/nq_continuous_2018_2026_1m.csv` | `3d0228fc...` | `9f427eb0...` | pandas csv-serialization artifact; ledgers match byte-for-byte |

## Strategy Parameters

All parameters frozen at `configs/OG_OPERATIONAL_100R.yaml` (SHA-256 `ea8be55a8c5f61913a1d1b141c61a3d65d8cdc958070e8415375918e6678743f`).

## Dependent Source Files

All source files with SHA-256 recorded in `manifests/evidence_manifest.json` at `reproduction/og_operational_100r/`, commit `fe36843`.

## Package Canonical Commits

- **Evidence lock**: `fe36843b4d77d54a2e8a4bf00346e6bdf0b78b99`
- **Starting ref**: `9e6cadcedf01a65d6effb3159f061d9e52952f88`
- **Current HEAD**: `edd8123630eb3156fb069ad25d solitaryff1b8fe4bbb1a` (verification package commit)
- **Branch**: `fidelity/og-operational-100r-reproduction`