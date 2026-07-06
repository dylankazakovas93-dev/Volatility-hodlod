"""Tests for the causal VXN-prev-close merge rule (src/og_vxn_filter.py),
part of docs/OG_VXN_EXPLORATORY_PROTOCOL.md. Covers: a weekend, a market
holiday, a missing/gap VXN session, and the DST transition boundary."""
import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.og_vxn_filter import build_session_date_to_vxn_close, load_vxn_normalized

VXN_PATH = os.path.join(REPO_ROOT, "data", "vxn_daily_2018_2026_normalized.csv")


def _vxn():
    return load_vxn_normalized(VXN_PATH)


def test_weekend_forward_fill():
    """Monday 2019-12-02 NQ session (19:00 ET Sun evening) has no VXN print
    on 2019-12-01 (Sunday) or 2019-11-30 (Saturday); the causal close for
    session_date 2019-12-02 must come from Friday 2019-11-29's close if
    2019-12-02 itself did not trade, or from that day's own close if it did.
    Actual data: 2019-12-02 IS a VXN trading day (Monday), so causal close
    for session_date 2019-12-02 is simply that day's own close (same-day,
    zero-gap causal per the 16:15 ET << 19:00 ET reasoning)."""
    vxn = _vxn()
    out = build_session_date_to_vxn_close(vxn, ["2019-12-02"])
    close, gap = out["2019-12-02"]
    own_close = float(vxn.loc[vxn["vxn_date"] == "2019-12-02", "vxn_close"].iloc[0])
    assert close == own_close
    assert gap == 0

    # A genuine no-VXN-trading calendar date standing in for a session (e.g.
    # if a session_date fell on Saturday 2019-11-30) must forward-fill from
    # the prior Friday close.
    out2 = build_session_date_to_vxn_close(vxn, ["2019-11-30"])
    close2, gap2 = out2["2019-11-30"]
    friday_close = float(vxn.loc[vxn["vxn_date"] == "2019-11-29", "vxn_close"].iloc[0])
    assert close2 == friday_close
    assert gap2 == 1


def test_thanksgiving_holiday_forward_fill():
    """Thanksgiving 2019-11-28 is a real, confirmed-absent VXN trading day
    (verified directly against the committed VXN file). A session_date of
    2019-11-28 must forward-fill from the prior trading day, 2019-11-27."""
    vxn = _vxn()
    dates = set(vxn["vxn_date"].dt.strftime("%Y-%m-%d"))
    assert "2019-11-28" not in dates  # Thanksgiving: confirmed absent
    assert "2019-11-27" in dates

    out = build_session_date_to_vxn_close(vxn, ["2019-11-28"])
    close, gap = out["2019-11-28"]
    prior_close = float(vxn.loc[vxn["vxn_date"] == "2019-11-27", "vxn_close"].iloc[0])
    assert close == prior_close
    assert gap == 1


def test_christmas_holiday_forward_fill():
    vxn = _vxn()
    dates = set(vxn["vxn_date"].dt.strftime("%Y-%m-%d"))
    assert "2019-12-25" not in dates  # Christmas: confirmed absent

    out = build_session_date_to_vxn_close(vxn, ["2019-12-25"])
    close, gap = out["2019-12-25"]
    # prior trading day should be 2019-12-24
    prior_dates = sorted(d for d in dates if d < "2019-12-25")
    prior = prior_dates[-1]
    prior_close = float(vxn.loc[vxn["vxn_date"] == prior, "vxn_close"].iloc[0])
    assert close == prior_close
    assert prior == "2019-12-24"


def test_no_gap_exceeds_max_forward_fill_in_committed_data():
    """The committed VXN file has no calendar gap exceeding 4 days anywhere
    in its 2017-12-01..2026-06-08 span (verified directly), so the
    max-forward-fill threshold of 5 days never actually excludes a real
    session in this study -- documented explicitly rather than assumed."""
    vxn = _vxn()
    diffs = vxn["vxn_date"].diff().dt.days.dropna()
    assert diffs.max() <= 4


def test_synthetic_long_gap_is_excluded_not_forward_filled():
    """A synthetic gap larger than MAX_FORWARD_FILL_DAYS must resolve to
    (None, gap) -- 'no VXN filter available' -- not a stale forward-fill."""
    synthetic = pd.DataFrame({
        "vxn_date": pd.to_datetime(["2020-01-01", "2020-01-20"]),
        "vxn_close": [15.0, 22.0],
    })
    out = build_session_date_to_vxn_close(synthetic, ["2020-01-15"], max_ff_days=5)
    close, gap = out["2020-01-15"]
    assert close is None
    assert gap == 14


def test_dst_spring_forward_boundary():
    """DST spring-forward 2019: 2019-03-10 (Sunday, clocks jump 2am->3am
    ET). The NQ session for calendar day 2019-03-11 begins 19:00 ET Sunday
    evening (already past the spring-forward at 2am), so ET offset changes
    do not affect which VXN close is causal -- 2019-03-08 (Friday) is the
    correct forward-filled source in this window."""
    vxn = _vxn()
    dates = set(vxn["vxn_date"].dt.strftime("%Y-%m-%d"))
    assert "2019-03-09" not in dates  # Saturday
    assert "2019-03-10" not in dates  # Sunday, DST switch day
    assert "2019-03-08" in dates

    out = build_session_date_to_vxn_close(vxn, ["2019-03-10", "2019-03-11"])
    close_sun, gap_sun = out["2019-03-10"]
    friday_close = float(vxn.loc[vxn["vxn_date"] == "2019-03-08", "vxn_close"].iloc[0])
    assert close_sun == friday_close
    assert gap_sun == 2
    # 2019-03-11 (Monday) is itself a trading day -> same-day causal close.
    close_mon, gap_mon = out["2019-03-11"]
    mon_close = float(vxn.loc[vxn["vxn_date"] == "2019-03-11", "vxn_close"].iloc[0])
    assert close_mon == mon_close
    assert gap_mon == 0


def test_dst_fall_back_boundary():
    """DST fall-back 2019-11-03 (Sunday, clocks fall 2am->1am ET). Verify
    the same-calendar-day-close-is-causal reasoning still holds: 2019-11-04
    (Monday) is a VXN trading day and supplies its own close for session
    2019-11-04, independent of the ET offset change the day before."""
    vxn = _vxn()
    dates = set(vxn["vxn_date"].dt.strftime("%Y-%m-%d"))
    assert "2019-11-04" in dates
    out = build_session_date_to_vxn_close(vxn, ["2019-11-04"])
    close, gap = out["2019-11-04"]
    mon_close = float(vxn.loc[vxn["vxn_date"] == "2019-11-04", "vxn_close"].iloc[0])
    assert close == mon_close
    assert gap == 0
