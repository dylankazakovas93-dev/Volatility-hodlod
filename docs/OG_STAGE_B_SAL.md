# Stage B — SAL on vs off (build years only)

Data firewall: every metric below is computed and filtered to
`OG_BUILD_YEARS = {2018, 2020, 2023, 2026}` only. No 2019/2021/2022/2024/2025
trade outcome was computed, displayed, or inspected to produce this document.

## What SAL is

In `src/strict_engine.py` (`run_strict`), SAL ("session-armed loss-lock") is a
same-session, forward-only trade-blocking state: once a trade closes with
`pnl < -0.1` and `exit_reason != "BE"`, SAL arms at that trade's exit
timestamp. Any further physical touch in the same 19:00->15:00 ET session at
or after the armed timestamp is skipped (`skip_reason == "SAL"`). SAL resets
at the next session's 19:00 ET start. It never arms retroactively and never
arms on a 0pt BE scratch.

## Implementation of the toggle

`src/og_build_variant_engine.py::run_variant(..., sal_enabled=bool)` — a
single boolean gate around the existing SAL-check block, structurally
identical to `strict_engine.run_strict`'s SAL logic when `sal_enabled=True`.
When `False`, the SAL-arming assignment is skipped entirely (the state is
simply never used to block trades); everything else (position exclusivity,
window, anchor, cutoff, gap-fill) is unchanged.

## Candidates tested

- `SAL_on` — canonical behavior (matches `configs/nq_current_config.yaml`).
- `SAL_off` — SAL disabled; a losing/negative-cutoff exit does not block
  further same-session touches.

All other parameters held at canonical defaults (BE-45, 200pt cap, canonical
11:00-15:00 blocked window, no HMM gate) for this controlled comparison.

## Build-year results

### Aggregate (2018+2020+2023+2026-partial)

| variant | n | net_pts | PF | win_rate | avg_trade | max_dd | TP | SL | BE | cutoff |
|---|---|---|---|---|---|---|---|---|---|---|
| SAL_on  | 460 | 3499.15 | 1.4191 | 0.387 | 7.607 | -756.99 | 165 | 128 | 125 | 42 |
| SAL_off | 507 | 4039.77 | 1.4533 | 0.389 | 7.968 | -721.54 | 180 | 135 | 141 | 51 |

### Per build year

| year | SAL_on net_pts | SAL_on PF | SAL_off net_pts | SAL_off PF |
|---|---|---|---|---|
| 2018 | 104.49 | 1.0771 | 240.24 | 1.1735 |
| 2020 | 747.27 | 1.2645 | 971.00 | 1.3106 |
| 2023 | **-96.16** | 0.9663 | 88.17 | 1.0294 |
| 2026 (partial) | 2743.56 | 3.0945 | 2740.36 | 2.9494 |

Positive build years: SAL_on = 3/4 (2023 negative); SAL_off = 4/4 (all
positive).

## Selection: **SAL OFF**

Rationale: on build-year evidence alone, disabling SAL strictly dominates —
higher aggregate net points (+540pts), higher aggregate PF (1.4533 vs
1.4191), a *smaller* max drawdown (-721.54 vs -756.99), more trades taken
(507 vs 460, i.e. SAL isn't needed to control tail risk here), and it flips
2023 from the only negative build year to marginally positive. SAL's
intended purpose — cutting further losses after a bad trade — does not pay
for itself in this 4-year build sample; the extra trades SAL would have
blocked are net additive. This is frozen as an empirical, build-year-only
decision, not a claim that SAL never helps (that question requires the
locked validation years, out of scope here).

Frozen: `sal_enabled = False` carried into Stage C.
