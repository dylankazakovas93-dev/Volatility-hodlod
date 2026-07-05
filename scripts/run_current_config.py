#!/usr/bin/env python3
"""Thin entrypoint: runs the primary strict engine using the frozen config's
paths/parameters. Equivalent to calling `python3 -m src.strict_engine`
directly -- this wrapper exists only so `scripts/` has one obvious "run the
current config" command.

Usage:
    python3 scripts/run_current_config.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv \
        --out-dir outputs
"""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.strict_engine import main  # noqa: E402

if __name__ == "__main__":
    main()
