# Known Limitations

## Data provenance

See `docs/DATA_PIPELINE.md` in full. Summary: the canonical NQ file is
hash-verified and every strategy result is reproducible from it, but the
exact raw-Databento-to-canonical construction procedure (roll-selection
algorithm, raw filenames, exact schema) is **not fully recoverable** from
what is available in this handoff. Classification:
`CANONICAL_FILE_VERIFIED_BUT_RAW_CONSTRUCTION_PARTIALLY_UNKNOWN`.

## VXN source

The VXN daily file's exact retrieval method is undocumented. The file is
hash-verified and internally consistent (used strictly-prior-only, no
lookahead — see `test_vxn_input_uses_only_prior_data`), but its original
fetch pipeline is unknown.

## Master/older-data holdout

No pre-2018 data (e.g. a 2013-2017 holdout period) exists anywhere in this
handoff or the research repository it was extracted from. This has not been
run and is not claimed to have been run.

## Grid search / optimization

**No configuration grid, walk-forward study, parameter optimization, or
alternate configuration has been authorized or performed.** The frozen
config in `configs/nq_current_config.yaml` is the only configuration this
handoff verifies. A previously-proposed 384-configuration preregistered
search was explicitly withdrawn by the user and must not be inferred as
implicitly approved by anything in this handoff.

## ES (E-mini S&P) companion strategy

Not addressed anywhere in this handoff. No ES-specific engine, data, or
research is included.

## Bootstrap / uncertainty quantification

Not performed in this handoff. The frozen result is a single historical
replay (2018-2026), not a resampled or simulated distribution. Any claim
about "probability of a losing year" or percentile drawdown would require
a separate, explicitly-authorized study.

## Two engines, one shared level-generation module

`src/strict_engine.py` and `src/independent_strict_engine.py` are
independently coded for touch detection, session/window logic, the
position/SAL state machine, conditional BE, and fill policy. Both share
`src/data_loader.py` and `src/level_generation.py` (data prep and the
level-placement formula) — this is a deliberate, documented choice (level
generation is not one of the frozen execution mechanics under test), not
an oversight. If you want a fully independent check including level
generation itself, that would require porting the Pine indicator a second
time from `indicator/mu_k_sigma.pine` in the research repository (not
included in this handoff).
