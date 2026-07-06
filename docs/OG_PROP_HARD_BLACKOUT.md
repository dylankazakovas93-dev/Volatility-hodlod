# PROP_HARD_BLACKOUT: permanent 16:00-19:00 ET prohibition

## Status: implemented, unit-tested. Applies to every engine variant and
every candidate tested in the OG build-four-years research pipeline, past
and future.

## What it is

`PROP_HARD_BLACKOUT` is a hard-coded, always-on constraint: no entry may
ever occur, and no position may ever remain open, during the interval
**16:00:00 ET (inclusive) through 19:00:00 ET (exclusive)**.

It is implemented once, in the shared engine path
(`src/og_build_variant_engine.py::in_prop_hard_blackout()`), and is checked
unconditionally inside `run_variant()` -- independent of, and evaluated
*before*, the research-selected `blocked_window` parameter. No candidate
parameterization can disable, widen, or bypass it, because it is not exposed
as a parameter at all.

## How it differs from the three other time-based rules

| Rule | Scope | Configurable per-candidate? |
|---|---|---|
| `PROP_HARD_BLACKOUT` (16:00-19:00 ET) | permanent, structural | No -- hard-coded constant |
| Research-selected blocked entry interval (e.g. `RESEARCH_ENTRY_BLACKOUT_10_16`, Stage E candidates) | research parameter | Yes -- `blocked_window` arg |
| Forced-liquidation cutoff (currently 15:00 ET) | canonical, `session_cutoff()` | Not varied in this research (frozen) |
| Session boundary (19:00 ET, `session_date()`) | canonical | No |

Today, `PROP_HARD_BLACKOUT` is redundant in practice: the 15:00 ET
liquidation cutoff already guarantees no position is open past 15:00, well
before 16:00. The rule is encoded anyway so that if a future change moves
the liquidation cutoff later (or otherwise changes window/session logic),
16:00-19:00 ET can never be silently reopened for trading.

## Implementation

```python
PROP_HARD_BLACKOUT_START_MIN = 16 * 60  # 16:00 ET, inclusive
PROP_HARD_BLACKOUT_END_MIN = 19 * 60    # 19:00 ET, exclusive (new session)

def in_prop_hard_blackout(ts):
    et = ts.tz_convert(ET)
    m = et.hour * 60 + et.minute
    return PROP_HARD_BLACKOUT_START_MIN <= m < PROP_HARD_BLACKOUT_END_MIN
```

In `run_variant()`, every touch group is checked against
`in_prop_hard_blackout(ts)` first, ahead of the research `blocked_window`
check, the HMM gate, and all other gates. A touch that falls in the
blackout is recorded under `skipped_prop_hard_blackout` and is never
re-evaluated: touches are keyed by their own physical `touched_at`
timestamp and each group is visited exactly once, in chronological order,
so there is no code path that could "retry" a blocked touch later (e.g.
after 19:00).

Two defensive runtime assertions were added directly in `run_variant()`,
executed on every run for every candidate:

```python
assert not ex_df["entry_time"].apply(in_prop_hard_blackout).any()
assert not ex_df["exit_time"].apply(in_prop_hard_blackout).any()
```

These will raise immediately (rather than silently produce bad output) if
any future change to window/cutoff logic ever allows an entry or exit into
16:00-19:00 ET.

## Tests

`tests/test_prop_hard_blackout.py`, 9 tests, all passing:

1. `test_1559_allowed_by_hard_blackout` -- 15:59 ET is allowed by this rule
   (may still be blocked by other rules; this test only exercises
   `PROP_HARD_BLACKOUT`).
2. `test_1600_blocked` -- 16:00 ET is blocked.
3. `test_1859_blocked` -- 18:59 ET is blocked.
4. `test_1900_allowed_new_session` -- 19:00 ET is allowed (new session per
   `session_date()`).
5. `test_position_cannot_be_open_at_1600_given_15_cutoff` -- structural
   proof that `session_cutoff()` never returns a timestamp at/after 16:00
   ET, so a position simulated against that cutoff cannot be open when the
   blackout begins; also `test_touch_at_1600_is_blocked_and_permanently_consumed`
   exercises `run_variant`'s own defensive assertions end-to-end.
6. `test_touch_at_1859_blocked_does_not_execute_after_1900` -- a touch
   blocked at 18:59 does not reappear/execute after 19:00 (permanent
   consumption).

Additional regression tests: `test_1200_touch_blocked_by_research_window_not_hard_blackout`
(demonstrates the two rules are independent) and
`test_no_executed_trade_ever_has_entry_or_exit_in_blackout` (end-to-end,
multi-touch scenario spanning the boundary).

Run: `python -m pytest tests/test_prop_hard_blackout.py -q` -> 9 passed.

## Terminology note (item 2 of the task)

Separately, the former Stage E "10:00-16:00 ET" label has been renamed to
`RESEARCH_ENTRY_BLACKOUT_10_16` and is described as a *blocked entry
interval* (entries blocked from 10:00 ET onward), not an "allowed trading
window." See the updated Stage E doc. As of this writing the full Stage E
matrix re-run and the doc-wide renaming pass were **not completed** in this
session -- see the top-level status note added to `docs/OG_BUILD_FOUR_YEARS_SUMMARY.md`
for what remains.
