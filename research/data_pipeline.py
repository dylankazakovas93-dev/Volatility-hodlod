"""
Build a continuous front-month NQ series from raw Databento GLBX.MDP3 ohlcv-1m
dumps (parent symbol NQ.FUT -> every outright contract month + calendar spreads).

Method: volume-based front month, selected per custom trading SESSION (18:00 ET
open -> 17:00 ET close next day), not per calendar day and not per bar. One
contract is used for the entire session so a roll never happens mid-session,
which keeps every 60m/120m/EOS trade window on a single instrument.

No back-adjustment is applied. Raw absolute prices are used, so a session
that lands on a roll (front month changes vs the prior session) can show a
small level jump from the outright contract basis spread. Those sessions are
flagged (roll=True) in the output rather than silently smoothed over.
"""
import re
import zoneinfo
import zstandard as zstd
import pandas as pd
import numpy as np

ET = zoneinfo.ZoneInfo("America/New_York")
UTC = zoneinfo.ZoneInfo("UTC")

OUTRIGHT_RE = re.compile(r"^NQ[FGHJKMNQUVXZ]\d$")


def _decompress(path: str) -> bytes:
    dctx = zstd.ZstdDecompressor()
    out = bytearray()
    with open(path, "rb") as f:
        with dctx.stream_reader(f) as reader:
            while True:
                chunk = reader.read(1 << 20)
                if not chunk:
                    break
                out.extend(chunk)
    return bytes(out)


def load_raw(path: str) -> pd.DataFrame:
    """Load a single databento ohlcv-1m .csv.zst into a DataFrame of outright
    contracts only (calendar spreads like NQH8-NQM8 are dropped)."""
    raw = _decompress(path)
    from io import BytesIO
    df = pd.read_csv(BytesIO(raw))
    df = df[df["symbol"].str.match(OUTRIGHT_RE)].copy()
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    return df[["ts_event", "symbol", "open", "high", "low", "close", "volume"]]


def session_date(ts_utc: pd.Series) -> pd.Series:
    """CME-style trade date: a session runs 18:00 ET -> 17:00 ET next day.
    Bars from 18:00-23:59 ET belong to the FOLLOWING calendar day's session."""
    ts_et = ts_utc.dt.tz_convert(ET)
    shifted = ts_et + pd.Timedelta(hours=6)  # 18:00 -> next midnight
    return shifted.dt.date


def build_continuous(df: pd.DataFrame) -> pd.DataFrame:
    """Pick, per session, the outright contract with the largest summed
    session volume, and splice its bars into one continuous series."""
    df = df.copy()
    df["session"] = session_date(df["ts_event"])

    vol_by_session_symbol = (
        df.groupby(["session", "symbol"])["volume"].sum().reset_index()
    )
    front = (
        vol_by_session_symbol.sort_values("volume", ascending=False)
        .drop_duplicates("session")
        .sort_values("session")[["session", "symbol"]]
        .rename(columns={"symbol": "front_symbol"})
    )
    front["roll"] = front["front_symbol"] != front["front_symbol"].shift(1)
    front.loc[front.index[0], "roll"] = False  # first session is not a "roll"

    merged = df.merge(front, on="session")
    cont = merged[merged["symbol"] == merged["front_symbol"]].copy()
    cont = cont.sort_values("ts_event").reset_index(drop=True)
    cont = cont.rename(columns={"symbol": "contract"})
    return cont[["ts_event", "session", "contract", "roll",
                 "open", "high", "low", "close", "volume"]]


def year_slice(cont: pd.DataFrame, year: int, warmup_days: int = 5) -> pd.DataFrame:
    """Return sessions whose session-date falls in `year`, plus `warmup_days`
    of the immediately preceding sessions so the first session of the year has
    a real prior-session high/low to build its deviation grid from."""
    sessions = sorted(cont["session"].unique())
    in_year = [s for s in sessions if s.year == year]
    if not in_year:
        return cont.iloc[0:0]
    first_idx = sessions.index(in_year[0])
    start_idx = max(0, first_idx - warmup_days)
    keep_sessions = set(sessions[start_idx: sessions.index(in_year[-1]) + 1])
    out = cont[cont["session"].isin(keep_sessions)].copy()
    out["in_target_year"] = out["session"].apply(lambda s: s.year == year)
    return out.reset_index(drop=True)
