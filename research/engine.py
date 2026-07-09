"""
Faithful Python port of the Pine v6 "Dev + Cluster Confluence" indicator's
state machine: session deviation grid, volume clusters, mitigation, and
confluence-zone liveness. Produces raw candidate signals for two entry
variants (formation-instant, retest) — no fills, no MAE/MFE, no
non-overlap filtering here; that happens in backtest.py.

Every quantity used at bar i is computed only from bars <= i (or, for the
session grid, from the prior *completed* session) — no future bar is read
at any point, matching how the indicator would actually behave live.
"""
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

TICK = 0.25
MS_MIN = 60_000

# indicator defaults, unchanged from the Pine source
BASE_MULT = 0.30
N_TIERS = 3
DEDUP_PTS = 15.0
MAX_LVLS = 15

VOL_LEN = 20
VOL_MULT = 1.5
CLOSE_THRESH = 0.20
VC_FIB = 0.50
MIT_THRESH = 0.79

ZONE_TOL = 20.0
TIGHT_TOL = 10.0
MIN_CLUSTER_MIN = 45
PREMIUM_AGE_MIN = 150
ZONE_PAD_TICKS = 2
ZONE_PAD = ZONE_PAD_TICKS * TICK

MIN_AGE_MS = MIN_CLUSTER_MIN * MS_MIN
PREM_AGE_MS = PREMIUM_AGE_MIN * MS_MIN


def f_tick(x):
    return np.round(x / TICK) * TICK


def build_session_grid(prev_high: float, prev_low: float) -> np.ndarray:
    """Port of f_buildLevels: dev ladder derived from the prior session's
    high/low/range, in the exact insertion order Pine uses (so dedup ties
    break the same way)."""
    if not (prev_high >= prev_low) or prev_high is None:
        return np.array([])
    p_hi, p_lo = f_tick(prev_high), f_tick(prev_low)
    p_mid = f_tick((p_hi + p_lo) / 2.0)
    p_vol = p_hi - p_lo
    if p_vol <= 0:
        return np.array([p_mid])
    step = f_tick(BASE_MULT * p_vol)

    used = [p_mid]
    levels = [p_mid]

    def try_add(px):
        if len(levels) >= MAX_LVLS:
            return
        if any(abs(u - px) < DEDUP_PTS for u in used):
            return
        used.append(px)
        levels.append(px)

    for k in range(1, N_TIERS + 1):
        try_add(f_tick(p_mid + k * step))
        try_add(f_tick(p_mid - k * step))
    for k in range(1, N_TIERS + 1):
        try_add(f_tick(p_hi + k * step))
        try_add(f_tick(p_lo - k * step))
    try_add(p_hi)
    try_add(p_lo)

    return np.array(levels)


def nearest_dev(px: float, levels: np.ndarray):
    if levels.size == 0:
        return None, np.inf
    d = np.abs(levels - px)
    i = np.argmin(d)
    return float(levels[i]), float(d[i])


@dataclass
class Cluster:
    cid: int
    born_bar: int
    born_time: pd.Timestamp
    high: float
    low: float
    rng: float
    ctype: int  # +1 bull, -1 bear
    cpx: float
    mitigated: bool = False
    # retest side-tracking state, kept per cluster across its whole life
    side: str = None  # 'above' | 'below' | 'inside' | None (never yet evaluated)
    was_live: bool = False


