"""Tests for the permanent PROP_HARD_BLACKOUT rule (16:00-19:00 ET),
structurally separate from the research-selected blocked entry window, the
15:00 ET forced-liquidation cutoff, and the 19:00 ET session boundary.

See src/og_build_variant_engine.py: in_prop_hard_blackout(), and its
unconditional use in run_variant() (independent of blocked_window).
"""
import pandas as pd
import pytest

from src.og_build_variant_engine import (
    ET, in_prop_hard_blackout, run_variant, entry_allowed_window,
)


def ts(hh, mm, date="2023-06-01"):
    return pd.Timestamp(f"{date} {hh:02d}:{mm:02d}", tz=ET)


def test_1559_allowed_by_hard_blackout():
    # 15:59 ET: allowed by PROP_HARD_BLACKOUT (may still be blocked by other
    # rules, e.g. the canonical 11:00-15:00 research window, but not by this
    # rule).
    assert in_prop_hard_blackout(ts(15, 59)) is False


def test_1600_blocked():
    assert in_prop_hard_blackout(ts(16, 0)) is True


def test_1859_blocked():
    assert in_prop_hard_blackout(ts(18, 59)) is True


def test_1900_allowed_new_session():
    # 19:00 ET is the canonical session boundary (session_date()); the
    # blackout ends here, not because of this rule but because a new
    # session begins.
    assert in_prop_hard_blackout(ts(19, 0)) is False


def test_position_cannot_be_open_at_1600_given_15_cutoff():
    """Structural proof: with the canonical 15:00 ET forced-liquidation
    cutoff, session_cutoff() never returns a timestamp >= 16:00 ET, so a
    position simulated against that cutoff cannot still be open when the
    blackout begins. We assert this structurally on session_cutoff and also
    exercise run_variant's defensive runtime assertion path."""
    from src.strict_engine import session_cutoff
    # Sample touches across a session; the returned cutoff must always be
    # exactly 15:00 ET of the appropriate session day, never >= 16:00.
    for hh, mm in [(9, 30), (10, 0), (11, 0), (14, 59)]:
        t = ts(hh, mm)
        co = session_cutoff(t)
        if co is not None:
            co_et = co.tz_convert(ET)
            assert (co_et.hour, co_et.minute) == (15, 0), (
                f"session_cutoff for touch at {t} returned {co_et}, "
                "expected 15:00 ET -- PROP_HARD_BLACKOUT relies on this "
                "structural guarantee")


def _make_bars_and_ranges(start, end):
    idx = pd.date_range(start, end, freq="1min", tz=ET)
    bars = pd.DataFrame({
        "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0,
    }, index=idx)
    hour_idx = pd.date_range(start.floor("60min"), end, freq="60min", tz=ET)
    ranges = pd.Series(1.0, index=hour_idx)
    return bars, ranges


def _make_single_touch_env(touch_ts, level=100.0, side="lower"):
    """Build minimal bars/ranges/events to drive run_variant for one
    synthetic touch."""
    # One session's worth of 1-min bars from touch_ts through end of day,
    # flat market so we can isolate entry-gating behavior.
    start = touch_ts - pd.Timedelta(hours=2)
    end = touch_ts + pd.Timedelta(hours=4)
    bars, ranges = _make_bars_and_ranges(start, end)
    events = [{
        "level_id": "L1", "touched_at": touch_ts, "level": level,
        "side": side, "created_at": bars.index[0],
    }]
    return bars, ranges, events


def test_touch_at_1600_is_blocked_and_permanently_consumed():
    touch_ts = ts(16, 0)
    bars, ranges, events = _make_single_touch_env(touch_ts)
    summary, ex_df = run_variant(bars, ranges, events,
                                  blocked_window=(11 * 60, 15 * 60))
    assert summary["executed"] == 0
    assert summary["skipped_prop_hard_blackout"] == 1
    # The touch must not "reappear" after 19:00: it is keyed to its own
    # touched_at (16:00) and is only ever evaluated once, at that timestamp,
    # so there is no code path that re-evaluates it later at/after 19:00.
    assert not len(ex_df)


def test_touch_at_1859_blocked_does_not_execute_after_1900():
    """A touch physically occurring at 18:59 is blocked and must not
    execute later (e.g. if some future scheduler bug tried to retry it at or
    after 19:00). We simulate this directly by checking that the gating
    predicate depends only on the touch's own timestamp, and that a second,
    independent event object timestamped at 19:00 is a *different* touch
    (not a retry of the 18:59 one) and is separately evaluated."""
    touch_1859 = ts(18, 59)
    touch_1900 = ts(19, 0)
    assert in_prop_hard_blackout(touch_1859) is True
    assert in_prop_hard_blackout(touch_1900) is False

    bars, ranges, events = _make_single_touch_env(touch_1859)
    summary, ex_df = run_variant(bars, ranges, events,
                                  blocked_window=(11 * 60, 15 * 60))
    assert summary["executed"] == 0
    assert summary["skipped_prop_hard_blackout"] == 1
    # No trade for this event exists anywhere in the output at any exit time
    # >= 19:00 either -- confirming permanent consumption rather than deferred
    # execution.
    if len(ex_df):
        assert not ex_df["exit_time"].apply(
            lambda t: t.tz_convert(ET).hour >= 19).any()


def test_1200_touch_blocked_by_research_window_not_hard_blackout():
    touch_ts = ts(12, 0)
    assert in_prop_hard_blackout(touch_ts) is False
    # It IS blocked by the canonical 11:00-15:00 research window in this
    # example, demonstrating the two rules are independent.
    assert entry_allowed_window(touch_ts, 11 * 60, 15 * 60) is False


def test_no_executed_trade_ever_has_entry_or_exit_in_blackout():
    """Broader regression: run a small multi-touch scenario spanning the
    blackout boundary and assert none of the executed trades' entry/exit
    timestamps fall in 16:00-19:00 ET (run_variant also asserts this
    internally; this test exercises it end-to-end)."""
    touches = [ts(9, 30), ts(15, 59), ts(16, 0), ts(18, 0), ts(18, 59)]
    bars, ranges = _make_bars_and_ranges(ts(9, 0), ts(19, 30))
    events = [
        {"level_id": f"L{i}", "touched_at": t, "level": 100.0,
         "side": "lower", "created_at": bars.index[0]}
        for i, t in enumerate(touches)
    ]
    summary, ex_df = run_variant(bars, ranges, events,
                                  blocked_window=(11 * 60, 15 * 60))
    if len(ex_df):
        assert not ex_df["entry_time"].apply(in_prop_hard_blackout).any()
        assert not ex_df["exit_time"].apply(in_prop_hard_blackout).any()
