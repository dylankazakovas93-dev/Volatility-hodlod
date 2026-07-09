# ES/VIX Level Discovery & MAE/MFE — Progress

## Stage 0 — Evidence Lock (first attempt — rejected by audit)❌

Commit `00711afa567a75a549dd11069a2b42297b377cf3` was rejected by direct
research audit because it used an incomplete specification, a future-aware
noncausal ES builder, and an incorrect holdout firewall.

The prior commit is preserved in history but is not the valid evidence lock.

## Stage 0 — Corrected Evidence Lock ✅

- [x] Complete standalone MASTER_PLAN.md written (level discovery only, no
      trade management, full formula, MAE/MFE contract, chronological gates)
- [x] Corrected branch: `research/es-vix-level-mae-mfe-discovery`
- [x] Official Cboe VIX acquired and validated: 9,224 daily rows, 1990–2026,
      0 duplicates, 0 nulls
- [x] Causal ES continuous builder implemented: `build_es_continuous_causal.py`
      uses prior-session volume dominance, never same-day volume
- [x] Causal ES continuous 1m CSV: 2,804,976 rows, 34 contracts, 33 roll days
- [x] Causal roll schedule: 33 clean quarterly rolls, Good Friday gap handled
- [x] Corrected GRID_DEFINITION.json: 6 sigma × 2 IB × 11 offset = 132 configs
- [x] Corrected TRIAL_REGISTRY.csv: 132 deterministic config IDs, all registered
- [x] Corrected HOLDOUT_LOCK.json: 2025-01-01 to end, one indivisible block,
      UNOPENED, outcome_columns_read=false
- [x] No stop, target, BE, blackout, or strategy-management fields anywhere
- [x] data_manifest.json with outer ZIP SHA-256, causal ES hash, all hashes
- [x] 43 Stage 0 corrected tests all passing
- [x] No performance outcomes generated, no runs directory
- [x] No 2025–2026 OHLC values inspected for strategy purposes
- [x] No level grid executed
- [x] Frozen NQ/VXN branch untouched

## Stage 1 — Not Started

## Stage 2 — Not Started