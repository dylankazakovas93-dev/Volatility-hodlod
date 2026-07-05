#!/usr/bin/env python3
"""Recover the earlier Codex 1,116-row local replay artifact.

The exact engine for that result was an inline Python command, not a committed
script. This recovery step therefore records the existing ledger artifact and
labels it as recovered-output-only, not a fully recovered original engine.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "outputs/nq_both_cap200_be45_onepos_local_2018_2026.csv"
DST = ROOT / "outputs/codex_original_1116.csv"
META = ROOT / "outputs/codex_original_1116_recovery.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def pf(s: pd.Series) -> float:
    gross = float(s[s > 0].sum())
    loss = float(-s[s < 0].sum())
    return gross / loss if loss else float("inf")


def maxdd(s: pd.Series) -> float:
    eq = s.cumsum()
    return float((eq - eq.cummax()).min())


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"missing source artifact: {SRC}")
    df = pd.read_csv(SRC)
    df.to_csv(DST, index=False)
    p = df["pnl"].astype(float)
    meta = {
        "status": "RECOVERED_OUTPUT_ONLY_FAILED_ENGINE_RECOVERY",
        "reason": "The original 1,116-row engine was run as inline Python and was not committed before this reconciliation.",
        "source": str(SRC),
        "destination": str(DST),
        "rows": len(df),
        "net": float(p.sum()),
        "pf": pf(p),
        "maxdd": maxdd(p),
        "sha256": sha256(DST),
    }
    META.write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
