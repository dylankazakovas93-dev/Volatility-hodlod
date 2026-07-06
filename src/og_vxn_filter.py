"""OG VXN-filter exploratory module (POST_VALIDATION_EXPLORATORY_REDEVELOPMENT).

Implements the causal VXN-prev-close merge rule and a thin filter-predicate
factory used by scripts/og_vxn_exploratory.py. Additive only -- does not
modify src/strict_engine.py or src/og_management_variants.py.

Causal timing rule (see docs/OG_VXN_EXPLORATORY_PROTOCOL.md for full
reasoning): an NQ session that begins at 19:00 ET on calendar day D uses the
most recently completed VXN REGULAR-SESSION close known before 19:00 ET on
day D. VXN's cash index closes ~16:15 ET, well before 19:00 ET, so day D's
own VXN close (if VXN traded that day) IS causal for day D's 19:00 ET
session. If VXN did not trade on day D (weekend/holiday), forward-fill from
the most recent prior VXN trading day's close, up to MAX_FORWARD_FILL_DAYS
calendar days. Gaps larger than that are treated as "no VXN filter
available" (excluded from any VXN-filtered candidate; NO_VXN_FILTER is
unaffected since it does not consult VXN at all).
"""
from __future__ import annotations

import hashlib

import pandas as pd

MAX_FORWARD_FILL_DAYS = 5  # observed max real gap in the data is 4 calendar days


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_vxn_normalized(path="data/vxn_daily_2018_2026_normalized.csv"):
    df = pd.read_csv(path, parse_dates=["vxn_date"])
    df = df.sort_values("vxn_date").reset_index(drop=True)
    return df


def build_session_date_to_vxn_close(vxn_df, session_dates, max_ff_days=MAX_FORWARD_FILL_DAYS):
    """For each NQ session_date (a date string 'YYYY-MM-DD' identifying the
    session that begins 19:00 ET the evening before that calendar date --
    see src.strict_engine.session_date), return the causal VXN prev-close:
    the VXN close on that same calendar date if VXN traded that day
    (causal: VXN's ~16:15 ET close precedes the 19:00 ET session open on the
    same calendar date), else the most recent prior VXN trading day's close
    within max_ff_days, else None (no VXN filter available for that
    session).

    Returns dict session_date_str -> (vxn_close or None, gap_days int).
    """
    vxn_by_date = {d.strftime("%Y-%m-%d"): c for d, c in zip(vxn_df["vxn_date"], vxn_df["vxn_close"])}
    sorted_dates = sorted(vxn_by_date.keys())
    sorted_ts = [pd.Timestamp(d) for d in sorted_dates]

    out = {}
    for sd in sorted(set(session_dates)):
        target = pd.Timestamp(sd)
        if sd in vxn_by_date:
            out[sd] = (vxn_by_date[sd], 0)
            continue
        # find most recent VXN trading day strictly before target
        prior = [t for t in sorted_ts if t < target]
        if not prior:
            out[sd] = (None, None)
            continue
        prior_ts = max(prior)
        gap = (target - prior_ts).days
        if gap <= max_ff_days:
            out[sd] = (vxn_by_date[prior_ts.strftime("%Y-%m-%d")], gap)
        else:
            out[sd] = (None, gap)
    return out


FILTER_DEFS = {
    "NO_VXN_FILTER": None,
    "VXN_PREV_CLOSE_GE_20": ("ge", 20.0),
    "VXN_PREV_CLOSE_GE_25": ("ge", 25.0),
    "VXN_PREV_CLOSE_GE_30": ("ge", 30.0),
    "VXN_PREV_CLOSE_LE_20": ("le", 20.0),
    "VXN_PREV_CLOSE_LE_25": ("le", 25.0),
    "VXN_PREV_CLOSE_LE_30": ("le", 30.0),
}


def passes_filter(filter_name, vxn_close):
    """vxn_close may be None (no VXN available for that session -> blocked
    for any real filter, always allowed for NO_VXN_FILTER)."""
    spec = FILTER_DEFS[filter_name]
    if spec is None:
        return True
    if vxn_close is None:
        return False
    op, thresh = spec
    return (vxn_close >= thresh) if op == "ge" else (vxn_close <= thresh)
