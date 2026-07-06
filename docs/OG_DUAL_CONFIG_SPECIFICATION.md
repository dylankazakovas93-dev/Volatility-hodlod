# OG Dual-Config Specification: OG_PRIMARY_150R and OG_OPERATIONAL_100R

Status: `RETROSPECTIVE_BUILD_ONLY__NOT_VALIDATED` (both configs). This
document formalizes, as two named locked configuration files, the two
retrospective build configurations already produced by
`docs/OG_FINAL_BUILDOFF_BE45.md`'s 4-candidate bakeoff: Candidate B
(`configs/OG_PRIMARY_150R.yaml`) and Candidate A
(`configs/OG_OPERATIONAL_100R.yaml`). No new backtest, parameter search, or
optimization is performed here; every number in the companion
build-results docs is recomputed directly from the already-committed
ledgers `outputs/og_build_years/final_buildoff_{A,B}_build_years_trades.csv`.

## 1. Everything the two configs share

- **Level generation**: unchanged canonical `src/strict_engine.py` logic
  (RTH 09:30-16:00 ET, `ib_minutes=60`, `sigma_mult=1.25`, NQ
  `fixed_offset=15.75`, `line_days=20`). Not modified anywhere in the OG
  build-four-years research line.
- **Anchor/stop-cap calculation**: `cap = min(1.5 * anchor, SL_CAP)`,
  unchanged. Stage F (`src/og_management_variants.py`) never touches this
  formula — only the profit target moves.
- **One global position**: exactly one active position across the whole
  book at any time; no overlapping positions; no stacking.
- **Permanent physical first-touch consumption**: each level side has at
  most one physical touch ever. A touch that is blocked (by either
  blackout rule), unentered (SAL, HMM, position-open, or a
  simultaneous-touch collision), or otherwise not converted into a trade
  permanently consumes that side — there is no later retry.
- **No same-minute exit-then-re-entry.**
- **Oldest-level-first simultaneous ordering** (`tie_order: age`) when
  multiple touches are eligible at the same instant.
- **Conservative intrabar TP/SL ambiguity handling**: `simulate_managed`'s
  touch-bar-stop-only rule — the touch bar is checked ONLY for a stop hit;
  a touch-bar target hit is never assumed a win. The full
  stop/target/management state machine only runs from the bar *after* the
  touch bar.
- **SAL off** (`sal_enabled: false`), **no HMM gate** (`hmm_gate.enabled:
  false`) — both frozen per Stage B/D of the earlier Phase 1 work.
- **BE45 barcount management** (`mode: barcount`, `be_bars: 45`, no extra
  lock beyond exact breakeven) — see §2 below for the exact mechanism.
- **Entries blocked 10:00 ET through the 15:00 ET cutoff**
  (`RESEARCH_ENTRY_BLACKOUT_10_15`, `blocked_window_minutes: [600, 900]`)
  — this is a *blocked entry interval*, not an "allowed trading window."
- **Forced liquidation at 15:00 ET** (`session_cutoff()`), unchanged.
- **`PROP_HARD_BLACKOUT` 16:00-19:00 ET**, permanent and unconditional —
  see §6.
- **All existing causal/no-lookahead safeguards**: touches keyed by their
  own physical timestamp, visited exactly once in chronological order; the
  defensive `assert`s in `run_variant()` that no executed trade's entry or
  exit ever falls inside `PROP_HARD_BLACKOUT`.
- **Identical data/rolls/contracts/preprocessing**: `data/nq_1m/nq_continuous_2018_2026_1m.csv`
  (2,964,655 rows, 2018-01-01 through 2026-06-07), `data/vxn_daily_2018_2026.csv`.

## 2. The sole difference: profit target

The only parameter that differs is `target.target_r` in
`src/og_management_variants.py::simulate_managed`/`run_variant_managed`:
`target_r=1.50` for `OG_PRIMARY_150R` (Candidate B), `target_r=1.00` for
`OG_OPERATIONAL_100R` (Candidate A). `target_dist = target_r * cap`; the
stop distance `cap` itself is never altered by this parameter. When
`target_r != 1.0`, a hit of target returns `target_r * cap` points rather
than the flat `cap` constant, so PF/payoff figures reflect the true R:R
actually tested.

## 3. How BE45 operates (barcount management)

`src/og_management_variants.py`'s `mode="barcount"` reuses the same
touch-bar-stop-only pattern as `src/strict_engine.py`'s
`simulate_cond_be`/`simulate_from_touch`: the touch bar is checked only
for an immediate stop hit; if not stopped, the full state machine starts
from the bar after the touch bar. From there, **BE arms conditionally at
bar 45** (`be_bars=45`) counted from the touch/entry: if, by the 45th bar
after entry, the trade's favorable excursion has reached (or the position
is otherwise judged "favorable" per the mechanism's own condition — see
`simulate_managed`), the stop is moved to exact breakeven
(`be_extra_lock: 0.0`, i.e. no additional lock beyond breakeven). If the
trade is not favorable at that checkpoint, no BE arming occurs and the
original stop remains live for the rest of the trade. **BE arming is
independent of `target_r`**: it depends only on price action relative to
entry/cap, not on how far away the (variable) target sits. This is why,
in the paired-trade analysis (`outputs/og_build_years/final_buildoff_paired_trade_analysis.csv`,
category `be45_avoided_eventual_full_stop`), the count is exactly 0 for
both A-vs-B and C-vs-D — a same-entry trade that arms BE under the 1.50R
variant arms at the identical bar under the 1.00R variant (same stop,
same price path), so it can never be "at risk of a stop" under one target
and "BE-protected" under the other.

