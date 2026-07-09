# Data Contract — VXN + NQ Strategy Verification Package

## Required Data Files

These files must exist in the repository root (`/workspaces/Volatility-hodlod/`) before running the full verification suite.

### Market Data (Gitignored — Must Be Provisioned Separately)

| File | Path | Expected SHA-256 | Status in Repo |
|---|---|---|---|
| NQ 1-minute continuous bars | `data/nq_1m/nq_continuous_2018_2026_1m.csv` | `9f427eb053b6c63e50f79baf666f239f851558d1558e706fc126cbe69f3a5af4` (reconstructed, harmless) or `3d0228fcc17a40933d4fdc3983a8153e5bb6445ed9e743919b3eb5c516e53880` (manifest) | Gitignored via `.gitignore:1` |

### VXN Daily Data (Committed — Always Present)

| File | Path | Expected SHA-256 | Status |
|---|---|---|---|
| VXN daily close | `data/vxn_daily_2018_2026.csv` | `76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e` | VERIFIED |

### Frozen Component Ledgers (Committed — Always Present)

| File | Path | Expected Rows | Status |
|---|---|---|---|
| External 2013-2015 trades | `outputs/og_external_2013_2015/operational_100r_trades.csv` | 315 | VERIFIED |
| Build years trades | `outputs/og_build_years/final_buildoff_A_build_years_trades.csv` | 407 | VERIFIED |
| Validation trades | `outputs/og_validation/OG_OPERATIONAL_100R_validation_trades.csv` | 633 | VERIFIED |

### Frozen Artifacts (Committed — Always Present)

| File | Path | Description |
|---|---|---|
| Gated benchmark | `artifacts/og_operational_100r_fidelity/gated_benchmark.csv` | 1,355 shadow rows with is_flat decisions |
| Assembled shadow | `artifacts/og_operational_100r_fidelity/assembled_shadow.csv` | Raw shadow sequence before gating |

## Python Dependencies

| Package | Minimum Version |
|---|---|
| pandas | >=2.0 |
| numpy | >=1.24 |
| pytest | >=7.0 |
| PyYAML | >=6.0 |

## Gitignore Rules

From `.gitignore` at the current HEAD (173d036):

```
data/nq_1m/
data/external_2013_2015/raw/*.csv
data/external_2013_2015/normalized/*.csv
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
outputs/og_build_years/_cache.pkl
```

The NQ 1-minute bar data must be reconstructed from raw Databento archives via `scripts/build_nq_continuous.py` or restored from separate storage before running engine tests.
