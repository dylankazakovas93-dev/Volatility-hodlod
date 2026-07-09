# Test Matrix — OG_OPERATIONAL_100R Verification

## Summary

| File | Count | Category |
|---|---|---|
| `test_og_rules.py` | 72 | Stage 1: Strategy rules |
| `test_level_generation.py` | 13 | Stage 2: Level generation |
| `test_causality.py` | 13 | Stage 4: Causality + shadow assembly |
| **Total** | **98** | |

## `test_og_rules.py` (72 tests)

| Area | Tests | Coverage |
|---|---|---|
| Position management | 8 | No-stacking, no overlap, one-global-position, no same-minute re-entry |
| Physical touch detection | 8 | In/out range, boundary cases, creation/expiry bar exclusion |
| Entry restrictions | 8 | 11:00-15:00 block, prop hard blackout 16:00-19:00, inclusive/exclusive boundaries |
| Stop and target | 8 | Stop distance cap at 200, hourly-range-based, 1R target |
| BE45 simulation | 12 | Threshold, retouch window, cancel window, determinism |
| Rolling PF gate | 12 | R computation, symmetric t=1.10 threshold, warmup, flat handling |
| Cutoff logic | 8 | Pre-15:00, post-19:00, 15:00-19:00 gap, next-day cutoff |
| Determinism | 8 | Deterministic on multiple identical runs |

## `test_level_generation.py` (13 tests)

| Area | Tests | Coverage |
|---|---|---|
| Sigma formula | 4 | cash_open * vxn/100 / sqrt(252), multiplier 1.25 |
| Initial balance range | 3 | Fixed offset 15.75, IB window 09:30-10:30 ET |
| Line expiry | 3 | 20-session expiry, creation bar excluded, expiry bar excluded |
| VXN priors | 3 | Prior level reference for VXN lookup on same-day entries |

## `test_causality.py` (13 tests)

| Area | Tests | Coverage |
|---|---|---|
| Prefix invariance | 1 | Truncating history before shadow period produces identical gated output |
| Append invariance | 1 | Appending future trades does not change prior ON/OFF decisions |
| Current row excluded | 1 | Row X cannot use its own trade to compute rolling PF for its own is_flat decision |
| Future row excluded | 1 | Row X cannot use row X+1's trade in its rolling PF window |
| Warmup | 1 | First 100 rows explicitly ON regardless of rolling PF value |
| Zero-loss denominator | 1 | R computation handles zero-loss case without division error |
| Symmetric gate | 1 | t=1.10 threshold same for ON→OFF and OFF→ON transitions |
| OFF rows influence | 1 | OFF rows contribute to subsequent ON decisions via rolling PF |
| Determinism | 1 | Repeated run produces identical gated output |
| Shadow assembly | 4 | 315 + 407 + 633 = 1,355 rows; all 3 component ledgers included; chronological order; correct row counts per year