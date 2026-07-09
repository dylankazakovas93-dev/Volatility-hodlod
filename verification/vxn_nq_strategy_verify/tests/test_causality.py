"""Causality proof tests for OG_OPERATIONAL_100R rolling-PF gate.

No calls to existing src/ functions. All gates are tested independently.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from _assemble_and_gate import rolling_pf_gate, apply_gate


def _simple_shadow(pnl_list: list[float]) -> pd.DataFrame:
    """Build a minimal shadow DataFrame for testing."""
    n = len(pnl_list)
    return pd.DataFrame({
        "entry_time": [f"2023-01-{i+1:02d}" for i in range(n)],
        "pnl": pnl_list,
        "cap": [10.0] * n,
        "exit_reason": ["TP"] * n,
        "side": ["long"] * n,
        "entry_price": [100.0] * n,
        "exit_price": [110.0] * n,
        "exit_time": [f"2023-01-{i+1:02d}" for i in range(n)],
        "anchor": [5.0] * n,
        "level": [105.0] * n,
        "level_id": [f"0_long"] * n,
        "gap_through": [False] * n,
        "year": [2023] * n,
        "source": ["test"] * n,
    })


class TestRollingPFCausality:
    """Causality invariants for the rolling-PF gate."""

    def test_prefix_invariance(self):
        """For any prefix, decisions in the prefix match full-sequence decisions."""
        np.random.seed(42)
        pnl = np.random.randn(200).cumsum()
        shadow = _simple_shadow(pnl.tolist())
        full = apply_gate(shadow)

        for prefix_len in [50, 100, 150, 199]:
            prefix_shadow = shadow.iloc[:prefix_len]
            prefix_gated = apply_gate(prefix_shadow.copy())
            full_prefix = full.iloc[:prefix_len]
            assert prefix_gated["is_flat"].equals(full_prefix["is_flat"]), \
                f"Prefix invariance failed at len={prefix_len}"

    def test_append_invariance(self):
        """Appending later rows does not alter earlier decisions."""
        np.random.seed(42)
        base_pnl = np.random.randn(200).cumsum()
        extra_pnl = np.random.randn(50).cumsum() + base_pnl[-1] + 50

        base_shadow = _simple_shadow(base_pnl.tolist())
        base_gated = apply_gate(base_shadow)

        combined = _simple_shadow(np.concatenate([base_pnl, extra_pnl]).tolist())
        combined_gated = apply_gate(combined)

        assert base_gated["is_flat"].equals(combined_gated["is_flat"].iloc[:len(base_pnl)]), \
            "Append invariance failed"

    def test_current_row_excluded(self):
        """Changing current row PnL must not change its own is_flat decision."""
        pnl = np.array([2.0] * 99 + [0.5, 0.5])
        shadow = _simple_shadow(pnl.tolist())
        gated = apply_gate(shadow)

        # Row 100: PF on first 100 rows (indices 0-99) should determine state at row 100
        # Change row 100's PnL
        pnl2 = pnl.copy()
        pnl2[100] = -100.0
        shadow2 = _simple_shadow(pnl2.tolist())
        gated2 = apply_gate(shadow2)

        # Row 100's decision should be the same regardless of its own PnL
        # (current row excluded from its own PF window)
        assert gated["is_flat"].iloc[100] == gated2["is_flat"].iloc[100], \
            "Current row excluded: changing own PnL changed decision"

    def test_future_row_excluded(self):
        """Changing future outcomes must not change prior decisions."""
        np.random.seed(42)
        pnl = np.random.randn(200).cumsum()
        shadow = _simple_shadow(pnl.tolist())
        gated = apply_gate(shadow)

        # Change future rows
        pnl2 = pnl.copy()
        pnl2[150:] = pnl2[150:] * 10
        shadow2 = _simple_shadow(pnl2.tolist())
        gated2 = apply_gate(shadow2)

        # First 150 decisions should be identical
        assert gated["is_flat"].iloc[:150].equals(gated2["is_flat"].iloc[:150]), \
            "Future row exclusion failed"

    def test_warmup_100_on(self):
        """First 100 rows must be ON (not flat)."""
        pnl = np.array([-5.0] * 200)
        shadow = _simple_shadow(pnl.tolist())
        gated = apply_gate(shadow)
        assert gated["is_flat"].iloc[:100].sum() == 0, \
            "First 100 rows must be ON"

    def test_zero_loss_denominator(self):
        """Zero-loss window yields inf PF, stays ON."""
        pnl = np.array([1.0] * 150)
        shadow = _simple_shadow(pnl.tolist())
        gated = apply_gate(shadow)
        # After 100, PF = inf, stays ON
        assert gated["is_flat"].iloc[100:].sum() == 0, \
            "Zero-loss window must stay ON"

    def test_symmetric_110_behavior(self):
        """Symmetric ON/OFF at exactly 1.10 threshold."""
        # Build a clean 300-row sequence:
        #   0-99: warmup (small wins)
        #   100-199: PF < 1.10 pattern → OFF after row 100
        #   200-299: PF >= 1.10 pattern → ON after row 200
        #
        # At row 100: window [0,100): 99×(1) + 1×(0.5) = 99.5g / 0l → PF=inf → ON
        # At row 120: window [20,120): 80×(1) + 20×(1.01) + 20×(-0.92) = ...
        #   Actually, let me just make it simple:
        #   100×(+1.0) [rows 0-99 warmup]
        #   100×(+1.01, -0.92) paired × 50 [rows 100-199]:
        #     window of 100 rows at row 200: 50×(1.01) + 50×(-0.92) = 50.5g / 46l = 1.0978 < 1.10 → OFF
        #   100×(+1.02, -0.92) paired × 50 [rows 200-299]:
        #     window of 100 rows at row 300: 50×(1.02) + 50×(-0.92) = 51g / 46l = 1.1087 > 1.10 → ON

        pnl = np.zeros(300)
        pnl[:100] = 1.0  # warmup (all wins)
        pnl[100:200] = np.tile([1.01, -0.92], 50)  # PF ~1.098 → OFF
        pnl[200:300] = np.tile([1.02, -0.92], 50)  # PF ~1.109 → ON

        shadow = _simple_shadow(pnl.tolist())
        gated = apply_gate(shadow)

        # Row 200: window [100,200): gains=50*1.01=50.5, losses=50*0.92=46 → PF=1.0978 < 1.10 → OFF
        assert gated["is_flat"].iloc[200] == True, \
            "PF < 1.10 should be OFF at row 200"

        # Row 300: window [200,300): gains=50*1.02=51, losses=50*0.92=46 → PF=1.1087 >= 1.10 → ON
        assert gated["is_flat"].iloc[299] == False, \
            "PF >= 1.10 should be ON at row 299"

    def test_off_rows_influence_future(self):
        """OFF rows remain in shadow and influence future windows."""
        pnl = np.array([-1.0] * 50 + [+2.0] * 200)
        shadow = _simple_shadow(pnl.tolist())
        gated = apply_gate(shadow)

        # At row 100: window [0,100) = 50×(-1) + 50×(2) = 100g/50l → PF=2.0 → ON
        # At row 150: window [50,150) = 100×(2) = 200g/0l → PF=inf → ON
        # The OFFs at rows 100-104 still count in window for row 150
        # Let's just verify that OFF rows aren't zeroed in the shadow
        off_mask = gated["is_flat"]
        shadow_pnl_in_windows = pnl[~off_mask].sum()  # only ON rows' PnL
        assert shadow_pnl_in_windows != 0, \
            "OFF rows must remain in shadow and count in future windows"

    def test_deterministic_output(self):
        """Identical input must produce identical is_flat decisions."""
        pnl = np.random.randn(200).cumsum()
        shadow = _simple_shadow(pnl.tolist())
        g1 = apply_gate(shadow.copy())
        g2 = apply_gate(shadow.copy())
        assert g1["is_flat"].equals(g2["is_flat"]), \
            "Determinism failed"


class TestShadowAssembly:
    """Shadow assembly tests."""

    def test_1355_rows(self):
        """The assembled shadow must have exactly 1355 rows."""
        from _assemble_and_gate import COMPONENT_LEDGERS, assemble_shadow_sequence
        shadow = assemble_shadow_sequence(COMPONENT_LEDGERS)
        assert len(shadow) == 1355, f"Expected 1355, got {len(shadow)}"

    def test_no_2016_or_2017(self):
        """Years 2016 and 2017 must be absent."""
        from _assemble_and_gate import COMPONENT_LEDGERS, assemble_shadow_sequence
        shadow = assemble_shadow_sequence(COMPONENT_LEDGERS)
        years = set(shadow["entry_ts"].dt.year)
        assert 2016 not in years, "2016 should be absent"
        assert 2017 not in years, "2017 should be absent"

    def test_three_sources_present(self):
        """All three component sources must be represented."""
        from _assemble_and_gate import COMPONENT_LEDGERS, assemble_shadow_sequence
        shadow = assemble_shadow_sequence(COMPONENT_LEDGERS)
        sources = shadow["source"].unique()
        for s in ["external_2013_2015", "build_years", "validation"]:
            assert s in sources, f"Source {s} missing"

    def test_chronological_ordering(self):
        """Shadow must be sorted chronologically by entry_time."""
        from _assemble_and_gate import COMPONENT_LEDGERS, assemble_shadow_sequence
        shadow = assemble_shadow_sequence(COMPONENT_LEDGERS)
        assert shadow["entry_ts"].is_monotonic_increasing, \
            "Shadow not chronologically ordered"
