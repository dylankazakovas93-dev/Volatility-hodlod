#!/usr/bin/env python3
"""Refresh data/gvz_daily.csv with CBOE Gold ETF Volatility Index (GVZ) daily OHLC.

FRED (the canonical source, series GVZCLS) is not reachable from this
environment's network egress, so we pull the same index from Yahoo Finance
(^GVZ) instead — it tracks FRED's GVZCLS series (FRED only publishes the
close, Yahoo gives full daily OHLC).

Usage:
    python3 scripts/fetch_gvz.py [--start 2023-01-01] [--out data/gvz_daily.csv]
"""
import argparse
import csv
import datetime
import json
import urllib.request

YAHOO_CHART_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/%5EGVZ"
    "?range=10y&interval=1d"
)


def fetch_gvz_daily(start: str) -> list[tuple[str, float, float, float, float]]:
    req = urllib.request.Request(YAHOO_CHART_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)

    result = payload["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]

    rows = []
    for i, ts in enumerate(timestamps):
        o, h, l, c = quote["open"][i], quote["high"][i], quote["low"][i], quote["close"][i]
        if None in (o, h, l, c):
            continue
        date = datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
        if date < start:
            continue
        rows.append((date, round(o, 2), round(h, 2), round(l, 2), round(c, 2)))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2023-01-01", help="earliest date to keep (YYYY-MM-DD)")
    parser.add_argument("--out", default="data/gvz_daily.csv", help="output CSV path")
    args = parser.parse_args()

    rows = fetch_gvz_daily(args.start)
    with open(args.out, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "open", "high", "low", "close"])
        writer.writerows(rows)

    print(f"wrote {len(rows)} rows to {args.out} ({rows[0][0]} -> {rows[-1][0]})")


if __name__ == "__main__":
    main()
