# OG Stage-A Independent Verification Report

**Status: `STAGE_A_BLOCKED_DATA_MISMATCH`**

This is Stage A of independent verification/reproduction of the
`OG_CONFIG_CLEAN_BASELINE` (documentation pointer added in commit `e304066`)
against its target: canonical branch `handoff/nq-strict-engine-v1`, commit
`a375818056ca435df021d60b111f5f58b1f3551f` (config
`configs/nq_current_config.yaml`, engines `src/strict_engine.py` and
`src/independent_strict_engine.py`).

This work is verification only. No optimization, redesign, or parameter
change was made to any engine or config. Every number below was produced by
a command actually run in this session; none is transcribed from memory or
from a prior report without independent recomputation.

## 1. Branch / commit setup

```
git checkout -b research/og-stage-a-independent-verification a375818056ca435df021d60b111f5f58b1f3551f
```

Confirmed starting point:
```
$ git log -1 --format='%H %s'
a375818056ca435df021d60b111f5f58b1f3551f Resolve NQ data provenance from raw Databento archives -- fully verified
```

No Stage 0-5 or OOS branches were merged in. `docs/OG_CONFIG_HISTORY.md` and
related documentation files from commit `e304066`
(`docs/og-config-clean-baseline` branch) are referenced for context only;
the engine/config/data tree of this branch is exactly the canonical
commit's tree, apart from the new Stage-A artifacts added here.

## 2. Data verification (performed BEFORE any run attempt)

`configs/nq_current_config.yaml` / `manifests/data_manifest.json` /
`data/README.md` (all present at the canonical commit) require exactly two
input files:

| File | Required SHA-256 (per manifest) | Present in repo/environment? |
|---|---|---|
| `data/nq_1m/nq_continuous_2018_2026_1m.csv` (~211 MB, 2,964,655 rows, 2018-01-01T23:00Z .. 2026-06-07T23:59Z, columns `timestamp,open,high,low,close,volume,contract,roll_day`) | `3d0228fcc17a40933d4fdc3983a8153e5bb6445ed9e743919b3eb5c516e53880` | **NO -- absent** |
| `data/vxn_daily_2018_2026.csv` (2,139 rows, `date,open,high,low,close`) | `76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e` | **Yes** |

Commands run:
```
$ ls data/nq_1m
ls: cannot access 'data/nq_1m': No such file or directory

$ cat data/README.md
# Data
This directory intentionally does not contain the large canonical NQ
bars file ... (211 MB) ... excluded via .gitignore ...
"You must obtain nq_continuous_2018_2026_1m.csv out-of-band ..."

$ cat .gitignore
data/nq_1m/
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/

$ git lfs ls-files            # git-lfs is not even installed/used
git: 'lfs' is not a git command

$ git log --all --oneline -- 'data/nq_1m/*'
# (no output -- the file was never committed on ANY branch)

$ for b in origin/verification/claude-baseline-v1 origin/handoff/nq-strict-engine-v1 \
    origin/research/claude-stage0-excursions origin/strict-one-position-reconciliation; do
    git ls-tree -r $b --name-only | grep -i nq_1m
  done
# (no output on any branch)

$ sha256sum data/vxn_daily_2018_2026.csv
76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e  data/vxn_daily_2018_2026.csv   # MATCHES exactly
```

**Result: the canonical NQ 1-minute bars file
(`data/nq_1m/nq_continuous_2018_2026_1m.csv`) is genuinely absent from this
repository and this execution environment, on every branch.** It is not a
git-lfs pointer, not compressed elsewhere, not under an alternate path. The
small VXN file is present and its hash matches exactly.

This is consistent with -- and independently confirms -- what
`docs/OG_CONFIG_HISTORY.md` (from `docs/og-config-clean-baseline`, commit
`e304066`) already disclosed: a prior verification pass (`f99c8fdcc7b4925fc3622dc672bc4e8d033ebbb2`
on `verification/claude-baseline-v1`) found the file present in *that*
environment but with a **different** top-level SHA-256
(`9f427eb053b6c63e50f79baf666f239f851558d1558e706fc126cbe69f3a5af4`) than
the one recorded in `manifests/data_manifest.json`, despite matching row
count, span, contract count, and roll structure -- and that discrepancy was
never resolved to a byte-identical match, only characterized as "consistent
with a serialization artifact." In this environment the situation is
strictly worse: the file is not present at all, so even that inconclusive
byte-level comparison cannot be repeated.

Per the Stage-A instructions: **required canonical data is absent, and this
cannot be proven harmless without the file. Per instruction, I STOP here
rather than substitute any other data file.** No engine run was attempted.
No ledger was regenerated. No new performance number was produced.

**Final status: `STAGE_A_BLOCKED_DATA_MISMATCH`.**

## 3. What was still verified without running any engine

