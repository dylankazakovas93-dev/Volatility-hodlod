# Reproducibility — Fresh Environment

Follow this exactly. It assumes no prior conversation context — a fresh
Claude or Codex session should be able to execute every step below without
anything except this file.

## 1. Supported Python version

Python 3.11 (tested). Python 3.10+ should work; nothing here uses
3.11-specific syntax.

## 2. Dependencies

```
pip install -r requirements.txt
```

Installs: `pandas`, `numpy`, `PyYAML`, `pytest`.

## 3. Environment setup

```
git clone <this repository/branch>
cd <repo>
```

No environment variables, API keys, or network access are required to run
the engine once the data files are in place.

## 4. Data location

- `data/vxn_daily_2018_2026.csv` — committed directly in this repo.
- `data/nq_1m/nq_continuous_2018_2026_1m.csv` — **not** committed (211 MB,
  gitignored). You must place this file yourself. See `data/README.md` for
  exactly what is and isn't known about how to obtain it, and why a
  portable retrieval script isn't included.

No Git LFS is used. If you cannot obtain the raw NQ file, you cannot run
the engine, full stop — there is no synthetic substitute.

## 5. Hash verification (run this first, always)

```
python3 scripts/build_or_verify_data.py \
    --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
    --vxn  data/vxn_daily_2018_2026.csv
```

Expected: `DATA VERIFICATION: PASS`. If this fails, stop — nothing
downstream is trustworthy.

## 6. Primary engine

```
python3 -m src.strict_engine \
    --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
    --vxn  data/vxn_daily_2018_2026.csv \
    --out-dir outputs
```

Expected: gate prints `1841` (exits nonzero and stops if not), then
`executed: 1107`, `net_pts: 6648.17`, `PF: 1.2924`,
`TP/SL/BE/cutoff: 394/333/281/99`, negative years `[2019, 2023, 2024]`.
Runtime: ~20-30 seconds.

## 7. Independent engine

```
python3 -m src.independent_strict_engine \
    --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
    --vxn  data/vxn_daily_2018_2026.csv \
    --out-dir outputs
```

Expected: identical headline numbers to step 6. Runtime: ~10-15 seconds.

## 8. Row-by-row comparison

```
python3 scripts/compare_engines.py \
    --reference outputs/baseline_executed.csv \
    --comparison outputs/independent_executed.csv
```

Expected: `matched: 1107`, every other category `0`, `FULLY REPRODUCED: True`.

## 9. Test suite

```
python3 -m pytest tests/ -v
```

Expected: 36 tests, all passing.

## 10. One-command version of steps 5-9

```
python3 scripts/verify_handoff.py \
    --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
    --vxn  data/vxn_daily_2018_2026.csv
```

Exits nonzero and prints exactly which step failed if anything doesn't
reproduce.

## Fresh-clone test performed for this handoff

A fresh working directory was built from scratch in this environment (not
by copying an existing checkout) and steps 5-9 were run against it end to
end. Results:

1. **Access the required data:** the VXN file was restored from the
   research branch and hash-verified; the NQ bars file already existed
   locally at the expected path in this sandbox and was hash-verified —
   this step was not tested against a genuinely network-fresh clone with
   zero local data, because no network retrieval path exists to test (see
   `data/README.md`).
2. **Verify hashes:** PASS — both files matched expected SHA-256 and row count.
3. **Run the primary engine:** PASS — executed=1107, net=+6648.17, PF=1.2924.
4. **Run the independent engine:** PASS — identical headline numbers.
5. **Match all 1,107 trades:** PASS — `compare_engines.py` reported
   1107/1107 matched, zero divergence in every category.
6. **Pass all tests:** PASS — 36/36 tests passed.

The one limitation on "fresh clone" here is honestly stated: this was
verified as a fresh **file tree** (all source files rebuilt/copied from the
verified research commit, not reused from a stale working directory), with
hash-verified data placed into it — not as a fresh **clone over a network
with no pre-existing data access**, since this sandbox has no path to fetch
the NQ file from anywhere except the local disk it was already sitting on.
