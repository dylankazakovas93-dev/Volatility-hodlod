# NQ Strict Engine -- Independent Baseline Verification (Claude)

Verification branch: `verification/claude-baseline-v1`
Checked-out handoff commit (confirmed via `git rev-parse HEAD` before any
work began): `a375818056ca435df021d60b111f5f58b1f3551f`

Scope: baseline verification only. No grid search, no parameter
optimization, no walk-forward/bootstrap/Monte Carlo, no ES work, no attempt
to improve the result. Nothing in `configs/nq_current_config.yaml` or the
frozen strategy mechanics was modified.

## 1. Handoff inspection

Read in full: README.md, docs/DATA_PIPELINE.md, docs/STRATEGY_RULES.md,
docs/ENGINE_ARCHITECTURE.md, docs/CURRENT_CONFIG.md, docs/REPRODUCIBILITY.md,
docs/KNOWN_LIMITATIONS.md, configs/nq_current_config.yaml. Inspected the code
(not just trusted the docs): scripts/build_nq_continuous.py,
src/strict_engine.py, src/independent_strict_engine.py,
src/level_generation.py, src/data_loader.py, src/metrics.py, all three test
files, scripts/build_or_verify_data.py, scripts/compare_engines.py,
scripts/verify_handoff.py. Code matches every documented rule (level
formula, touch semantics, entry window, anchor/stop/target, conditional BE
at bar 45, SAL activation/reset, touch-bar stop-first, gap-through fill,
simultaneous-touch oldest-level-first ordering). Config values
(`sigma_mult=1.25`, `fixed_offset=15.75`, `ib_minutes=60`, `LINE_DAYS=20`,
`SL_CAP=200`, `BE_BARS=45`) match the hardcoded engine constants exactly.

## 2. VXN file

SHA-256 of `data/vxn_daily_2018_2026.csv`: `76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e`
-- **matches** the frozen hash exactly. 2,139 data rows + header.

## 3. Raw Databento archives

See `raw_archive_report.md` in this directory for full detail. Summary: all
5 `.zst` archives' compressed-file hashes match their own `manifest.json`
exactly; all 5 `metadata.json` query specs match the documented
`GLBX.MDP3`/`ohlcv-1m`/`NQ.FUT`/`parent` query exactly; raw CSV schema
matches; standard quarterly outrights and calendar-spread symbols both
present in every archive as expected.

## 4. Independent roll-rule audit

A from-scratch, independently-coded (plain Python, no pandas, no reuse of
`scripts/build_nq_continuous.py`) reimplementation of "highest
standard-contract volume per UTC day" reproduces **34 distinct contracts,
33 roll days**, zero same-day volume ties anywhere in 2018-2026. See
`independent_daily_contract_selection.csv`.

## 5. Rebuilt canonical file vs. frozen hash -- MISMATCH, then diagnosed

Ran the committed `scripts/build_nq_continuous.py` against the 5
decompressed raw files:

```
rows: 2,964,655                          (expected 2,964,655 -- MATCH)
span: 2018-01-01T23:00:00Z -> 2026-06-07T23:59:00Z   (MATCH)
contracts used: 34, roll days: 33        (MATCH)
SHA-256: 9f427eb053b6c63e50f79baf666f239f851558d1558e706fc126cbe69f3a5af4
expected: 3d0228fcc17a40933d4fdc3983a8153e5bb6445ed9e743919b3eb5c516e53880
```

**`DATA VERIFICATION: FAIL`** for the bars file (VXN still passes). Per
instructions, the official chain was not treated as passed on this basis.
The remainder of this section is the authorized **diagnostic-only**
investigation into why.

### 5a. Byte-level characterization of the rebuilt file (canonical file itself
was never available in this environment -- see "Known limitation" below)

- Size: 205,826,945 bytes; 2,964,655 data rows + 1 header row
- `file(1)`: CSV ASCII text; no CRLF (`grep -c $'\r'` = 0); no UTF-8 BOM;
  trailing byte is a single `\n`; zero quote characters anywhere
- Header: `timestamp,open,high,low,close,volume,contract,roll_day` --
  matches `manifests/data_manifest.json`'s `columns` field exactly
