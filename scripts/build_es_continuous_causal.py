#!/usr/bin/env python3
"""Build causal ES continuous 1-minute CSV from Databento raw GLBX.MDP3 archives.

Causal contract-selection rule:
  For ES RTH session D, choose the standard quarterly contract with the highest
  total traded volume during the *previous* completed RTH session (D-1).
  Never use any volume from session D.

Same-day volume contract selection is strictly forbidden.
"""
from __future__ import annotations

import argparse
import sys
import io
import zipfile
import zstandard
from zoneinfo import ZoneInfo
from datetime import time, timedelta, date

import pandas as pd

STANDARD_CONTRACT_RE = r"^ES[HMUZ]\d$"
NY = ZoneInfo("America/New_York")
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)
MONTH_CODES = {"H": 3, "M": 6, "U": 9, "Z": 12}


def contract_expiry_key(c: str) -> tuple:
    return (int(c[3:]), MONTH_CODES.get(c[2], 99))


def decompress_csv_bytes(zip_path: str) -> bytes:
    zf = zipfile.ZipFile(zip_path)
    csv_zst_name = [n for n in zf.namelist() if n.endswith(".csv.zst")][0]
    compressed = zf.read(csv_zst_name)
    dctx = zstandard.ZstdDecompressor()
    reader = dctx.stream_reader(io.BytesIO(compressed))
    buf = io.BytesIO()
    while True:
        chunk = reader.read(1048576)
        if not chunk:
            break
        buf.write(chunk)
    return buf.getvalue()


def previous_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def find_prior_with_data(sess: date, lookup: dict, syms: list) -> tuple[date, str | None]:
    """Walk back through prior weekdays until we find a session with RTH
    volume data for at least one contract in syms. Returns (prior_date, winner)
    or (None, None) if no prior data exists at all."""
    prior = sess - timedelta(days=1)
    for _ in range(30):
        while prior.weekday() >= 5:
            prior -= timedelta(days=1)
        best = None
        bv = -1
        for sym in syms:
            v = lookup.get((prior, sym))
            if v is not None and v > bv:
                bv = v
                best = sym
        if best is not None:
            return prior, best
        prior -= timedelta(days=1)
    return None, None


def segment_winner_map(raw: pd.DataFrame) -> dict:
    """Given a raw per-contract DataFrame, return {session_date: winning_contract}."""
    std = raw[raw["symbol"].str.match(STANDARD_CONTRACT_RE)].copy()
    ts_local = std["ts_event"].dt.tz_convert(NY)
    std["session"] = ts_local.dt.date

    is_rth = ts_local.dt.time.between(RTH_OPEN, RTH_CLOSE, inclusive="left")
    rth = std[is_rth].copy()
    rth["session"] = rth["ts_event"].dt.tz_convert(NY).dt.date
    rth_vol = rth.groupby(["session", "symbol"], as_index=False)["volume"].sum()

    session_contracts = std.groupby("session")["symbol"].unique()
    lookup = {(r["session"], r["symbol"]): r["volume"] for _, r in rth_vol.iterrows()}

    sessions = sorted(rth_vol["session"].unique())
    wmap = {}
    for sess in sessions:
        _, best = find_prior_with_data(sess, lookup, session_contracts[sess])
        if best is None:
            best = sorted(session_contracts[sess], key=contract_expiry_key)[0]
        wmap[sess] = best
    return wmap


def apply_winner(raw: pd.DataFrame, wmap: dict) -> pd.DataFrame:
    std = raw[raw["symbol"].str.match(STANDARD_CONTRACT_RE)].copy()
    ts_local = std["ts_event"].dt.tz_convert(NY)
    std["session"] = ts_local.dt.date
    std["winner"] = std["session"].map(wmap)
    kept = std[std["symbol"] == std["winner"]].sort_values("ts_event")
    return kept[["ts_event", "open", "high", "low", "close", "volume", "symbol", "session"]].rename(
        columns={"ts_event": "timestamp", "symbol": "contract", "session": "session_date"}
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", action="append", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    print("reading and building segment-level winner maps", flush=True)
    all_winner_maps = {}
    segment_tables = []
    for zp in args.zip:
        sys.stdout.flush()
        text = decompress_csv_bytes(zp)
        raw = pd.read_csv(io.BytesIO(text), usecols=["ts_event", "open", "high", "low", "close", "volume", "symbol"])
        raw["ts_event"] = pd.to_datetime(raw["ts_event"], utc=True)
        
        wm = segment_winner_map(raw)
        for k, v in wm.items():
            if k in all_winner_maps:
                if all_winner_maps[k] != v:
                    print(f"  WARNING: duplicate session {k}: {all_winner_maps[k]} vs {v}", flush=True)
            else:
                all_winner_maps[k] = v
        
        seg = apply_winner(raw, wm)
        segment_tables.append(seg)
        print(f"  {zp}: {len(seg)} rows, {len(wm)} sessions mapped", flush=True)

    full = pd.concat(segment_tables).sort_values("timestamp").reset_index(drop=True)
    full["roll_day"] = (full["contract"] != full["contract"].shift(1)).astype(int)
    if len(full):
        full.loc[0, "roll_day"] = 0

    full.to_csv(args.out, index=False)
    print(f"wrote {len(full)} rows to {args.out}", flush=True)
    print(f"span: {full['timestamp'].iloc[0]} -> {full['timestamp'].iloc[-1]}", flush=True)
    print(f"contracts: {full['contract'].nunique()}, roll_days: {int(full['roll_day'].sum())}", flush=True)


if __name__ == "__main__":
    sys.exit(main())