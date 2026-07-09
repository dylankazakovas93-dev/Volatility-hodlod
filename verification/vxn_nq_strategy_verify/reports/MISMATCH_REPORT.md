# Mismatch Report

No mismatches found between the independent reproduction and the frozen canonical outputs.

## Stage 3 — Strict Engine (1,107 trades)
- Zero mismatches across all 15 compared fields
- Entry/exit timestamps, prices, PnL, exit reasons all identical

## Stage 4 — Shadow Assembly + Rolling PF (1,355 rows)
- Zero is_flat mismatches
- All aggregate metrics match expected exactly

## Three Original Stage 1 Tests with Changed Boundaries
Three tests had stale 10:00-15:00 ET block boundaries corrected to the frozen 11:00-15:00 ET block.
These corrections were applied after verifying the frozen engine code at strict_engine.py:43.
The corrections tightened the test to match actual frozen behavior.
