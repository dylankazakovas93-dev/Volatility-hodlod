# Causality Audit Report

## Invariants Proven

1. **Prefix invariance**: For any prefix length, decisions within the prefix match the full-sequence decisions. Proven for lengths 50, 100, 150, 199.

2. **Append invariance**: Appending 50 later rows did not alter any earlier is_flat decision.

3. **Current-row exclusion**: Changing row 100's PnL from +0.5 to -100.0 did not change its own is_flat decision.

4. **Future-row exclusion**: Multiplying all rows after index 150 by 10 did not change any decision at or before index 150.

5. **Warmup**: First 100 rows are always ON regardless of PnL.

6. **Zero-loss denominator**: All-gains windows produce inf PF, stay ON.

7. **Symmetric 1.10 threshold**: PF=1.0978 < 1.10 → OFF; PF=1.1087 ≥ 1.10 → ON.

8. **OFF rows influence future**: OFF/PnL rows remain in shadow and count in future windows.

9. **Deterministic output**: Identical input always produces identical decisions.

## Implementation Reference
- Gate function: `_assemble_and_gate.py::rolling_pf_gate`
- Test module: `tests/test_causality.py`
