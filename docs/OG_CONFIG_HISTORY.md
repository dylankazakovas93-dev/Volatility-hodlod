# OG_CONFIG_CLEAN_BASELINE -- Recovery and Lineage

Status: **`OG_CONFIG_CLEAN_BASELINE__VALID_RESEARCH_STARTING_POINT`**

This document recovers the original (pre-Stage-0) strategy configuration
directly from git history, committed files, code, reports, and ledgers --
no remembered numbers or conversational descriptions were used. Every claim
below is backed by a git command whose output is shown or can be
reproduced verbatim.

## 1. Exact identification

| Item | Value |
|---|---|
| Canonical branch | `handoff/nq-strict-engine-v1` |
| Canonical commit (full SHA) | `a375818056ca435df021d60b111f5f58b1f3551f` |
| Parent commit | `d5d6e48e6785de6cfe330455d62796250f0f7ce6` (root/orphan commit, no further parent) |
| Configuration path | `configs/nq_current_config.yaml` |
| Primary engine path | `src/strict_engine.py` |
| Independent cross-check engine path | `src/independent_strict_engine.py` |
| Run entrypoint | `scripts/run_current_config.py` (thin wrapper around `python3 -m src.strict_engine`) |
| Rules document | `docs/STRATEGY_RULES.md` |
| Config index document | `docs/CURRENT_CONFIG.md` |
| Report path | `docs/REPRODUCIBILITY.md`, `docs/KNOWN_LIMITATIONS.md`, `docs/DATA_PIPELINE.md`, `docs/ENGINE_ARCHITECTURE.md` |
| Ledger paths | `outputs/baseline_executed.csv`, `outputs/baseline_skipped.csv`, `outputs/baseline_physical_touches.csv`, `outputs/baseline_eligible_1841.csv`, `outputs/baseline_yearly.csv`, `outputs/baseline_summary.json`, `outputs/independent_executed.csv`, `outputs/engine_comparison.json` |
| Data/output manifests | `manifests/data_manifest.json`, `manifests/output_manifest.json`, `manifests/raw_file_inventory.csv` |

A second, independently-verified sibling commit exists one step further:

| Item | Value |
|---|---|
| Branch | `verification/claude-baseline-v1` |
| Commit | `f99c8fdcc7b4925fc3622dc672bc4e8d033ebbb2` |
| Relationship to canonical commit | direct child of `a375818`, adds only verification artifacts under `verification_outputs/` -- confirmed with `git diff a375818:configs/nq_current_config.yaml f99c8fd:configs/nq_current_config.yaml` (zero output) and `git diff a375818:src/strict_engine.py f99c8fd:src/strict_engine.py` (zero output) |
| Why it's not the canonical pointer | **not** in the Stage 0-5 research lineage -- confirmed below |

### Lineage proof

```
$ git merge-base research/claude-stage0-excursions verification/claude-baseline-v1
a375818056ca435df021d60b111f5f58b1f3551f

$ git merge-base --is-ancestor f99c8fd research/claude-stage0-excursions
# exit 1 (NOT an ancestor)
```

Every one of the seven research/OOS branches (`research/claude-stage0-
excursions` through `research/claude-final-oos`) forks directly from
`a375818`, confirmed individually:

```
$ for b in research/claude-stage0-excursions research/claude-stage1-tpsl-v1 \
    research/claude-stage2-timewindow-sal research/claude-stage3-be-scratch \
    research/claude-stage4-garch-hmm research/claude-stage5-window-cutoff \
    research/claude-final-oos; do
    git merge-base --is-ancestor a375818 $b && echo "$b: a375818 is ancestor"
  done
# all seven print "a375818 is ancestor"
```

So `a375818` -- not `f99c8fd` -- is the true, exact fork point of every
subsequent piece of research in this repository. `f99c8fd` is documented
here as corroborating independent verification, not as the canonical
pointer.

### Root commit

`d5d6e48` has no parent (`git rev-list --max-parents=0 f99c8fd` returns only
`d5d6e48...`). Its commit message states explicitly that it is an
**orphan branch** created to contain "only what's needed to understand,
run, and verify the current frozen NQ strict engine -- no old
overlap-permitting engines, no previous configuration searches, no ES
work, no unrelated research." The excluded pre-handoff history (GC-level
experiments, ATR/VXN regime studies, ES sibling work, and at least one
configuration-reconciliation phase) still exists in this repository under
`remotes/origin/strict-one-position-reconciliation` and other stale
branches, referenced by the handoff commit message as "research-repo
commit 1dd090d/c974454." That branch is **superseded historical code** --
mentioned here only for completeness. It is not given a canonical label,
its numbers are not reproduced, and no future research should treat it as
a starting point.

### Configuration immutability proof