Because the canonical bars file is unavailable, engine execution and the
full adversarial dynamic invariant-test battery (causality/truncation test,
retry-after-consumed-touch test, forced-liquidation test, SAL-transition
test under mutated inputs) specified in the Stage-A instructions **could
not be performed** and are explicitly not claimed here.

What *was* independently verified, using only the pre-existing, already
git-committed artifacts at canonical commit `a375818` (i.e. re-deriving
numbers from raw ledger rows rather than trusting `baseline_summary.json`):

### 3.1 Config / engine / manifest hashes (this environment)

```
0ecd9f9f0f231e2aa508c31ea01f2aebe115e6c7132ee562d2e87c1bf5e1b9a4  configs/nq_current_config.yaml
9ffc0224310ef4904f012d946a56b0db94d777290b07fd5b3ee5d38fadf539f5  src/strict_engine.py
513b0a06ef6cd1249c8f9664134b044307eff3ac4a016531e4b8ca6643a758a0  src/independent_strict_engine.py
6e7edf10265c66f0dc41164ad8e1aec5dfa18ece1af663d307bb39365557df9c  src/level_generation.py
```
(Full manifest, including all output/ledger file hashes, in
`outputs/og_stage_a_hash_manifest.json`.)

### 3.2 Headline metrics recomputed directly from `outputs/baseline_executed.csv`

The trade ledger (1,107 data rows, 1,108 lines including header) was parsed
independently and metrics recomputed from scratch -- not copied from
`baseline_summary.json`:

| Metric | Recomputed from ledger | `baseline_summary.json` (pre-existing) | Match |
|---|---|---|---|
| Executed trades | 1107 | 1107 | exact |
| Net points | 6648.17 | 6648.17 | exact |
| Profit Factor | 1.2924 | 1.2924 | exact |
| Win rate | 0.3803 | 0.3803 | exact |
| Avg trade | 6.006 | 6.006 | exact |
| Avg winner | 69.800 | (not broken out) | n/a |
| Avg loser | -56.142 | (not broken out) | n/a |
| Max drawdown (equity-curve, trade-sequence order) | -1290.29 | -1290.29 | exact |
| TP / SL / BE / cutoff | 394 / 333 / 281 / 99 | 394 / 333 / 281 / 99 | exact |
| Negative years | 2019, 2023, 2024 | 2019, 2023, 2024 | exact |

Year-by-year net points recomputed from ledger (see
`outputs/og_stage_a_yearly_metrics.csv`):

| Year | n | Net pts |
|---|---|---|
| 2018 | 130 | 104.49 |
| 2019 | 122 | -240.86 |
| 2020 | 138 | 747.27 |
| 2021 | 130 | 718.39 |
| 2022 | 132 | 1792.16 |
| 2023 | 125 | -96.16 |
| 2024 | 121 | -176.62 |
| 2025 | 142 | 1055.95 |
| 2026 (partial) | 67 | 2743.56 |

This matches `outputs/baseline_yearly.csv` exactly (checked by year/n/net_pts).

### 3.3 Touch / skip reconciliation

From `outputs/baseline_skipped.csv` (3,486 rows = total physical touches),
recomputed independently:

| Category | Count |
|---|---|
| Total physical touches | 3486 |
| Executed | 1107 |
| Skipped: blocked_time | 968 |
| Skipped: no_cutoff | 458 |
| Skipped: SAL | 318 |
| Skipped: position_open | 315 |
| Skipped: no_anchor | 219 |
| Skipped: simultaneous_collision | 94 |
| Skipped: same_bar_reentry | 7 |
| Sum of skip reasons | 2379 |
| Executed + skipped | 3486 (matches total touches exactly) |

All values match `outputs/baseline_summary.json` exactly. Reconciliation is
saved at `outputs/og_stage_a_skip_reconciliation.json` and the full
per-touch row detail at `outputs/og_stage_a_touch_reconciliation.csv`
(copy of `outputs/baseline_skipped.csv`).

### 3.4 Two-engine agreement (pre-existing artifact, re-checked, not regenerated)

`outputs/engine_comparison.json` (already committed at the canonical commit)
reports `strict_engine.py` (`outputs/baseline_executed.csv`) and
`independent_strict_engine.py` (`outputs/independent_executed.csv`) agree on
all 1,107 trades exactly: `only_in_reference: 0`, `only_in_comparison: 0`,
`same_entry_diff_exit: 0`, `same_entry_exit_diff_pnl: 0`,
`fully_reproduced: true`. This was **not regenerated** in this session
(cannot be, without the bars file) -- it is reported as a pre-existing,
already-committed artifact only, and is explicitly labeled as such
everywhere it's cited.

### 3.5 No-overlap / no-same-minute-reentry invariant (checked against the existing ledger)

Sorting `outputs/baseline_executed.csv` by `entry_time` and checking each
trade's `entry_time` against the running-maximum prior `exit_time`:

