# OG Stage A Independent Verification Report

**Status: `STAGE_A_BLOCKED_DATA_MISMATCH`**

## Scope

Independent Stage A verification of `OG_CONFIG_CLEAN_BASELINE`, per the
handoff documentation recovered in commit `e304066` (branch
`docs/og-config-clean-baseline`) and the canonical strategy state on branch
`handoff/nq-strict-engine-v1` at commit
`a375818056ca435df021d60b111f5f58b1f3551f`.

This branch (`research/og-stage-a-independent-verification`) was created
directly from the canonical commit:

```
git checkout -b research/og-stage-a-independent-verification a375818056ca435df021d60b111f5f58b1f3551f
```

Verified HEAD:

```
a375818056ca435df021d60b111f5f58b1f3551f  Resolve NQ data provenance from raw Databento archives -- fully verified
```

No later research branch (Stage 0-5, OOS, ground-up/HMM) was merged in.

## Step 1-5: Documentation review

Read in full:
- `docs/OG_CONFIG_HISTORY.md`, `docs/OG_CONFIG_LIVE_RULES.md`,
  `docs/OG_CONFIG_NEXT_RESEARCH.md`, `configs/OG_CONFIG_CLEAN_BASELINE.yaml`
  (from commit `e304066`)
- `docs/REPRODUCIBILITY.md`, `docs/DATA_PIPELINE.md`,
  `docs/KNOWN_LIMITATIONS.md`, `data/README.md` (canonical commit)

These establish the exact required inputs and reproduction procedure.

## Step 2-3 (Data verification): result

Required files per `data/README.md`:

| File | Expected SHA-256 | Expected size | Present in this environment? |
|---|---|---|---|
| `data/nq_1m/nq_continuous_2018_2026_1m.csv` | `3d0228fcc17a40933d4fdc3983a8153e5bb6445ed9e743919b3eb5c516e53880` | ~211 MB, 2,964,655 rows | **No** |
| `data/vxn_daily_2018_2026.csv` | `76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e` | ~176 KB | **Yes — verified match** |

Actual command run:

```
sha256sum data/vxn_daily_2018_2026.csv
# 76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e  data/vxn_daily_2018_2026.csv
```
Matches the manifest exactly.

The NQ 1-minute bars file is deliberately excluded from version control
(211 MB, `.gitignore`'d per `data/README.md`). No portable retrieval script
exists in the repo, no raw Databento archives are present in this
environment, and there is no network access to Databento available here.
Filesystem search confirmed:
- `data/nq_1m/` directory does not exist in this checkout.
- No file matching `nq_continuous*` or raw Databento archive names
  (`nq2018.zip`, `nq2020.zip`, `nq2021.zip`, `nq2023.zip`, `nq2025.zip`)
  exists anywhere on this filesystem.
- No other branch in this repository (checked: `handoff/nq-strict-engine-v1`,
  `verification/claude-baseline-v1`, `strict-one-position-reconciliation`,
  `main`, all `research/*` and `codex/*` branches) contains the bars file —
  only the same construction script (`scripts/build_nq_continuous.py`),
  which itself requires the same absent raw archives.

`scripts/build_or_verify_data.py --bars data/nq_1m/nq_continuous_2018_2026_1m.csv --vxn data/vxn_daily_2018_2026.csv`
fails at the bars-file check because the file does not exist.

## Consequence

Per `docs/DATA_PIPELINE.md` / `data/README.md`: "If the hash or row count
does not match, do not proceed — you do not have the canonical dataset, and
no downstream number in this handoff will reproduce." No synthetic or
substitute data is permitted, and none was used.

As a result, the following required Stage A steps **could not be executed**
in this environment and are not reported:
- Running `src/strict_engine.py` and `src/independent_strict_engine.py`
- Physical-touch / trade / exit ledger generation and hashing
- Headline, yearly, and session metric recomputation
- Two-engine agreement comparison
- Adversarial invariant tests that require real market data
  (causality/truncation test, TP/SL ambiguity resolution, forced-liquidation
  bound, SAL state transitions, deterministic-rerun byte-diff)

No numbers, hashes, or ledger contents for these steps are fabricated or
estimated. This report intentionally leaves them absent rather than
substituting placeholder or synthetic figures.

## What this branch contains

- Canonical config unchanged: `configs/nq_current_config.yaml`
- Canonical engines unchanged: `src/strict_engine.py`,
  `src/independent_strict_engine.py`
- This report, documenting the blocker precisely.

No `outputs/*` ledger/reconciliation files are included because no engine
run was possible.

## To unblock

Place `nq_continuous_2018_2026_1m.csv` (sha256
`3d0228fcc17a40933d4fdc3983a8153e5bb6445ed9e743919b3eb5c516e53880`,
2,964,655 rows) at `data/nq_1m/nq_continuous_2018_2026_1m.csv` in an
environment with access to it, then re-run:

```
python3 scripts/build_or_verify_data.py \
    --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
    --vxn  data/vxn_daily_2018_2026.csv
```

Once this prints `DATA VERIFICATION: PASS`, Stage A verification can resume
from engine execution (step 6 of `docs/REPRODUCIBILITY.md`) on this same
branch.

## Final status

**`STAGE_A_BLOCKED_DATA_MISMATCH`** — required canonical input data
(`data/nq_1m/nq_continuous_2018_2026_1m.csv`) is absent from this
environment, with no substitute used. All other verification steps that
depend on it are withheld rather than fabricated.
