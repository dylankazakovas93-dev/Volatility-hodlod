# OG Stage C — Management (BE/exit-management) candidates (build years only)

Scope: `OG_BUILD_YEARS` only = {2018, 2020, 2023, 2026-partial}. Carries forward
the Stage B freeze (`sal_enabled=False`). No metric below includes
2019/2021/2022/2024/2025 trade outcomes.

## Candidates tested

| Label | be_bars | be_extra_lock | Description |
|---|---|---|---|
| BE45_lock0 | 45 | 0.0 | Canonical BE-45 (baseline candidate) |
| BE30_lock0 | 30 | 0.0 | Earlier BE trigger |
| BE60_lock0 | 60 | 0.0 | Later BE trigger |
| BE45_lock2 | 45 | 2.0 | Canonical BE-45 + 2pt profit lock beyond entry once armed |

Command: `python3 scripts/og_stage_c_management.py` (uses
`src/og_build_variant_engine.run_variant` with `sal_enabled=False` carried
from Stage B).

## Build-year aggregate results

| Candidate | n | net_pts | PF | win_rate | avg_trade | max_drawdown |
|---|---|---|---|---|---|---|
| BE45_lock0 | 507 | 4039.77 | 1.4533 | 0.3886 | 7.968 | -721.54 |
| BE30_lock0 | 512 | 4337.67 | 1.4891 | 0.3809 | 8.472 | -542.05 |
| BE60_lock0 | 500 | 4372.34 | 1.4548 | 0.4100 | 8.745 | -793.77 |
| BE45_lock2 | 507 | 3954.65 | 1.4437 | 0.6667 | 7.800 | -711.54 |

(Note: BE45_lock2's much higher "win_rate" is an artifact of counting any
locked-in-profit BE exit as a "win" under `pnl>0`; it is not directly
comparable to the other rows' win-rate definition without re-deriving BE
semantics, so it is not used as a deciding metric here.)

## Per-build-year breakdown

### BE30_lock0
| Year | n | net_pts | PF | max_drawdown |
|---|---|---|---|---|
| 2018 | 144 | -20.01 | 0.9863 | -414.06 |
| 2020 | 155 | 996.37 | 1.3150 | -542.05 |
| 2023 | 139 | 630.15 | 1.2333 | -512.83 |
| 2026 (partial) | 74 | 2731.17 | 2.7715 | -345.00 |

### BE60_lock0
| Year | n | net_pts | PF | max_drawdown |
|---|---|---|---|---|
| 2018 | 140 | 103.61 | 1.0709 | -317.36 |
| 2020 | 150 | 1301.84 | 1.3819 | -563.16 |
| 2023 | 137 | 99.04 | 1.0321 | -793.77 |
| 2026 (partial) | 73 | 2867.86 | 2.7313 | -423.81 |

(BE45_lock0 per-year figures are in `docs/OG_STAGE_B_SAL.md`'s SAL_off table.)

## Selection rationale

- BE30_lock0 has the best aggregate PF (1.4891) but **2018 is net-negative**
  (-20.01) — it fails the "all build years positive" bar that Stage B used.
- BE60_lock0 has the highest aggregate net_pts (4372.34) and **is the only
  candidate other than canonical BE45 with all 4 build years net-positive**
  (103.61 / 1301.84 / 99.04 / 2867.86), and it also has the highest per-trade
  average (8.745) and highest win rate (0.4100) among the directly comparable
  candidates.
- Its tradeoff is a larger aggregate max drawdown (-793.77, driven by the 2023
  fold specifically) than BE30 or BE45 — a real cost, but not disqualifying
  given every year still nets positive and the drawdown is concentrated in a
  single build year rather than being systemic.
- BE45_lock2's altered "win" semantics for locked BE exits make it not
  directly comparable on this metric set; its net_pts is also the lowest of
  the four, so it does not warrant using a nonstandard BE definition.

**Frozen decision: `be_bars = 60`, `be_extra_lock = 0.0`** (a later BE trigger
than canonical BE-45, no extra profit-lock threshold).

Raw outputs: `outputs/og_build_years/stage_c_*_build_years_trades.csv`,
`outputs/og_build_years/stage_c_management_results.json`.