def run_engine(bars: pd.DataFrame, session_prior_hilo: dict) -> pd.DataFrame:
    """
    bars: continuous dataframe with columns
        ts_event, session, open, high, low, close, volume
      sorted ascending, one row per minute.
    session_prior_hilo: {session_date: (prev_high, prev_low) or None}
      prior-session high/low to seed each session's deviation grid
      (None for the very first session in the feed, matching a fresh chart).

    Returns a DataFrame of candidate signals:
        bar_index, time, session, variant, direction, zone_top, zone_bottom,
        premium, cluster_id, dist_to_dev
    """
    n = len(bars)
    ts = bars["ts_event"].to_numpy()
    sess = bars["session"].to_numpy()
    o = bars["open"].to_numpy(dtype=float)
    h = bars["high"].to_numpy(dtype=float)
    l = bars["low"].to_numpy(dtype=float)
    c = bars["close"].to_numpy(dtype=float)
    v = bars["volume"].to_numpy(dtype=float)

    vol_sma = bars["volume"].rolling(VOL_LEN, min_periods=VOL_LEN).mean().to_numpy()
    rng = h - l
    high_vol = v > vol_sma * VOL_MULT
    is_bull = high_vol & (c > o) & (c >= h - rng * CLOSE_THRESH)
    is_bear = high_vol & (c < o) & (c <= l + rng * CLOSE_THRESH)

    grid_cache = {}

    def grid_for(session_date):
        if session_date in grid_cache:
            return grid_cache[session_date]
        prior = session_prior_hilo.get(session_date)
        g = build_session_grid(prior[0], prior[1]) if prior else np.array([])
        grid_cache[session_date] = g
        return g

    active: list[Cluster] = []
    next_cid = 0
    signals = []  # list of dicts

    for i in range(n):
        cur_time = ts[i]
        cur_sess = sess[i]
        cur_close = c[i]

        # 1) mitigation check for existing clusters (skip the cluster's own birth bar)
        for cl in active:
            if cl.mitigated or i <= cl.born_bar:
                continue
            if cl.ctype == 1:
                limit = cl.high - cl.rng * MIT_THRESH
                if cur_close < limit:
                    cl.mitigated = True
            else:
                limit = cl.low + cl.rng * MIT_THRESH
                if cur_close > limit:
                    cl.mitigated = True

        # 2) spawn new cluster on this bar if it qualifies
        if is_bull[i]:
            target = f_tick(l[i] + rng[i] * VC_FIB)
            active.append(Cluster(next_cid, i, cur_time, h[i], l[i], rng[i], 1, target))
            next_cid += 1
        if is_bear[i]:
            target = f_tick(h[i] - rng[i] * VC_FIB)
            active.append(Cluster(next_cid, i, cur_time, h[i], l[i], rng[i], -1, target))
            next_cid += 1

        # 3) zone liveness + signal generation, vs THIS bar's session grid
        grid = grid_for(cur_sess)
        for cl in active:
            if cl.mitigated:
                continue
            age_ms = (cur_time - cl.born_time) / np.timedelta64(1, "ms")
            dev_px, dist = nearest_dev(cl.cpx, grid)
            live = (dev_px is not None) and (age_ms >= MIN_AGE_MS) and (dist <= ZONE_TOL)

            if not live:
                cl.was_live = False
                continue

            z_top = max(cl.cpx, dev_px) + ZONE_PAD
            z_bot = min(cl.cpx, dev_px) - ZONE_PAD
            premium = (age_ms >= PREM_AGE_MS) or (dist <= TIGHT_TOL)

            just_activated = not cl.was_live
            cl.was_live = True

            if just_activated:
                # formation-instant candidate: direction from price vs zone at this bar
                if cur_close > z_top:
                    signals.append(dict(bar_index=i, time=cur_time, session=cur_sess,
                                         variant="formation", direction="long",
                                         zone_top=z_top, zone_bottom=z_bot,
                                         premium=premium, cluster_id=cl.cid, dist_to_dev=dist))
                elif cur_close < z_bot:
                    signals.append(dict(bar_index=i, time=cur_time, session=cur_sess,
                                         variant="formation", direction="short",
                                         zone_top=z_top, zone_bottom=z_bot,
                                         premium=premium, cluster_id=cl.cid, dist_to_dev=dist))
                # if price is already inside the band, no directional formation signal
                # reset side tracking fresh for the retest state machine
                if cur_close > z_top:
                    cl.side = "above"
                elif cur_close < z_bot:
                    cl.side = "below"
                else:
                    cl.side = "inside"
                continue

            # retest state machine (only once the zone is already live)
            if cl.side in ("above", None) and l[i] <= z_top and cur_close >= z_bot:
                # was above (or unresolved) and price traded down into the band
                if cl.side == "above":
                    signals.append(dict(bar_index=i, time=cur_time, session=cur_sess,
                                         variant="retest", direction="long",
                                         zone_top=z_top, zone_bottom=z_bot,
                                         premium=premium, cluster_id=cl.cid, dist_to_dev=dist))
                cl.side = "inside"
            elif cl.side in ("below", None) and h[i] >= z_bot and cur_close <= z_top:
                if cl.side == "below":
                    signals.append(dict(bar_index=i, time=cur_time, session=cur_sess,
                                         variant="retest", direction="short",
                                         zone_top=z_top, zone_bottom=z_bot,
                                         premium=premium, cluster_id=cl.cid, dist_to_dev=dist))
                cl.side = "inside"
            elif cur_close > z_top:
                cl.side = "above"
            elif cur_close < z_bot:
                cl.side = "below"
            # else stays 'inside', no signal (already in the zone, no fresh touch)

        # drop mitigated clusters from the active list (mirrors Pine's array.remove)
        if active and any(cl.mitigated for cl in active):
            active = [cl for cl in active if not cl.mitigated]

    return pd.DataFrame(signals)


def session_prior_hilo_map(bars: pd.DataFrame) -> dict:
    """session_date -> (prior session high, prior session low), None for the
    first session present in the raw feed (no history to seed a grid from)."""
    summ = bars.groupby("session").agg(high=("high", "max"), low=("low", "min"))
    summ = summ.sort_index()
    sessions = list(summ.index)
    out = {}
    for idx, s in enumerate(sessions):
        if idx == 0:
            out[s] = None
        else:
            prev = sessions[idx - 1]
            out[s] = (summ.loc[prev, "high"], summ.loc[prev, "low"])
    return out
