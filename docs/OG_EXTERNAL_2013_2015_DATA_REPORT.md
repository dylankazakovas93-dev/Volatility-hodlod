# OG External 2013-2015 Data Report

Phase label: `POST_VALIDATION_EXTERNAL_DIAGNOSTIC_2013_2015`

This report covers **data handling only** (Step 1 + Step 2 of the task). It
contains **no strategy outcome, no trade, no P&L figure of any kind**. The
locked validation result in `docs/OG_VALIDATION_RESULTS_DUAL_CONFIG.md`
(commit `add8f30`, verdict `DUAL_CONFIG_FAIL`) is not touched, modified, or
reinterpreted anywhere in this document.

## 1. Raw file identity

Source: user-supplied Databento batch job `GLBX-20260704-8PDJP3C4A9`,
uploaded to `/root/.claude/uploads/856d6357-1058-5b2f-a03e-440fb0f499a2/`
with filenames mangled by the upload transport (punctuation stripped). The
job manifest (`10e3663a-manifest.json`, copied verbatim into
`data/external_2013_2015/raw/manifest.json`) records the true Databento
filename as `glbx-mdp3-20130101-20151231.ohlcv-1m.csv.zst`. This report's
files were renamed back to that true filename on copy-in (the upload folder
itself was left untouched) so provenance is legible and matches the
`condition.json`/`metadata.json`/`manifest.json` filenames they describe.

| file | bytes | sha256 |
|---|---|---|
| `data/external_2013_2015/raw/glbx-mdp3-20130101-20151231.ohlcv-1m.csv.zst` (compressed raw, as delivered) | 14,169,004 | `d5754b1abf47b11d3bbd12a56024152f53648fb1a466319a9e74e0b40cd0013d` |

**Verification: the uploaded file's sha256 was computed directly
(`sha256sum`) and matches the manifest's recorded hash for
`glbx-mdp3-20130101-20151231.ohlcv-1m.csv.zst`
(`d5754b1abf47b11d3bbd12a56024152f53648fb1a466319a9e74e0b40cd0013d`) exactly.**
Proceeding with this data is justified by this match.

Supporting provenance files copied in verbatim (unchanged content):
`condition.json` (112,673 bytes), `manifest.json` (1,474 bytes),
`metadata.json` (685 bytes). `metadata.json` confirms the query:
`{"dataset": "GLBX.MDP3", "schema": "ohlcv-1m", "symbols": ["NQ.FUT"],
"stype_in": "parent", "stype_out": "instrument_id"}`, date range
2013-01-01T00:00:00Z (1356998400000000000 ns) to
2015-12-31T00:00:00Z (1451606400000000000 ns) — the identical query shape
used for the existing 2018-2026 canonical archive.

## 2. Decompression

Decompressed with Python's `zstandard` library
(`ZstdDecompressor().copy_stream(...)`), the same approach used for the
existing canonical 2018-2026 archives.

| file | rows (incl. header) | bytes | sha256 |
|---|---|---|---|
| `data/external_2013_2015/raw/glbx-mdp3-20130101-20151231.ohlcv-1m.csv` | 1,130,107 (1,130,106 data rows) | 124,115,940 | `3b2063a91b42b116bcdf0e433cdd58dc1707c25f77aed81c8bbe967b8b1a251d` |

## 3. Raw schema check

Columns found: `ts_event, rtype, publisher_id, instrument_id, open, high,
low, close, volume, symbol` — this is an **exact match** to the documented
raw format in `docs/DATA_PIPELINE.md` and to the format `scripts/build_nq_continuous.py`
expects. No column differences. dtypes: `ts_event`/`symbol` are strings,
`rtype`/`publisher_id`/`instrument_id`/`volume` are int64, `open`/`high`/`low`/`close`
are float64 — consistent with the existing pipeline's raw ingestion.

## 4. Canonical continuous series build

Built with the **unmodified** `scripts/build_nq_continuous.py` (no new roll
logic written), applying its documented rule: for each UTC calendar day,
keep only the standard quarterly contract (regex `^NQ[HMUZ]\d$`, excluding
calendar-spread symbols) with the highest total traded volume that day.

Command:
```
python3 scripts/build_nq_continuous.py \
    --raw data/external_2013_2015/raw/glbx-mdp3-20130101-20151231.ohlcv-1m.csv \
    --out data/external_2013_2015/normalized/nq_continuous_2013_2015_1m.csv
```