## 4. Target and stop are frozen at entry

Both `cap` (stop distance) and `target_dist = target_r * cap` are computed
once, at entry, from the anchor/cap formula and the fixed `target_r` for
that config. Neither value is recomputed or adjusted intrabar; the only
thing that can change post-entry is whether the stop has been moved to
breakeven by the BE45 mechanism (§3). The target level itself never moves.

## 5. Cutoff handling

`forced_liquidation_time_et: "15:00"` (`session_cutoff()`) is unchanged
and canonical. If a trade is still open when the 15:00 ET cutoff is
reached, it is closed at the cutoff price/time and recorded with
`exit_reason=cutoff`. Since the two configs' only difference is the
target distance, a config with a larger target (1.50R) mechanically
produces more cutoff exits on entries that would have hit the smaller
(1.00R) target before 15:00 but do not reach the larger one in time — see
`docs/OG_100R_VS_150R_MECHANICS.md` §"cutoff-caused-by-larger-target" for
the exact count (11 of 404 shared entries for A-vs-B).

## 6. Touch consumption / overlap prevention / hard blackout

- **Touch consumption**: permanent, as in §1 — a touch blocked by either
  blackout rule, or otherwise not entered, is never retried later (not
  even after `PROP_HARD_BLACKOUT` ends at 19:00).
- **Overlap prevention**: one global position (§1) — no second entry can
  occur while a position from either config's own simulation is open.
- **`PROP_HARD_BLACKOUT` (16:00-19:00 ET)**: structurally separate from,
  and evaluated *before*, the research-selected `blocked_window`
  (`in_prop_hard_blackout()` in `src/og_build_variant_engine.py`). It is
  hard-coded and unconditional — not exposed as a config parameter to
  either `OG_PRIMARY_150R` or `OG_OPERATIONAL_100R`, and cannot be
  disabled, widened, or bypassed by either config. In practice it is
  currently redundant given the 15:00 ET cutoff (no position can still be
  open at 16:00), but it is enforced independently (with runtime
  assertions on every entry/exit timestamp) so that a future change to
  the cutoff logic could never silently reopen 16:00-19:00 ET for trading.
  See `docs/OG_PROP_HARD_BLACKOUT.md` for full detail and
  `tests/test_prop_hard_blackout.py` (9 tests, all passing) for the test
  suite.

## 7. Why 1.50R is primary

`OG_PRIMARY_150R` (Candidate B) won the preregistered 4-candidate bakeoff
(`docs/OG_FINAL_BUILDOFF_BE45.md` §5) on the priority-ordered selection
criteria: highest completed-years avg R/trade (0.1067 vs 0.0968/0.0737/0.0709)
and highest PF_R (1.3299), with every completed year individually positive
for all four candidates, a floor year (2020) that still beats the other
candidates' floor years, only a modest drawdown cost (-8.50R vs -8.00R for
A), and a robustness check confirming the edge survives removing the best
single day and the best single completed year (§ same doc). It wins
because it won this preregistered comparison — not because 1.50R is
assumed superior in general — and it remains primary regardless of any
later comparison against `OG_OPERATIONAL_100R` under validation-year data.

## 8. Why 1.00R is retained

`OG_OPERATIONAL_100R` (Candidate A) is preserved because it dominates on
day-smoothness / prop-relevant diagnostics that a prop-firm consistency
rule would care about even though it loses on raw expectancy: higher win
rate (38.9% vs 30.7% completed-years trades-positive), higher
%profitable-days (55.7% vs 49.5%), shallower max drawdown (-8.00R vs
-8.50R), a shorter longest non-winning-day streak (7 vs 10), and profit
that is less concentrated in a handful of best days (45.4% vs 49.3% of net
points from the best 5 days). See `docs/OG_100R_VS_150R_MECHANICS.md` for
the full quantitative breakdown. It is retained as an independent
secondary research line, not as a fallback if the primary fails
validation.

## 9. Why neither may be silently changed after validation opens

Both configs were selected using only `OG_BUILD_YEARS` = {2018, 2020,
2023, 2026 (partial)} outcome data — no locked/validation-year (2019,
2021, 2022, 2024, 2025) result informed any part of either config. This is
preregistration: the whole point of holding out those five years is that
a strategy's parameters are fixed *before* anyone sees how it performs on
them. If either `target_r` (or any other now-locked parameter) were
changed after seeing validation-year performance — even to "fix" an
apparent failure or to pick whichever of the two configs happens to look
better on those years — the validation test would no longer be measuring
generalization; it would be curve-fit to the validation years themselves.
`docs/OG_VALIDATION_PROTOCOL_DUAL_CONFIG.md` makes this explicit as a
standing rule: report each config's validation result honestly, do not
select a configuration post hoc using validation-year performance, and do
not alter the gate itself after viewing results.