- **Overlap violations found: 0**
- **Same-minute re-entry violations found: 0**

This is a **necessary but not sufficient** check -- it confirms the
*already-produced* ledger has no overlap, but (absent the bars file) it does
not independently prove the engine *itself* would refuse overlap on
arbitrary new data; that would require the causality/mutation adversarial
tests, which are blocked (see section 4).

### 3.6 TP/SL ambiguity and tie-order rule (static code inspection only)

Read directly from `src/strict_engine.py::simulate_from_touch` (lines
~196-234):
- The touch bar itself is **stop-only**: `hit_stop = (l0 <= orig_stop)`
  (long) / `(h0 >= orig_stop)` (short) is checked first; a touch-bar target
  hit is never assumed a win (a target hit on the touch bar itself is not
  even evaluated) -- i.e. the conservative rule for the touch bar is "assume
  the adverse outcome is possible, never assume the favorable one."
- On every subsequent bar, stop is checked **before** target in the same
  bar: `if l <= stop: return ... elif h >= target: return ...` (long case;
  mirrored for short) -- i.e. when a single bar's OHLC cannot disambiguate
  which was touched first, the engine conservatively resolves in favor of
  the stop/BE outcome, never the target.
- `run_strict(..., tie_order="age")` docstring: "tie_order breaks
  simultaneous-touch ties; the frozen primary config uses 'age' (oldest
  level first)" -- confirms canonical simultaneous-touch handling is
  oldest-level-first.

This is a **static/code-level** confirmation only; it is not a dynamic test
that exercises a constructed ambiguous bar, because that would require
running the engine.

## 4. Adversarial invariant tests -- status: BLOCKED (not fabricated)

The instructions require dynamic tests proving (among others): causality
under data truncation, no-retry-after-consumed-touch, forced-liquidation
bound, and SAL-transition correctness under mutated inputs. **All of these
require executing `strict_engine.py`/`independent_strict_engine.py` against
bars data**, which is unavailable in this environment. They are not
performed. `tests/test_og_stage_a_invariants.py` (committed on this branch)
contains only the ledger-level static checks described in sections 3.5-3.6
plus a guard test (`test_data_file_absent_documented`) that will start
failing (by design) the moment the canonical bars file becomes available,
as a signal that Stage A should be re-run in full with the dynamic battery.

```
$ python3 -m pytest tests/test_og_stage_a_invariants.py -v
8 passed
```

## 5. Exact rerun reproducibility

Not tested. Re-running `strict_engine.py`/`independent_strict_engine.py`
twice to diff ledgers byte-for-byte requires the bars file. The only
"rerun" performed in this session was rerunning the independent metric
recomputation script against the same, static, pre-existing
`outputs/baseline_executed.csv` -- which is trivially deterministic (pure
CSV parsing/arithmetic) and was confirmed to produce identical output on
repeat invocation, but this does not exercise engine determinism.

## 6. Reproduction commands (verbatim, from `docs/OG_CONFIG_HISTORY.md` / README, NOT executed in this session because of section 2)

```
pip install -r requirements.txt
python3 scripts/build_or_verify_data.py --bars data/nq_1m/nq_continuous_2018_2026_1m.csv --vxn data/vxn_daily_2018_2026.csv
python3 -m src.strict_engine --bars data/nq_1m/nq_continuous_2018_2026_1m.csv --vxn data/vxn_daily_2018_2026.csv --out-dir outputs
python3 -m src.independent_strict_engine --bars data/nq_1m/nq_continuous_2018_2026_1m.csv --vxn data/vxn_daily_2018_2026.csv --out-dir outputs
python3 scripts/compare_engines.py --reference outputs/baseline_executed.csv --comparison outputs/independent_executed.csv
python3 -m pytest tests/ -v
```

To unblock Stage A: place the canonical file at
`data/nq_1m/nq_continuous_2018_2026_1m.csv`, verify `sha256sum` equals
`3d0228fcc17a40933d4fdc3983a8153e5bb6445ed9e743919b3eb5c516e53880` via
`scripts/build_or_verify_data.py`, then re-run this Stage A procedure in
full, including the dynamic adversarial invariant battery.

## 7. Final status

**`STAGE_A_BLOCKED_DATA_MISMATCH`**

Reason: the canonical required input `data/nq_1m/nq_continuous_2018_2026_1m.csv`
is absent from every branch of this repository and from this execution
environment; no substitute data was used. All checks that could be
performed without executing the engine (ledger-internal reconciliation of
the pre-existing canonical-commit artifacts, hash verification of config/
engine/VXN files, static code inspection of TP/SL and tie-order rules, and
no-overlap/no-same-minute-reentry checks on the existing ledger) were
performed and passed with exact matches; they are reported as such and not
conflated with full independent reproduction, which remains blocked.
