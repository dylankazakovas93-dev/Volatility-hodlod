# Research Changelog

## NQ Strict Reconciliation

- Added `scripts/recover_codex_1116.py`.
- Added `scripts/reconcile_strict_one_position.py`.
- Added strict state-machine assertions in `tests/test_strict_engine.py`.
- Generated recovered local 1,116-row output artifact.
- Generated local physical-touch, eligible-candidate, executed, skipped, yearly, sensitivity, cost, collision, gap, and concentration outputs.
- Documented canonical data mismatch and explicitly labelled the current run as local replay.
- Corrected annual-result record: 2019 is negative, 2018 and 2024 are near flat.