- Timestamp format: `2018-01-01 23:00:00+00:00` (space separator, `+00:00`
  offset) -- matches the format already used in
  `manifests/raw_file_inventory.csv`'s own timestamp columns
- `volume` column: `int64` (no `.0` suffix); confirmed 0 rows have any
  sub-minute (non-`.000000000Z`) raw `ts_event` component across all 5 raw
  files, so no fractional-second formatting ambiguity is possible
- Rebuild is **deterministic**: re-ran the exact same command twice,
  identical hash both times

### 5b. Pandas/Python version test

This environment's toolchain: pandas 3.0.3, numpy 2.4.6, Python 3.11.15.
Built a second isolated venv with **pandas 2.2.3 / numpy<2** (the version
family the repo's `requirements.txt` (`pandas>=2.0`) and docs' "tested on
Python 3.11" most plausibly describe) and reran the identical build command.
Result: **byte-for-byte identical** to the pandas 3.0.3 build (`cmp`
reported no differences; both hash to `9f427eb0...`). This **rules out** a
pandas-major-version CSV float-serialization difference as the cause.

### 5c. Ruled out as causes (checked explicitly, not assumed)

- Duplicate timestamps within any winning-contract segment: **0** (so
  `drop_duplicates` never triggers, in either build)
- Symbols resolving to more than one `instrument_id` (a remap collision):
  **0**
- Same-day volume ties between two standard contracts: **0**
- Non-zero sub-second raw timestamps: **0**
- `build_nq_continuous.py` has a single-commit history in this branch (never
  modified after the frozen hash was recorded)

### 5d. Per-segment semantic cross-check against `manifests/raw_file_inventory.csv`

The handoff's own manifest records each of the 34 contract segments'
row-count and first/last timestamp. Recomputing this table from my rebuilt
file and diffing against the manifest: **all 34 rows match exactly** --
same contract, same row count, same first timestamp, same last timestamp,
for every single segment, covering all 2,964,655 rows. (Table saved as
`independent_daily_contract_selection.csv`/segment check in this report's
companion outputs.)

### 5e. Normalized content fingerprint

Wrote `scripts/normalized_content_hash.py` (committed as verification-only
code): parses each row's timestamp as a UTC instant and each OHLC value as a
`Decimal` (not a binary float), serializes to an explicit
`ts|open|high|low|close|volume|contract|roll_day` line, and streams a single
SHA-256 over all 2,964,655 normalized rows -- independent of any CSV
float-formatting convention.

```
rows normalized : 2,964,655
normalized sha256: 7a5cc648499c4d9d759f6767fb2f4a6c207778df33304de6b3226d8ad4329182
```

**Known limitation:** the canonical 211 MB bars file is gitignored and was
never present anywhere in this session's environment (confirmed by
filesystem search) -- only its SHA-256 is recorded in the handoff. This
means the normalized hash **cannot be directly compared** against the
canonical file's normalized hash; there is nothing to diff it against. This
report cannot claim item 1/2's literal byte/field-level comparison for that
reason -- it is reported here as a limitation, not glossed over.

### 5f. Decisive downstream diagnostic: run the engines

Since a direct byte/field diff against the canonical file is impossible in
this environment, the strongest available evidence is whether my rebuilt
file, run through the frozen engines, reproduces the already-committed
`outputs/` ledgers (which were presumably produced from the true canonical
file). Both engines were run against my rebuilt bars file:

**Primary engine** (`src.strict_engine`): eligible=1841, executed=1107,
net=+6648.17, PF=1.2924, TP/SL/BE/cutoff=394/333/281/99, negative
years=[2019,2023,2024] -- **exact match** to every frozen headline number,
including every granular skip-reason count.

**Independent engine** (`src.independent_strict_engine`): executed=1107,
net=+6648.17, PF=1.2924, TP/SL/BE/cutoff=394/333/281/99, negative
years=[2019,2023,2024] -- **exact match**.

**Byte-level output check**: `outputs/baseline_executed.csv` (already
committed in the handoff) vs. my freshly-generated
`verification_outputs/primary/baseline_executed.csv`:

```
$ cmp verification_outputs/primary/baseline_executed.csv outputs/baseline_executed.csv
(no output -- byte identical)
```

