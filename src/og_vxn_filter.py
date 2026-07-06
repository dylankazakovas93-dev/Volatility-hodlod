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
from collections import defaultdict

import pandas as pd

from src.strict_engine import BE_BARS, SL_CAP, session_date, session_cutoff, prev_completed_range, touch_is_clean
from src.og_build_variant_engine import in_prop_hard_blackout, entry_allowed_window
from src.og_management_variants import simulate_managed

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


def run_variant_managed_vxn(bars, ranges, events, vxn_map, filter_name, *,
                             mgmt_kwargs, blocked_window):
    """Structurally identical to
    src.og_management_variants.run_variant_managed, with SAL/HMM held off
    (matching the locked base configs: sal_enabled=false, hmm_gate
    disabled) and one additional skip reason, "vxn_filter", inserted
    alongside the existing skip checks. A VXN-blocked touch is consumed
    permanently exactly like any other skip (never retried), consistent
    with permanent_touch_consumption in the base configs.

    vxn_map: dict session_date_str -> (vxn_close_or_None, gap_days).
    """
    touched = [e for e in events if e["touched_at"] is not None]
    total_physical_touches = len(touched)

    for e in touched:
        pos = bars.index.get_indexer([e["touched_at"]])[0]
        e["prior_close"] = float(bars["close"].iloc[pos - 1]) if pos > 0 else float(bars["close"].iloc[pos])
        e["dist_prior_close"] = abs(e["level"] - e["prior_close"])

    groups = defaultdict(list)
    for e in touched:
        groups[e["touched_at"]].append(e)

    executed = []
    skip_counts = defaultdict(int)
    pos_exit_time = None

    def record_skip(reason):
        skip_counts[reason] += 1

    for ts in sorted(groups.keys()):
        group = groups[ts]

        anchor = prev_completed_range(ranges, ts)
        if anchor is None:
            for _ in group:
                record_skip("no_anchor")
            continue

        if in_prop_hard_blackout(ts):
            for _ in group:
                record_skip("prop_hard_blackout")
            continue

        if not entry_allowed_window(ts, *blocked_window):
            for _ in group:
                record_skip("blocked_time")
            continue

        cutoff = session_cutoff(ts)
        if cutoff is None:
            for _ in group:
                record_skip("no_cutoff")
            continue

        sess = session_date(ts)

        # VXN filter check: applied per session_date, before position-state
        # checks, so a blocked touch is consumed permanently regardless of
        # what the global position state was.
        vxn_close, _gap = vxn_map.get(sess, (None, None))
        if not passes_filter(filter_name, vxn_close):
            for _ in group:
                record_skip("vxn_filter")
            continue

        if pos_exit_time is not None and ts < pos_exit_time:
            for _ in group:
                record_skip("position_open")
            continue
        if pos_exit_time is not None and ts == pos_exit_time:
            for _ in group:
                record_skip("same_bar_reentry")
            continue

        if len(group) > 1:
            ordered = sorted(group, key=lambda e: (e["created_at"], e["side"]))
            chosen, losers = ordered[0], ordered[1:]
            for _ in losers:
                record_skip("simultaneous_collision")
        else:
            chosen = group[0]

        sign = -1.0 if chosen["side"] == "upper" else 1.0
        cap = min(1.5 * anchor, SL_CAP)
        clean = touch_is_clean(bars, ts, chosen["level"])
        fill = chosen["level"] if clean else float(bars.loc[ts, "close"])

        pnl, ex, exit_ts = simulate_managed(bars, ts, cutoff, fill, sign, cap, **mgmt_kwargs)

        year = pd.Timestamp(sess).year
        exit_price = fill + sign * pnl
        executed.append({
            "level_id": chosen["level_id"], "session_date": sess, "year": year,
            "side": chosen["side"], "entry_time": ts, "exit_time": exit_ts,
            "entry_price": fill, "exit_price": exit_price, "level": chosen["level"],
            "anchor": anchor, "cap": cap, "vxn_prev_close": vxn_close,
            "exit_reason": ex, "pnl": pnl, "gap_through": not clean,
        })

        pos_exit_time = exit_ts

    ex_df = pd.DataFrame(executed)

    if len(ex_df):
        assert not ex_df["entry_time"].apply(in_prop_hard_blackout).any()
        assert not ex_df["exit_time"].apply(in_prop_hard_blackout).any()

    summary = {
        "total_physical_touches": total_physical_touches,
        "executed": len(ex_df),
        "skipped_vxn_filter": skip_counts.get("vxn_filter", 0),
        "skipped_position_open": skip_counts.get("position_open", 0),
        "skipped_blocked_time": skip_counts.get("blocked_time", 0),
        "skipped_prop_hard_blackout": skip_counts.get("prop_hard_blackout", 0),
    }
    return summary, ex_df
