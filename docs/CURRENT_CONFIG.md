# Current Config

The single source of truth for every parameter value is
`configs/nq_current_config.yaml`. This document is a human-readable index
into it — if the two ever disagree, the YAML file is authoritative.

| Rule | Value | YAML path |
|---|---|---|
| Timezone | America/New_York | `data.timezone` |
| RTH window | 09:30-16:00 ET | `level_generation.rth_start` / `rth_end` |
| IB minutes | 60 | `level_generation.ib_minutes` |
| Sigma multiplier | 1.25 | `level_generation.sigma_mult` |
| Fixed offset | 15.75 pts | `level_generation.fixed_offset` |
| Annual trading days | 252 | `level_generation.annual_trading_days` |
| Level lifetime | 20 newer levels | `level_generation.line_days` |
| Entry window | 19:00-11:00 ET | `entry_window.valid` |
| Session cutoff | 15:00 ET | `session_cutoff` |
| Anchor interval | 60 min | `risk.anchor_interval_minutes` |
| Range multiplier | 1.5 | `risk.range_multiplier` |
| Stop cap | 200 pts | `risk.stop_cap` |
| Reward-to-risk | 1.00 | `risk.reward_to_risk` |
| BE enabled | true | `risk.conditional_be.enabled` |
| BE bar | 45 | `risk.conditional_be.bar` |
| SAL enabled | true | `sal.enabled` |
| Creation-bar policy | excluded | `edge_cases.creation_bar_entry` |
| Expiry policy | excluded | `edge_cases.expiry_timestamp` |
| Same-bar re-entry | blocked | `edge_cases.same_bar_reentry` |
| Simultaneous-touch ordering | oldest-level-first | `edge_cases.simultaneous_touch_ordering` |
| Touch-bar resolution | stop-first | `edge_cases.touch_bar_resolution` |
| Gap-fill policy | deterministic realistic-fill | `edge_cases.gap_through_fill` |
| Headline result cost | 0.0 pts round-trip | `costs.headline_result_cost_pts` |
| Also reported at | 0.5 / 1.0 / 2.0 pts | `costs.also_reported` |

## Frozen result this config must reproduce

```yaml
eligible_candidates: 1841
executed_trades: 1107
net_pts: 6648.17
PF: 1.2924
avg_trade: 6.006
TP: 394
SL: 333
BE: 281
cutoff: 99
max_drawdown: -1290.29
negative_years: [2019, 2023, 2024]
```

`tests/test_strategy_invariants.py` and `tests/test_data.py` assert the
engine's hardcoded constants match this file, and that running the engine
against the canonical data reproduces every one of these numbers within the
documented tolerance (`net_pts` ± 0.05, `PF` ± 0.0005).

No important rule is a hidden, unexplained hardcoded constant — every value
the engine uses appears in `configs/nq_current_config.yaml` and is
cross-checked by the test suite.
