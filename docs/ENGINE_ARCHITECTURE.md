# Engine Architecture

Two independently-coded implementations exist in this handoff:

- `src/strict_engine.py` — the primary engine
- `src/independent_strict_engine.py` — a freshly-written second
  implementation used as a cross-check

Both share only `src/data_loader.py` (file loading) and
`src/level_generation.py` (the level-placement formula — data prep, not one
of the frozen execution mechanics under test). Everything below — touch
detection, session/window logic, anchor computation, the single-position /
SAL state machine, conditional BE, fill policy, and PF — is implemented
**twice, independently**, in separate code. Neither engine imports the
other's simulation or state-machine functions.

## Chronological state machine (both engines follow this sequence)

1. **Load and validate NQ bars** — `src/data_loader.py::load_1m_ohlcv()`,
   sorted, tz-converted to America/New_York.
2. **Load and validate VXN** — `load_gvz_daily()` (generic daily-close loader).
3. **Generate session levels** — `src/level_generation.py::generate_levels()`,
   one row per session with `upper_level`, `lower_level`, `created_at`.
4. **Determine each level side's physical first touch** — scan the bars
   strictly between `created_at` (exclusive) and the level's expiry
   (exclusive) for the first bar where the level falls inside `[low, high]`
   or the close crosses it relative to the prior close. At most one touch
   is ever found per level side.
5. **Sort touch events chronologically** by timestamp (ties broken by
   oldest-level-first).
6. **Determine session state** for the touch's timestamp — which session
   (19:00 ET -> next-day 15:00 ET) it belongs to, and whether SAL is
   currently armed for that session.
7. **Apply static eligibility** — anchor must exist (a valid previous
   completed 60-minute range), the timestamp must fall in the valid entry
   window (19:00-11:00 ET), and a valid session cutoff must exist.
8. **Apply SAL state** — if SAL is armed for the current session and the
   touch falls at/after the arming timestamp, the touch is consumed without
   a trade.
9. **Apply global-position state** — if a position is currently open
   (touch falls strictly before the open position's exit time), the touch
   is consumed without a trade. If the touch falls exactly on the exit
   time, it is also consumed (same-bar re-entry is blocked).
10. **Resolve simultaneous touches** — if two level sides share the exact
    same touch timestamp, the older level is entered; the younger is
    marked a simultaneous-touch collision and consumed.
11. **Calculate anchor, stop, and target** — `anchor` = previous completed
    60-minute range; `stop_distance = min(1.5 * anchor, 200)`;
    `target_distance = stop_distance`.
12. **Simulate the trade** — touch-bar stop-first check, then bar-by-bar
    TP/SL/conditional-BE resolution until TP, SL, BE, or the session cutoff.
13. **Record the exit** — exit reason, exit timestamp, exit price, PnL.
14. **Activate SAL if required** — if the realized PnL is a qualifying loss
    (`pnl < -0.1` and `exit_reason != "BE"`), SAL arms at the exit
    timestamp for the remainder of that session.
15. **Record all skipped events** — every touch that did not result in a
    trade is recorded with its specific skip reason (no_anchor,
    blocked_time, no_cutoff, SAL, position_open, same_bar_reentry,
    simultaneous_collision).
16. **Produce metrics and annual results** — net points, PF, win rate, tWR,
    max drawdown, max loss streak, cost-adjusted variants, and a per-year
    breakdown.

## Why the causal guarantees hold

- **Overlap is impossible** because step 9 checks the actual exit
  timestamp of the currently-open position against every subsequent
  touch's timestamp before allowing a new entry — there is only ever one
  "open position" variable in the state machine, never a list.
- **Later retests are impossible** because each level side's physical
  first touch is computed once (step 4) and is the only touch event ever
  considered for that side — there is no loop that re-scans a level side
  after its first touch or after a skip.
- **Future outcomes cannot affect earlier entry decisions** because the
  engine processes touch events in strict chronological order (step 5) and
  every state variable (position-open-until, SAL-armed-at) is only ever
  set using a timestamp that has already been computed by an earlier trade
  simulation — nothing is computed out of order or backfilled.
- **SAL cannot activate before a loss exits** because SAL is armed at
  `exit_ts` (step 14), which is the outcome of step 12's simulation, not at
  entry time — arming always happens strictly after the simulation that
  produced the qualifying loss has completed.
- **All physical touches reconcile to either executed or skipped rows** —
  every touch event enters exactly one of the two output tables
  (`baseline_executed.csv` or `baseline_skipped.csv`), and
  `tests/test_strategy_invariants.py::test_skip_categories_reconcile_to_physical_touch_population`
  asserts `len(executed) + len(skipped) == total physical touches` directly
  against the generated output files.

## Verifying the two engines agree

```
python3 scripts/compare_engines.py \
    --reference outputs/baseline_executed.csv \
    --comparison outputs/independent_executed.csv
```

Expected: 1,107 reference rows, 1,107 comparison rows, 1,107 matched, zero
in every other category. See `docs/REPRODUCIBILITY.md` for the full
end-to-end command sequence.