And every other committed output file's SHA-256 matches the freshly
generated one exactly (`baseline_executed.csv`, `baseline_skipped.csv`,
`baseline_yearly.csv`, `baseline_eligible_1841.csv`,
`baseline_physical_touches.csv` -- all identical to
`manifests/output_manifest.json`). Only `baseline_summary.json` differs,
and only in the two fields that are supposed to differ across runs/commits
(`code_commit`, `data_hashes.bars`, `reproduction_command`) -- the `result`
block is identical.

### 5g. Interpretation

Per the interpretation rules: byte SHA differs, but every available
normalized/structural cross-check (segment table, row counts, all 5
downstream ledgers byte-identical to the committed baseline, both engines'
full headline numbers and all 1,107 trades reproduced exactly) indicates
the actual data content is identical. Status for this section:

**`SEMANTIC_DATA_AND_ENGINE_MATCH_BYTE_SERIALIZATION_UNRESOLVED`**

I did not achieve exact byte reproduction of the frozen
`3d0228fc...` hash, and could not identify a specific serialization
difference (pandas version, numpy version, line ending, quoting, and BOM
were all checked and ruled out). Given the canonical file itself was never
available to diff against in this session, I cannot rule out that the
`3d0228fc...` hash in the manifests was itself recorded from a build that
predates or differs from the exact committed `build_nq_continuous.py` in
some way not discoverable from this repository alone. This is reported
as an open item, not resolved.

## 6. Config audit

`configs/nq_current_config.yaml` values cross-checked directly against
`NQ_PARAMS` / `LINE_DAYS` / `SL_CAP` / `BE_BARS` in the engine source (not
just the docs): all match. No hidden, unexplained hardcoded constant found
outside the config file.

## 7. Test suite

`python3 -m pytest tests/ -v`: **35 passed, 1 failed**
(full output: `test_results.txt`). The one failure is
`test_data.py::test_canonical_bars_hash`, which fails for the exact same
reason as section 5 (the rebuilt bars SHA-256 doesn't match the frozen
value) -- not a different or new problem. The test was **not** modified,
weakened, or skipped.

## 8. Target-chasing / hidden-dependency audit

Grepped `src/` and `scripts/` for the frozen headline numbers
(1107/6648/1.2924/1841): the only occurrences are in
`build_eligible_candidates`'s **fail-fast sanity gate**
(`if len(eligible) != 1841: sys.exit(1)`), which stops the run rather than
adjusting it -- it does not filter, retry, or otherwise steer the
simulation toward a target. No other reliance on expected results, future
trade outcomes, retroactive SAL, position overlap, re-enterable skipped
touches, cutoff-exclusion from PF, or undocumented local-path dependencies
was found in either engine. Both engines compute everything from `--bars`
and `--vxn` arguments only.

## 9. Final status

**`SEMANTIC_DATA_AND_ENGINE_MATCH_BYTE_SERIALIZATION_UNRESOLVED`**

- Raw archives: verified exactly as claimed (hashes, query params, schema).
- Roll-selection rule: independently re-derived and matches exactly.
- Canonical bars file: **byte-hash does not reproduce** (`DATA
  VERIFICATION: FAIL`); diagnosed at length; every available semantic
  cross-check (segment table, downstream ledger byte-identity, full
  headline and row-level engine reproduction) indicates the content is
  identical; root cause of the byte-hash difference itself remains
  unresolved.
- Primary engine: reproduces every frozen number exactly.
- Independent engine: reproduces every frozen number exactly, and matches
  the primary engine row-for-row (1,107/1,107, 0 divergence).
- Tests: 35/36 pass; the 1 failure is the same bars-hash issue, not a new
  defect.
- No target-chasing or hidden dependency found.

This is **not** `EXACT_MATCH` (the bars hash gate failed) and it is **not**
`MATERIAL_DISAGREEMENT` (nothing downstream actually disagrees). It sits
between `ENGINE_MATCH_DATA_NOT_REBUILT` and `EXACT_MATCH` in the given
taxonomy; reported verbatim per the diagnostic-phase interpretation rules
rather than forced into the pre-diagnostic category list.