Output: 953,805 rows, span `2013-01-02 11:00:00+00:00` -> `2015-12-31
21:59:00+00:00`, 13 distinct standard contracts used, 12 roll days.

| file | bytes | sha256 |
|---|---|---|
| `data/external_2013_2015/normalized/nq_continuous_2013_2015_1m.csv` | 63,067,050 | `026aab199422298cfac7d03b1c58e883b74598d3bd0c66cb52cf6b3d2f5ce4da` |

Roll dates found (contract becomes the day's volume winner):

| roll date (UTC) | new contract |
|---|---|
| 2013-03-08 | NQM3 |
| 2013-06-14 | NQU3 |
| 2013-09-13 | NQZ3 |
| 2013-12-13 | NQH4 |
| 2014-03-14 | NQM4 |
| 2014-06-15 | NQU4 |
| 2014-09-12 | NQZ4 |
| 2014-12-12 | NQH5 |
| 2015-03-13 | NQM5 |
| 2015-06-12 | NQU5 |
| 2015-09-11 | NQZ5 |
| 2015-12-11 | NQH6 |

This is the identical roll methodology (highest-volume-standard-contract-
per-day, ~quarterly cadence, ~7-10 trading days before expiry) as documented
for the 2018-2026 canonical file — same script, same rule, no changes.

## 5. Timestamp / timezone convention

`ts_event` in the raw file is UTC (per Databento convention and the `Z`
suffix on every timestamp, e.g. `2013-01-02T11:00:00.000000000Z`). The
build script converts with `pd.to_datetime(..., utc=True)` — identical to
the existing pipeline. Downstream ET conversion (for RTH/session-window
logic) is performed by the existing, unmodified `src/data_loader.py` /
`src/strict_engine.py` — no new timezone logic was written for this task.

## 6. Chronological integrity

Verified programmatically on the normalized file:
- Duplicate timestamps: **0**
- Monotonically increasing timestamp index: **True** (strict)
- Row count: 953,805 (matches the build script's own reported count)

## 7. OHLC consistency

Verified programmatically: **0** rows where `high < max(open,close,low)` or
`low > min(open,close,high)`. **0** non-positive prices across
open/high/low/close. All prices are in the plausible NQ range for
2013-2015 (roughly 2600-4700).

## 8. Session coverage / gap analysis

920 distinct UTC trading dates in the normalized file, spanning
2013-01-02 to 2015-12-31. Comparing to the full business-day calendar
(`pd.bdate_range`) for that span finds **11 missing weekdays**:

| missing date | weekday | classification |
|---|---|---|
| 2013-03-29 | Friday | Good Friday (CME NQ closed) — expected |
| 2013-12-25 | Wednesday | Christmas — expected |
| 2014-01-01 | Wednesday | New Year's Day — expected |
| 2014-04-18 | Friday | Good Friday — expected |
| 2014-06-12 | Thursday | **unexplained — no rows anywhere in the raw archive** |
| 2014-06-13 | Friday | **unexplained — no rows anywhere in the raw archive** |
| 2014-09-23 | Tuesday | **unexplained — no rows anywhere in the raw archive** |
| 2014-09-24 | Wednesday | **unexplained — no rows anywhere in the raw archive** |
| 2014-09-25 | Thursday | **unexplained — no rows anywhere in the raw archive** |
| 2014-12-31 | Wednesday | **unexplained — no rows anywhere in the raw archive** |
| 2015-12-25 | Friday | Christmas — expected |

5 of the 11 gaps match the known CME/NASDAQ 2013-2015 holiday calendar
(Good Friday 2013 and 2014, Christmas 2013 and 2015, New Year's Day 2014)
and are plausible, expected closures. **The other 6 weekdays
(2014-06-12, 2014-06-13, 2014-09-23, 2014-09-24, 2014-09-25, 2014-12-31)
have zero rows across every symbol in the raw archive** (confirmed by
querying the raw CSV directly, not just the standard-contract-filtered
normalized file) — NQ futures traded normally on those real-world dates,
so this is a genuine gap in the supplied Databento batch job, not a market
closure and not an artifact of the roll-selection logic. This is reported
as-is; the raw file was not repaired or backfilled. Any consumer of the
normalized series should treat these 6 dates as absent data, not as
zero-volume days.

No other calendar-plausibility issues were found; weekly Sunday-evening
partial sessions (CME's ~18:00 ET reopen) appear as low-row-count Sunday
dates, which is expected and consistent with the existing pipeline's
session structure.

## 9. Roll convention confirmation

Confirmed: `scripts/build_nq_continuous.py` was run unmodified, with no
new arguments or logic. The roll rule (highest-volume standard contract
per UTC calendar day) is identical to the rule already verified
byte-for-byte for the 2018-2026 canonical file.

## 10. Hash summary

| file | bytes | sha256 |
|---|---|---|
| raw `.csv.zst` (as delivered) | 14,169,004 | `d5754b1abf47b11d3bbd12a56024152f53648fb1a466319a9e74e0b40cd0013d` |
| raw decompressed `.csv` | 124,115,940 | `3b2063a91b42b116bcdf0e433cdd58dc1707c25f77aed81c8bbe967b8b1a251d` |
| normalized continuous `.csv` | 63,067,050 | `026aab199422298cfac7d03b1c58e883b74598d3bd0c66cb52cf6b3d2f5ce4da` |

Per `.gitignore`, the decompressed raw `.csv` and the normalized `.csv`
are **excluded from git** (matching this repo's existing convention for
its main NQ bars data, `data/nq_1m/`, which is likewise gitignored and
tracked only by hash/manifest). The compressed `.csv.zst` (14MB, the
authoritative Databento-delivered artifact) and the three small JSON
provenance files ARE committed directly, since they are small and are the
byte-identical source of truth from which the excluded derivatives can be
regenerated deterministically via the two commands in this report.

## Step 2 — Warmup / eligibility determination (CRITICAL FINDING)

The task brief's working assumption was that `OG_PRIMARY_150R.yaml` /
`OG_OPERATIONAL_100R.yaml` "do not use VXN at all" since neither the SAL
gate nor the Stage D/HMM-VXN filter is enabled in either config
(`hmm_gate.enabled: false`, `sal_enabled: false`). That assumption is
**checked here and found to be incorrect** in one specific, structural
way:

- Both frozen configs declare `data.vxn_file:
  data/vxn_daily_2018_2026.csv` and `data.vxn_sha256`.
- `src/strict_engine.py::build_eligible_candidates` and
  `src/level_generation.py::generate_levels` take a **mandatory** daily
  volatility-close series (`vol_close`, historically "VXN" for NQ) and use
  it, unconditionally, in the core level-placement formula for *every*
  session: `sigma_day = cash_open * (vix_close / 100) / sqrt(252)`, which
  directly feeds `imp_up`/`imp_dn` and therefore `upper_level`/
  `lower_level`. This is **not** the optional Stage D/HMM regime filter
  and **not** the SAL add-on — it is the base sigma-band math the whole OG
  indicator is built on. There is no code path in `generate_levels` that
  skips this input.
- `generate_levels` calls `prior_session_close(vol_close, session_date)`
  per session and **returns `None` (skips the session entirely, no level
  created) whenever no prior-day volatility close exists**.
- The repository's only volatility-close file, `data/vxn_daily_2018_2026.csv`,
  spans **2017-12-01 to 2026-06-08** (confirmed by reading its first/last
  rows directly). It has **zero coverage for 2013-2015**.
- No 2013-2015 VXN (or substitute daily volatility close) file was among
  the four files supplied in
  `/root/.claude/uploads/856d6357-1058-5b2f-a03e-440fb0f499a2/`.

**Consequence:** with the data actually supplied, `generate_levels` would
skip every single session in 2013-2015 — there is no date in the
2013-2015 window for which the warmup/eligibility requirement is
genuinely satisfiable from currently-available data. This is not a
partial-eligibility problem solvable by excluding a few early warmup
sessions (as the LINE_DAYS=20 level-lifetime mechanic or a 1-hour IB
anchor would be); it is a total absence of a required, mandatory,
config-declared input for the entire requested window.

The task instructions are explicit that this diagnostic must not:
(a) fabricate or backfill any data ("no fabricated pre-2013 history, no
backfilled levels, no synthetic prior sessions"), or
(b) source any additional data beyond what was supplied
("Do not source any additional data beyond what's already supplied").

Both of the only two ways to close this gap are therefore explicitly
out of scope for this task as specified. **No first eligible trading date
can be honestly reported, because no eligible trading date exists under
the current data + no-fabrication + no-new-sourcing constraints.**

This is reported transparently rather than worked around. See the top-level
final report for how this affects Steps 3-7.