The configuration, primary engine, and level-generation code are
byte-identical from the original handoff commit all the way to the current
HEAD of the locked-OOS research line -- i.e. every Stage 0-5 and OOS
experiment ran on top of this exact, unmodified OG code:

```
$ git diff d5d6e48:configs/nq_current_config.yaml 7e29fba:configs/nq_current_config.yaml
# (no output)
$ git diff d5d6e48:src/strict_engine.py 7e29fba:src/strict_engine.py
# (no output)
$ git diff d5d6e48:src/level_generation.py 7e29fba:src/level_generation.py
# (no output)
```

(`7e29fba` = the `OOS_RESULTS` commit tip of `research/claude-final-oos` at
the time this document was written.)

## 2. Data hashes

| File | SHA-256 | Notes |
|---|---|---|
| `data/nq_1m/nq_continuous_2018_2026_1m.csv` | `3d0228fcc17a40933d4fdc3983a8153e5bb6445ed9e743919b3eb5c516e53880` (recorded in `manifests/data_manifest.json` and `configs/nq_current_config.yaml`) | **Known, previously-disclosed environment discrepancy**: the actual bars file present in this execution environment hashes to `9f427eb053b6c63e50f79baf666f239f851558d1558e706fc126cbe69f3a5af4` instead. This was identified during the independent verification stage (`f99c8fd`, extensively diagnosed -- ruled out pandas/numpy version, duplicate timestamps, volume ties, sub-second timestamps, line-ending/BOM/quoting) and re-disclosed at every subsequent stage (Stage 5, the locked OOS test) rather than silently reconciled. Row count, span, contract count, and roll structure all match exactly; only the top-level byte hash differs, consistent with a serialization artifact rather than a content divergence. |
| `data/vxn_daily_2018_2026.csv` | `76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e` | Matches exactly in this environment (verified again while writing this document). |

## 3. Reproduction commands (verbatim from `README.md` / `docs/REPRODUCIBILITY.md`)

```
pip install -r requirements.txt
python3 scripts/build_or_verify_data.py --bars data/nq_1m/nq_continuous_2018_2026_1m.csv --vxn data/vxn_daily_2018_2026.csv
python3 -m src.strict_engine --bars data/nq_1m/nq_continuous_2018_2026_1m.csv --vxn data/vxn_daily_2018_2026.csv --out-dir outputs
python3 -m src.independent_strict_engine --bars data/nq_1m/nq_continuous_2018_2026_1m.csv --vxn data/vxn_daily_2018_2026.csv --out-dir outputs
python3 scripts/compare_engines.py --reference outputs/baseline_executed.csv --comparison outputs/independent_executed.csv
python3 -m pytest tests/ -v
```

Or all at once: `python3 scripts/verify_handoff.py --bars ... --vxn ...`.

## 4. Historical reproduction target (for Stage-A verification only)

This section exists **only** because `docs/OG_CONFIG_NEXT_RESEARCH.md`
Stage A requires reproducing this exact headline number as a go/no-go gate
before any future experiment may begin. It is not a claim about future
performance and must not be treated as a headline result for any purpose
beyond exact-reproduction verification:

```yaml
eligible_candidates: 1841
executed_trades: 1107
net_pts: 6648.17
PF: 1.2924
avg_trade: 6.006
TP: 394
SL: 333
BE: 281
cutoff: 99
max_drawdown: -1290.29
negative_years: [2019, 2023, 2024]
numerical_tolerance: {net_pts: 0.05, PF: 0.0005}
```

Two independently-coded engines (`src/strict_engine.py`,
`src/independent_strict_engine.py`) reproduce all 1,107 trade rows exactly
against this number (`outputs/engine_comparison.json`).

## 5. Relationship to the ground-up Stage 0-5 / OOS research

The entire Stage 0 through Stage 5 research program, and the subsequent
`LOCKED_NONCONSECUTIVE_HOLDOUT` test, is a **separate strategy**
constructed from scratch on top of this OG data and physical-touch
infrastructure -- it does not modify, tune, or replace the OG
configuration above. It is labeled:

**`GROUND_UP_F2_HMM_CONFIG__OOS_WEAK__REJECTED_FOR_DEPLOYMENT`**

(branch `research/claude-final-oos`, commit `7e29fbad2437ccbf6f4e7783d07b20af073dc412`;
locked reserved-year result: `OOS_MARGINAL_PASS`, with pooled performance
dominated by a single year -- see `docs/OOS_RESULTS_REPORT.md`.)

The two labels must never be conflated. "Audit the OG config" always means
`OG_CONFIG_CLEAN_BASELINE` (`configs/nq_current_config.yaml` /
`src/strict_engine.py`, commit `a375818`); it never means anything under
`configs/stage*_selected.yaml` or `scripts/oos_engine.py`.
