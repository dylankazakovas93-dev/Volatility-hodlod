# Phase 0 — Independent Engine Reproduction

Status: **EXACT MATCH**

Per explicit user instruction, Phase 1 (the 384-configuration preregistered
search) is withdrawn and not authorized. This document covers Phase 0 only:
independent reproduction of the canonical strict-engine result.

## Canonical reference

- Repository: `dylankazakovas93-dev/Volatility-hodlod`
- Branch: `strict-one-position-reconciliation`
- Final documentation commit: `306aa310e63814e5a55f40ced7d47532d3147bc7`
- Source-code commit: `8943c9cd18e586c1e185778d60809e4c5b12289e`
- Output commit: `1dd090df20e26c0c03fb117bc99f7803dd8d015f`

## 1. Data verification

```
bars rows      : 2,964,655   (expected 2,964,655)   MATCH
bars sha256    : 3d0228fcc17a40933d4fdc3983a8153e5bb6445ed9e743919b3eb5c516e53880   MATCH
vxn  sha256    : 76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e   MATCH
```

## 2. Reference engine re-run (same script, same commit)

```
python3 scripts/reconcile_strict_one_position.py \
    --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
    --vxn  data/vxn_daily_2018_2026.csv \
    --out-dir outputs
python3 -m pytest tests/test_nq_strict_invariants.py -v
```

Result: identical output hashes to the committed baseline
(`nq_strict_executed.csv`, `nq_eligible_1841.csv`, `nq_strict_yearly.csv` all
byte-identical), all 18 invariant tests pass, executed=1107, net=+6648.17,
PF=1.2924, TP/SL/BE/cutoff=394/333/281/99, negative years [2019, 2023, 2024].

## 3. Independent second implementation

`scripts/independent_nq_strict_engine.py` is a freshly-written engine. It
does **not** import or call `reconcile_strict_one_position.py`'s or
`nq_cond_be45.py`'s simulation/state-machine code. It reuses only
`volgen.levels.generate_levels()` and the OHLCV/VXN loaders — level
placement is explicitly not one of the frozen execution mechanics under
test. Everything downstream (touch detection, valid-entry-window /
session-cutoff logic, hourly-range anchor computation, the single-global-
position + time-aware-SAL causal state machine, conditional BE at bar 45,
stop-first touch-bar handling, fill policy, oldest-level-first simultaneous
ordering, and PF over all exit types) is independently coded from scratch.

```
python3 scripts/independent_nq_strict_engine.py \
    --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
    --vxn  data/vxn_daily_2018_2026.csv \
    --out-dir outputs
```

Result:

```
executed        : 1107
net_pts         : 6648.17
PF              : 1.2924
TP/SL/BE/cutoff : 394/333/281/99
negative years  : [2019, 2023, 2024]
```

Identical to the canonical reference on every headline number.

## 4. Row-by-row comparison

```
python3 scripts/compare_strict_ledgers.py \
    --reference outputs/nq_strict_executed.csv \
    --comparison outputs/nq_independent_executed.csv
```

```
reference rows            : 1107
comparison rows           : 1107
matched                    : 1107
only in reference          : 0
only in comparison         : 0
same entry, diff exit      : 0
same entry/exit, diff pnl  : 0
FULLY REPRODUCED: True
```

Every one of the 1,107 executed rows matches on identity key (level_id,
entry timestamp, side, session date), exit reason, and P&L (within
floating-point tolerance). Zero divergence in any category.

## 5. Final status

**EXACT MATCH.** Two independently-coded implementations, given the same
canonical input data, produce a bit-identical trade population and
identical per-trade outcomes. This is the strongest form of confirmation
available short of a third, differently-authored implementation.

Machine-verifiable via `tests/test_independent_engine_matches_canonical.py`
(4 tests, all passing) in addition to the existing 18-test invariant suite.

## Reproduction commands (all three, in order)

```
python3 scripts/reconcile_strict_one_position.py --bars data/nq_1m/nq_continuous_2018_2026_1m.csv --vxn data/vxn_daily_2018_2026.csv --out-dir outputs
python3 scripts/independent_nq_strict_engine.py --bars data/nq_1m/nq_continuous_2018_2026_1m.csv --vxn data/vxn_daily_2018_2026.csv --out-dir outputs
python3 scripts/compare_strict_ledgers.py --reference outputs/nq_strict_executed.csv --comparison outputs/nq_independent_executed.csv
python3 -m pytest tests/test_nq_strict_invariants.py tests/test_independent_engine_matches_canonical.py -v
```

## Explicitly out of scope for this task

Per user instruction, no configuration grid, optimization, walk-forward
selection, master holdout, bootstrap, or ES research was performed. The
previously-proposed 384-configuration preregistered search is withdrawn and
unauthorized. This document reports Phase 0 only.
