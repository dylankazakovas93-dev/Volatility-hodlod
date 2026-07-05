# NQ Strict Engine — Verified Handoff

## What this strategy is

An NQ (Nasdaq-100 E-mini futures) level-fade strategy. Each session, two
statistically-derived levels (upper/lower) are placed using implied daily
volatility (VXN) and the first-hour Initial Balance range. The first
physical touch of a level fades it: an upper-level touch shorts, a
lower-level touch longs. Exactly one NQ position may be open at a time,
across the whole book — a genuinely single-position, time-aware-SAL
engine, not an overlap-permitting one. Full rules: `docs/STRATEGY_RULES.md`.

## Which files are authoritative

- **Strategy rules:** `docs/STRATEGY_RULES.md`
- **Frozen parameters:** `configs/nq_current_config.yaml` (if this and any
  other document disagree, the YAML file wins)
- **Engine code:** `src/strict_engine.py` (primary),
  `src/independent_strict_engine.py` (independent cross-check —
  freshly-coded, does not call the primary engine's simulation code)
- **Verified result:** `outputs/baseline_summary.json`,
  `outputs/baseline_executed.csv`

## How the data was constructed

See `docs/DATA_PIPELINE.md` in full — read it before assuming anything
about the source data. Short version: the canonical NQ bars file
(`data/nq_1m/nq_continuous_2018_2026_1m.csv`, hash-verified, 2,964,655
rows) is **not** committed in this repo (211 MB, gitignored — see
`data/README.md` for how to obtain it). The VXN daily file **is**
committed. The exact raw-Databento-to-canonical construction procedure is
**partially unknown** — classification:
`CANONICAL_FILE_VERIFIED_BUT_RAW_CONSTRUCTION_PARTIALLY_UNKNOWN`. Every
result in this handoff is reproducible *from* the canonical file; the raw
multi-contract source data used to *build* that file is not available to
re-derive it from scratch.

## What the frozen config is

```
stop distance   = min(1.5 * previous completed 60-min range, 200 pts)
target distance = stop distance (1:1 RR)
conditional BE  = arms at bar 45 if the open is on the profit side
SAL             = enabled, time-aware, arms only at a qualifying loss's exit
entry window    = 19:00-11:00 ET, session cutoff 15:00 ET
```

Full parameter table: `docs/CURRENT_CONFIG.md`.

## How to reproduce it

```
pip install -r requirements.txt
python3 scripts/build_or_verify_data.py --bars data/nq_1m/nq_continuous_2018_2026_1m.csv --vxn data/vxn_daily_2018_2026.csv
python3 -m src.strict_engine --bars data/nq_1m/nq_continuous_2018_2026_1m.csv --vxn data/vxn_daily_2018_2026.csv --out-dir outputs
python3 -m src.independent_strict_engine --bars data/nq_1m/nq_continuous_2018_2026_1m.csv --vxn data/vxn_daily_2018_2026.csv --out-dir outputs
python3 scripts/compare_engines.py --reference outputs/baseline_executed.csv --comparison outputs/independent_executed.csv
python3 -m pytest tests/ -v
```

Or all at once: `python3 scripts/verify_handoff.py --bars ... --vxn ...`.
Full details, including what "fresh clone" was actually tested: `docs/REPRODUCIBILITY.md`.

## Exact result to expect

```
eligible candidates = 1,841
executed trades     = 1,107
net                 = +6,648.17 NQ points
PF                  = 1.2924
average trade       = +6.006 points
max drawdown        = -1,290.29 points
TP / SL / BE / cutoff = 394 / 333 / 281 / 99
negative years      = 2019, 2023, 2024
```

Two independently-written engines reproduce all 1,107 trade rows exactly
(`outputs/engine_comparison.json`, `matched: 1107`, zero divergence in
every other category).

## What is not authorized yet

**No grid search or parameter optimization has been authorized. The next
stage will be designed by the user after independent baseline
verification.** Do not run, propose, or infer a configuration sweep, a
walk-forward study, a master holdout, a bootstrap, or any ES (E-mini S&P)
work from anything in this repository. See `docs/KNOWN_LIMITATIONS.md` for
the full list of what has and hasn't been done.
