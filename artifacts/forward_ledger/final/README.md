# Final Prop Lab Forward-Ledger Bundle

Forecast window: July 8, 2026 through August 31, 2026.

Use `forward_1rr.csv` and `forward_1_5rr.csv` as physically separate source
libraries. Do not sample `../forward_source_pool.csv` directly for Prop Lab
without first selecting one RR configuration.

Selection order:

1. RR configuration: `1rr` or `1_5rr`.
2. PF assumption: `FORWARD_PF_ASSUMPTION_1_35`, `1_50`, or `1_65`.
3. Regime path: `stable`, `gradual_degradation`, `favourable_persistence`, or
   `abrupt_tail`.
4. Point-scale scenario: `scale_central`, `scale_minus_10`, `scale_plus_10`,
   `scale_minus_15`, `scale_plus_15`, `scale_minus_20`, or `scale_plus_20`.
5. Forecast dates.

Each row is a complete historical trade packet with P&L, stop, target,
MAE/MFE, exit reason, duration, and switch state kept together. Normalized R
columns are provided so Prop Lab can coherently translate the same packet into
the selected July/August point-scale environment.

`realized_anchor.csv` contains the July 7, 2026 +150 point realized result
once for `rr_config_id=1rr` and once for `rr_config_id=1_5rr`, based on the
user-confirmed statement that both configurations hit +150. It is not blended
into either historical source library.

These are synthetic internal risk scenarios, not actual future trades,
guaranteed performance or a historical track record.

Streamlit explorer:

```bash
python3 -m streamlit run apps/forward_ledger_app.py --server.port 8501
```
