# Final Forward Ledger Method

This document describes the July 8-August 31, 2026 forward-ledger inputs under
`artifacts/forward_ledger/final/`.

These are synthetic internal risk scenarios, not actual future trades,
guaranteed performance or a historical track record.

## Two RR Ledgers

The final bundle keeps the two frozen configurations physically separate:

- `forward_1rr.csv`: `OG_OPERATIONAL_100R`, `rr_config_id=1rr`,
  independently replayed 1.00R target history.
- `forward_1_5rr.csv`: `OG_PRIMARY_150R`, `rr_config_id=1_5rr`,
  independently replayed 1.50R target history.

The 1.50R ledger is not derived by multiplying 1RR winners. The wider target
can change exit time, exit reason, holding duration, MAE/MFE, open-position
blocking, chronology, and total executed trade count.

## Historical Packets

Each row is a complete historical trade packet. P&L, stop, target, exit reason,
duration, MAE, MFE, and rolling-PF switch state remain attached to the same
packet. The final ledgers include `trade_packet_id`, `chronological_block_id`,
`source_ledger_id`, and `source_block_id` so Prop Lab can sample complete units
without redrawing individual fields.

## MAE/MFE

MAE/MFE are computed from actual one-minute OHLC paths from recorded entry time
through recorded exit time, inclusive. The 2013-2015 Databento raw file is
first reduced to the canonical continuous NQ contract rule: standard quarterly
contracts only, selecting the highest-volume contract per UTC date. The
2018-2026 continuous NQ file is supplied locally or via `NQ_1M_2018_2026_CSV`.

The limitation is source resolution: one-minute OHLC does not reveal tick
ordering inside the entry or exit minute.

## Normalization

The strategy scale field is `raw_stop_points`, which maps to the frozen
strategy cap:

`cap = min(1.5 * anchor, SL_CAP=200)`

Normalized fields are:

- `pnl_R = pnl_points / raw_stop_points`
- `effective_stop_R = effective_stop_points / raw_stop_points`
- `target_R = target_points / raw_stop_points`
- `mae_R = mae_points / raw_stop_points`
- `mfe_R = mfe_points / raw_stop_points`

Rows with invalid non-positive denominators fail generation.

## Forward Point Scale

`point_scale_scenarios.json` models point scale independently from PF using:

- recent 2025-2026 raw-stop geometry;
- historical July/August geometry;
- neighbouring June/September summer geometry.

Scenarios are `scale_central`, `scale_minus_10`, `scale_plus_10`,
`scale_minus_15`, `scale_plus_15`, `scale_minus_20`, and `scale_plus_20`.
For a selected packet, Prop Lab should draw one coherent forward raw-stop scale
and reconstruct all responsive point fields from that scale and the packet's R
ratios. It should not scale winners, losers, MAE, or MFE independently.

## PF Scenarios

`forward_scenario_manifest.json` contains synthetic forward PF assumptions:

- `FORWARD_PF_ASSUMPTION_1_35`
- `FORWARD_PF_ASSUMPTION_1_50`
- `FORWARD_PF_ASSUMPTION_1_65`

PF is calibrated only by transparent weighting of complete calendar/month
blocks. Individual trade outcomes, P&L, stops, targets, MAE/MFE, and exit
reasons are never edited. Losing blocks and negative months remain eligible.

## Seasonality

`calendar_blocks.csv` is based on historical calendar/month blocks. July and
August blocks receive primary seasonality weight. June and September receive
neighbouring-summer support weight, and other months remain low-weight broader
pool support. This avoids treating every generic consecutive two-month window
as July/August evidence.

## Regime Paths

The scenario manifest includes `stable`, `gradual_degradation`,
`favourable_persistence`, and `abrupt_tail`. Gradual degradation and tail
stress are implemented through time-varying probabilities of complete
predefined blocks, not manual edits to individual rows.

## Rolling-PF Switch

The final ledgers preserve the selected retrospective monitoring overlay:
rolling points-PF, last 100 completed trades, threshold 1.10, symmetric
re-entry. Switch state is carried as `rolling_pf_is_flat`,
`rolling_pf_switch_state`, and `effective_exit_reason`. The switch is not a
static full-history filter.

## Prop Lab Consumption

Prop Lab should select:

1. `rr_config_id`;
2. PF assumption;
3. regime path;
4. point-scale scenario;
5. forecast dates.

Then it should sample complete packets or complete calendar blocks according
to the chosen scenario metadata.

`realized_anchor.csv` contains the July 7, 2026 +150 point realized result
exactly once, marked `rr_config_id=UNKNOWN` because no config-specific
evidence was provided. It is not blended into either source library.

## Limitations

- The rolling-PF switch was selected retrospectively and is not fresh
  out-of-sample validation.
- The PF assumptions are scenario controls, not predictions or guarantees.
- July/August seasonality has limited sample depth, so the bundle uses a
  documented hierarchy rather than pretending the evidence is exact.
- Tick-level MAE/MFE ordering inside a one-minute bar is unavailable.
