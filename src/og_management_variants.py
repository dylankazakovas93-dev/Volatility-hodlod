"""Stage C (full sweep): parameterized management/exit-simulation families for
the OG build-four-years research pipeline. Additive only -- reuses
src.strict_engine's touch/level/session helpers and src.og_build_variant_engine's
run_variant() skeleton (PROP_HARD_BLACKOUT, canonical entry-time restriction,
SAL toggle, HMM gate hook) without modifying either file.

Every management family below follows the same touch-bar-stop-only rigor as
strict_engine.simulate_from_touch / simulate_cond_be: the touch bar is
checked ONLY for a stop hit (a touch-bar target hit is never assumed a win).
The full state machine (stop/target/management-mechanism) only runs from the
bar AFTER the touch bar.

Families (see docs/OG_STAGE_C_MANAGEMENT.md for the full candidate list):
  - "none"       : no management at all (raw 1:1 TP/SL, no BE mechanism).
  - "barcount"   : canonical conditional-BE-at-N-bars mechanism (be_bars).
  - "exact_r"    : move stop to breakeven once price reaches +r_trigger*cap
                   favorable excursion; activates the bar AFTER the trigger
                   bar (no same-bar retroactive protection).
  - "profit_lock": same trigger timing as exact_r, but locks in
                   +lock_r*cap profit instead of exact breakeven.
  - "time_be"    : at minutes_elapsed since entry, arm BE only if (a) MFE
                   up to and including that bar >= mfe_r*cap, AND (b) that
                   bar's close is favorable relative to entry. One-shot
                   checkpoint; activates the following bar.
  - "scratch"    : once adverse excursion reaches -adverse_r*cap, arm a
                   scratch exit (close at entry/breakeven) the next time
                   price recovers to touch/cross entry, evaluated starting
                   the bar after arming. Original stop remains live
                   throughout (scratch is an additional exit path, not a
                   stop replacement).
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from src.strict_engine import (
    BE_BARS, SL_CAP, session_date, session_cutoff, prev_completed_range,
    touch_is_clean,
)
from src.og_build_variant_engine import in_prop_hard_blackout, entry_allowed_window
from src.metrics import profit_factor, max_drawdown, max_loss_streak


def _fav_adv(sign, h, l, entry_fill):
    """Return (favorable_excursion, adverse_excursion) implied by this bar's
    high/low, both in points, both using the trade's own sign convention
    (favorable is always >= 0 in the good case, adverse always <= 0)."""
    a = sign * (h - entry_fill)
    b = sign * (l - entry_fill)
    return max(a, b), min(a, b)


def simulate_managed(bars, touched_at, cutoff, entry_fill, sign, cap, *,
                      mode="barcount", be_bars=BE_BARS, r_trigger=None,
                      lock_r=None, minutes_elapsed=None, mfe_r=0.25,
                      adverse_r=None, target_r=1.0):
    """Generalized touch-bar-stop-only + full-state-machine simulator.

    `target_r` (Stage F): the target distance as a multiple of the per-trade
    stop distance `cap` (1R). Default 1.0 reproduces every prior stage's
    behavior exactly (target == cap, i.e. 1:1). The stop distance/cap itself
    is never changed by this parameter -- only the target moves. When
    target_r != 1.0, a hit of target returns a pnl of target_r * cap (not
    the flat `cap` constant used previously), so payoff/PF reflect the true
    R:R tested.

    Returns (pnl, exit_type, exit_ts). exit_type in {"SL","TP","BE","LOCK",
    "SCRATCH","cutoff"}.
    """
    touch_row = bars.loc[touched_at]
    orig_stop = entry_fill - sign * cap
    h0, l0 = float(touch_row["high"]), float(touch_row["low"])
    hit_stop = (l0 <= orig_stop) if sign > 0 else (h0 >= orig_stop)
    if hit_stop:
        return sign * (orig_stop - entry_fill), "SL", touched_at

    rest = bars.loc[touched_at: cutoff].iloc[1:]
    if rest.empty:
        return sign * (float(touch_row["close"]) - entry_fill), "cutoff", touched_at

    target_dist = target_r * cap
    target = entry_fill + sign * target_dist
    hi, lo, op, cl = (rest["high"].values, rest["low"].values, rest["open"].values, rest["close"].values)
    idx = rest.index
    n = len(hi)

    # --- barcount mode uses the exact canonical mechanism (arm-check via the
    # bar's OPEN at i==be_bars), independent of the generic MFE/MAE machinery
    # used by the other families.
    if mode in ("barcount", "none"):
        eff_be_bars = be_bars if mode == "barcount" else n + 1  # "none": never reach be_bars
        armed = checked = False
        for i in range(n):
            h, l = float(hi[i]), float(lo[i])
            if i < eff_be_bars:
                stop = orig_stop
            else:
                if not checked:
                    checked = True
                    o = float(op[i])
                    armed = (o >= entry_fill) if sign > 0 else (o <= entry_fill)
                stop = entry_fill if armed else orig_stop
            if sign > 0:
                if l <= stop:
                    return sign * (stop - entry_fill), ("BE" if (i >= eff_be_bars and armed) else "SL"), idx[i]
                if h >= target:
                    return target_dist, "TP", idx[i]
            else:
                if h >= stop:
                    return sign * (stop - entry_fill), ("BE" if (i >= eff_be_bars and armed) else "SL"), idx[i]
                if l <= target:
                    return target_dist, "TP", idx[i]
        return sign * (float(cl[-1]) - entry_fill), "cutoff", (idx[-1] if n else touched_at)

    # --- generic MFE/MAE-driven families -----------------------------------
    current_stop = orig_stop
    current_label = "SL"
    mfe = 0.0   # running max favorable excursion (points, sign-adjusted)
    mae = 0.0   # running min (most negative) adverse excursion
    scratch_armed = False
    triggered = False  # exact_r / profit_lock / time_be: has the mechanism fired yet

    for i in range(n):
        h, l, o, c = float(hi[i]), float(lo[i]), float(op[i]), float(cl[i])

        # 1. check exits using the stop/label decided at the END of the prior
        #    iteration (i.e. "activates starting next bar after trigger").
        if mode == "scratch":
            # original stop always stays live; scratch is an ADDITIONAL exit.
            if sign > 0:
                if l <= orig_stop:
                    return sign * (orig_stop - entry_fill), "SL", idx[i]
                if scratch_armed and h >= entry_fill:
                    return 0.0, "SCRATCH", idx[i]
                if h >= target:
                    return target_dist, "TP", idx[i]
            else:
                if h >= orig_stop:
                    return sign * (orig_stop - entry_fill), "SL", idx[i]
                if scratch_armed and l <= entry_fill:
                    return 0.0, "SCRATCH", idx[i]
                if l <= target:
                    return target_dist, "TP", idx[i]
        else:
            if sign > 0:
                if l <= current_stop:
                    return sign * (current_stop - entry_fill), current_label, idx[i]
                if h >= target:
                    return target_dist, "TP", idx[i]
            else:
                if h >= current_stop:
                    return sign * (current_stop - entry_fill), current_label, idx[i]
                if l <= target:
                    return target_dist, "TP", idx[i]

        # 2. update running MFE/MAE/close-favorable using THIS bar's data
        #    (now fully observed -- causal, no lookahead into future bars).
        fav, adv = _fav_adv(sign, h, l, entry_fill)
        mfe = max(mfe, fav)
        mae = min(mae, adv)
        close_fav = sign * (c - entry_fill) > 0

        # 3. decide whether a NEW trigger fires this bar; if so, effective
        #    starting the NEXT iteration only (never retroactive this bar).
        if mode == "exact_r":
            if not triggered and mfe >= r_trigger * cap:
                triggered = True
                current_stop, current_label = entry_fill, "BE"
        elif mode == "profit_lock":
            if not triggered and mfe >= r_trigger * cap:
                triggered = True
                current_stop = entry_fill + sign * (lock_r * cap)
                current_label = "LOCK"
        elif mode == "time_be":
            elapsed = i + 1  # minutes elapsed since entry (1-min bars)
            if not triggered and elapsed == minutes_elapsed:
                if mfe >= mfe_r * cap and close_fav:
                    triggered = True
                    current_stop, current_label = entry_fill, "BE"
        elif mode == "scratch":
            if not scratch_armed and mae <= -adverse_r * cap:
                scratch_armed = True
        else:
            raise ValueError(f"unknown mode {mode}")

    return sign * (float(cl[-1]) - entry_fill), "cutoff", (idx[-1] if n else touched_at)


def run_variant_managed(bars, ranges, events, *, mgmt_kwargs, sal_enabled=False,
                         blocked_window=(11 * 60, 15 * 60), hmm_gate=None,
                         tie_order="age"):
    """Chronological single-global-position engine, structurally identical to
    og_build_variant_engine.run_variant, but delegating trade management to
    simulate_managed(**mgmt_kwargs). Stage C holds sal_enabled=False (Stage B
    freeze) and the CANONICAL 11:00-15:00 blocked_window (not the Stage E
    RESEARCH_ENTRY_BLACKOUT_10_16) so this sweep isolates the management
    variable alone. PROP_HARD_BLACKOUT is unconditional, as in run_variant."""
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
    sal_session = None
    sal_armed_at = None

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

        if hmm_gate is not None and not hmm_gate(ts):
            for _ in group:
                record_skip("hmm_gate")
            continue

        cutoff = session_cutoff(ts)
        if cutoff is None:
            for _ in group:
                record_skip("no_cutoff")
            continue

        sess = session_date(ts)
        if sess != sal_session:
            sal_session = sess
            sal_armed_at = None

        if sal_enabled and sal_armed_at is not None and ts >= sal_armed_at:
            for _ in group:
                record_skip("SAL")
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
            if tie_order == "age":
                ordered = sorted(group, key=lambda e: (e["created_at"], e["side"]))
            elif tie_order == "nearest":
                ordered = sorted(group, key=lambda e: e["dist_prior_close"])
            elif tie_order == "farthest":
                ordered = sorted(group, key=lambda e: -e["dist_prior_close"])
            else:
                raise ValueError(f"unknown tie_order {tie_order}")
            chosen, losers = ordered[0], ordered[1:]
            for _ in losers:
                record_skip("simultaneous_collision")
        else:
            chosen = group[0]

        sign = -1.0 if chosen["side"] == "upper" else 1.0
        cap = min(1.5 * anchor, SL_CAP)
        clean = touch_is_clean(bars, ts, chosen["level"])
        fill = chosen["level"] if clean else float(bars.loc[ts, "close"])

        pnl, ex, exit_ts = simulate_managed(
            bars, ts, cutoff, fill, sign, cap, **mgmt_kwargs)

        year = pd.Timestamp(sess).year
        exit_price = fill + sign * pnl
        executed.append({
            "level_id": chosen["level_id"], "session_date": sess, "year": year,
            "side": chosen["side"], "entry_time": ts, "exit_time": exit_ts,
            "entry_price": fill, "exit_price": exit_price, "level": chosen["level"],
            "anchor": anchor, "cap": cap,
            "exit_reason": ex, "pnl": pnl, "gap_through": not clean,
        })

        pos_exit_time = exit_ts
        if pnl < -0.1 and ex not in ("BE", "LOCK", "SCRATCH"):
            sal_armed_at = exit_ts

    ex_df = pd.DataFrame(executed)

    if len(ex_df):
        assert not ex_df["entry_time"].apply(in_prop_hard_blackout).any(), (
            "PROP_HARD_BLACKOUT violated: an entry occurred at/after 16:00 "
            "and before 19:00 ET")
        assert not ex_df["exit_time"].apply(in_prop_hard_blackout).any(), (
            "PROP_HARD_BLACKOUT violated: a position remained open into "
            "16:00-19:00 ET")

    summary = {
        "total_physical_touches": total_physical_touches,
        "executed": len(ex_df),
        "skipped_SAL": skip_counts.get("SAL", 0),
        "skipped_position_open": skip_counts.get("position_open", 0),
        "skipped_hmm_gate": skip_counts.get("hmm_gate", 0),
        "skipped_blocked_time": skip_counts.get("blocked_time", 0),
        "skipped_prop_hard_blackout": skip_counts.get("prop_hard_blackout", 0),
    }
    return summary, ex_df
