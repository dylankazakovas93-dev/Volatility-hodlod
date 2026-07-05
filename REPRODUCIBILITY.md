# Reproducibility

## Branch

`codex/nq-strict-reconciliation`

## Primary Commands

Recover prior local 1,116-row output artifact:

```bash
python3 scripts/recover_codex_1116.py
```

Run strict one-position reconciliation and falsification harness:

```bash
python3 scripts/reconcile_strict_one_position.py
```

Run assertions:

```bash
python3 -m pytest tests/test_strict_engine.py -q
```

## Current Verification

`python3 -m pytest tests/test_strict_engine.py -q`

Result:

```text
6 passed
```

## Canonical Guard

The script only labels the result canonical when both guards pass:

- bars rows = 2,964,655
- eligible candidates = 1,841

The current local workspace does not pass:

- bars rows = 2,965,023
- eligible candidates = 1,835

Therefore current output is `FAILED_REPRODUCTION_LOCAL_REPLAY`.

