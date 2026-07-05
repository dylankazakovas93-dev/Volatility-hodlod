# Stage 0 -- All-Hours Signal-Path and MAE/MFE Study

Research branch: `research/claude-stage0-excursions`
Source handoff commit (unchanged data pipeline, level generation, touch
semantics): `a375818056ca435df021d60b111f5f58b1f3551f`
Data hashes: bars `9f427eb053b6c63e50f79baf666f239f851558d1558e706fc126cbe69f3a5af4`
(see `verification/claude-baseline-v1` for why this differs from the frozen
`3d0228fc...` hash by serialization only -- content-verified identical: same
row count/span/contracts/rolls, and both engines reproduce the frozen
ledger byte-for-byte from it), VXN `76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e`.

This is **rebuilt trade management from zero** on top of the **unchanged**
verified data pipeline, level-generation formula, and physical first-touch
semantics. No TP, SL, BE, SAL, or time-of-day entry filter from the frozen
strategy is inherited, reused as a seed, or used as a control in this study.

## 1. Physical-touch reconciliation (required first step)

Reused, unmodified: `src.level_generation.generate_levels`,
`src.strict_engine.physical_touches` (which itself has **no** time-of-day
restriction -- it never did; the old 19:00-11:00 entry window was applied
only downstream, during trade execution eligibility, never during touch
discovery).

```
verified baseline physical touches : 3,486
Stage 0 physical touches            : 3,486
reconciled                          : True
```

`outputs/stage0_physical_touches.csv` is **byte-for-byte identical** to the
already-committed `outputs/baseline_physical_touches.csv` (`diff` reports no
differences). There is no divergence to explain by category and no first
differing level side, because the two runs use identical code, identical
bars, identical VXN, and touch discovery was never gated by entry hour in
the first place. The population size is therefore **unchanged by design**,
exactly as anticipated -- widening the tradeable session changes which
touches get a *valid signal path*, not what counts as a physical first
touch.

## 2. All-hours research session definition

Session: **18:00 ET through 15:59 ET the following day.**

- `research_session_date(ts)`: a touch at ET local hour >= 18 belongs to the
  *following* calendar day's session (same rolling convention the verified
  engine used at its 19:00 boundary, just at 18:00).
- **Forced liquidation**: the session's own 15:59 ET bar. The 15:59 bar is
  processed normally for any already-open position, and represents the
  minute interval 15:59:00-15:59:59 ET (the raw bar's timestamp is its
  open); no bar exists that starts at 16:00:00 and is still "session time,"
  so "flat before 16:00 ET" is implemented by treating the 15:59 bar's
  *close* as the final tradable price -- one consistent convention, applied
  everywhere in this study.
- **No new position may enter on the 15:59 bar itself** -- a touch whose
  bar *is* the 15:59 bar has no room for a post-touch path and is excluded
  (`reason=liquidation_bar`, 17 of 3,486 touches).
- **The 16:00:00-17:59:59 ET gap is undefined, not silently assigned.** The
  literal session spec (18:00 -> 15:59 next day) leaves a ~2-hour window
  each day with no active session and therefore no defined forced-
  liquidation timestamp. Rather than guess which neighboring session a
  touch in that gap belongs to, touches inside it are excluded from the
  Stage 0 signal population (`reason=gap`, 137 of 3,486 touches) and
  reported separately, not silently folded into either session.
- A touch with **no bar after it** before its computed cutoff (i.e. an
  empty post-touch path -- effectively data-end truncation) is excluded
  (`reason=no_valid_path`, 1 of 3,486 touches, at the very end of the
  2018-2026 span).

Net: **3,486 physical touches -> 3,331 qualifying Stage 0 signals** (137
gap + 17 liquidation-bar + 1 no-valid-path = 155 excluded, reconciling
exactly: 3,331 + 155 = 3,486).

## 3. Two datasets

- **Dataset A -- independent signal paths**
  (`outputs/stage0_signal_paths.csv`, `scripts/build_signal_paths.py`): one
  row per qualifying touch, full 1-minute path recorded independently of
  any other signal's state. 3,331 rows.
- **Dataset B -- one-position cutoff-only control**
  (`outputs/stage0_control_executed.csv`,
  `scripts/run_stage0_control_replay.py`): chronological replay, one global
  position, no TP/SL/BE/SAL, exit only at forced liquidation; a touch is
  skipped (never retried) if a position is already open when it fires.
  1,393 executed / 3,486 physical touches (155 excluded exactly as above,
  1,938 further skipped because a position was open).

Dataset B is **not** a sum of Dataset A's independent paths -- it is a
genuine chronological replay, so which touches are consumed depends on how
long the *previous* position happened to stay open (confirmed by
`tests/test_stage0_control_replay.py::test_no_overlapping_positions` and
`test_chronological_order`).

## 4. Causal pre-entry features

`scripts/build_preentry_features.py` computes, for every Dataset-A signal,
using **only bars that closed strictly before the touch timestamp**:
completed-range (15/30/60/120-min, plus previous full research-session
range), ATR(14) on completed 5/15/30/60-min bars, EWMA point-volatility at
30/60/120-minute half-lives, the prior VXN close and its % change (lagged
per the verified engine's own `prior_session_close` convention), and RVOL
at 30/60/120-minute windows against the median same-time-of-day volume
over the prior 15/20/30 research sessions, clipped to a fixed a priori
`[0.10, 10.0]` bound (documented before any profitability was examined).

23 features total, causality proven by `tests/test_feature_causality.py`
(range/ATR/EWMA/RVOL sign and bound checks, VXN strict-lag check against
the same session-date convention used by the level-generation code, and a
static source-text check that the builder never references outcome/time-
identity columns).

See `docs/STAGE1_KNOWN_LIMITATIONS.md` for the `rvol_120m` high-missing-rate
finding.
