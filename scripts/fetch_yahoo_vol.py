#!/usr/bin/env python3
"""Fetch daily OHLC from Yahoo chart API for volatility indexes."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import urllib.parse
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True, help="Yahoo symbol, e.g. ^VXN")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD inclusive-ish")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    start = int(dt.datetime.fromisoformat(args.start).replace(tzinfo=dt.timezone.utc).timestamp())
    end_dt = dt.datetime.fromisoformat(args.end).replace(tzinfo=dt.timezone.utc) + dt.timedelta(days=1)
    end = int(end_dt.timestamp())
    sym = urllib.parse.quote(args.symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={start}&period2={end}&interval=1d&events=history&includeAdjustedClose=true"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]

    rows = []
    for i, timestamp in enumerate(timestamps):
        close = quote["close"][i]
        if close is None:
            continue
        day = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).date().isoformat()
        rows.append([day, quote["open"][i], quote["high"][i], quote["low"][i], close])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "open", "high", "low", "close"])
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows -> {args.out}")


if __name__ == "__main__":
    main()
