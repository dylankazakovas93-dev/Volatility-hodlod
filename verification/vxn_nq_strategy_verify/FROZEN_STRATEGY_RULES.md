# Frozen Strategy Rules — OG_OPERATIONAL_100R

Frozen parameters and behavioral invariants from `canonical_config.json`, `_synthetic_helpers.py`, and the frozen `src/strict_engine.py`.

## Constants

| Constant | Value | Source |
|---|---|---|
| SL_CAP | 200.0 points | `_synthetic_helpers.py:20` |
| BE_BARS | 45 bars | `_synthetic_helpers.py:21` |
| ROLLING_WINDOW | 100 trades | `_synthetic_helpers.py:22` |
| SHUTDOWN_THRESHOLD | 1.10 | `_synthetic_helpers.py:23` |
| REENTRY_THRESHOLD | 1.10 | `_synthetic_helpers.py:24` |
| ENTRY_BLOCKED_START | 660 (11:00 ET) | `_synthetic_helpers.py:27`, frozen `strict_engine.py:43` |
| ENTRY_BLOCKED_END | 900 (15:00 ET) | `_synthetic_helpers.py:28` |
| PROP_HARD_BLACKOUT_START | 960 (16:00 ET) | `_synthetic_helpers.py:31` |
| PROP_HARD_BLACKOUT_END | 1140 (19:00 ET) | `_synthetic_helpers.py:32` |

> **Note**: The configuration YAML claims a 10:00-15:00 block, but the frozen engine code at `strict_engine.py:43` enforces an 11:00-15:00 block. The test suite was corrected to match the engine, not the config comment.

## Level Generation

- **RTH**: 09:30-16:00 ET
- **IB**: 60 minutes (09:30-10:30 ET)
- **Sigma day**: `cash_open * (vxn/100) / sqrt(252)`
- **Sigma multiplier**: 1.25
- **Fixed offset**: 15.75 points (for NQ)
- **Level expiry**: 20 sessions (`line_days = 20`)
- **Creation bar excluded** from touch eligibility
- **Expiry bar excluded** from touch eligibility

## Position Rules

- **One global position**: no stacking, no overlap
- **No same-minute re-entry**
- **Permanent touch consumption**: blocked/rejected touches never revived
- **Simultaneous touch tie-break**: oldest level wins

## Entry Restrictions

- **Entry blocked**: 11:00-15:00 ET (inclusive-exclusive)
- **Prop hard blackout**: 16:00-19:00 ET (inclusive-exclusive)
- **Cutoff**: 15:00 ET same day for touches before 15:00; 15:00 ET next day for touches at/after 19:00; no valid cutoff for touches 15:00-19:00

## Stop and Target

- **Stop distance**: `min(1.5 * hourly_range, 200.0)`
- **Stop (long)**: `entry - stop_distance`
- **Stop (short)**: `entry + stop_distance`
- **Target**: 1.00R (`entry + stop_distance` for long, `entry - stop_distance` for short)
- **Stop checked before target** on every managed bar

## BE45 Management

- **One-shot BE check** at rest[45] (zero-based index 45 after touch bar)
- Rest[0] through rest[44] use original stop
- **BE eligibility (short)**: bar open <= entry
- **BE eligibility (long)**: bar open >= entry
- **Failed BE check never repeats** — original stop retained permanently
- **BE exit** fills exactly at entry (zero PnL)
- BE fill not worsened by gap-through

## Rolling PF Gate

- **Window**: 100 prior trades `[i-window, i)`
- **Warmup**: first 100 rows always ON
- **Shutdown**: PF < 1.10 → OFF
- **Re-entry**: PF >= 1.10 → ON
- **Symmetric**: same threshold for shutdown and re-entry
- **Current row excluded** from own PF calculation
- **OFF rows remain** in shadow and influence future windows

## Data Firewall

- **Build years**: 2018, 2020, 2023, 2026 (partial)
- **Excluded years** (never used for outcomes): 2019, 2021, 2022, 2024, 2025
- **Absent years**: 2016, 2017

## Determinism

All operations produce identical output on repeat runs. No random state is used in the engine or gate logic.
