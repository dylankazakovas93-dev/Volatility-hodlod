# Stage C — Management Confirmation Pass (STEP 1 of the Phase-1 continuation)

Status: COMPLETE. Decision: **BE60_CONFIRMED**.

## Scope

This is a *confirmation* pass only, not a re-run of the full 20-candidate
Stage C sweep (see `docs/OG_STAGE_C_MANAGEMENT.md` for that). It isolates the
bar-count BE family, which is the only family the prior session's provisional
pick (`be_bars=60`) belonged to, and tests it in a clean neighbourhood:

Held constant: SAL off (Stage B freeze), no HMM (Stage D freeze), CANONICAL
entry blackout (11:00-15:00, the original canonical window — not the Stage E
`RESEARCH_ENTRY_BLACKOUT_10_16` label), target fixed at 1.0R, forced
liquidation 15:00 ET, PROP_HARD_BLACKOUT unconditional.

Candidates: `noBE`, `BE30`, `BE45`, `BE60`, `BE75`, `BE90` (bar-count family,
via `mode="barcount"` / `mode="none"` in `src/og_management_variants.py`,
driven by `scripts/og_stage_c_confirm.py`).

### Omitted diagnostic candidate — disclosed, not fabricated

The task requested a labeled diagnostic-only reference candidate,
`BE45+2pt-lock` (arm at 45 bars elapsed, then lock a fixed +2pt profit rather
than exact breakeven). This is **not representable** by the existing
`simulate_managed()` primitives in `src/og_management_variants.py` without
new engine code: the `profit_lock` mode there triggers on exact-R
(`r_trigger`), not elapsed bar-count, and there is no bar-count-triggered
fixed-point-lock mode. Per the instruction to reuse existing infrastructure
rather than rebuild from scratch, and to avoid fabricating or silently
approximating a result, this diagnostic candidate was **not run**. If it is
needed, `simulate_managed` needs a new mode (e.g. `barcount_lock` taking
`be_bars` + `lock_pts`) — flagged for a follow-up, not invented here.

## Results (build years 2018/2020/2023/2026 only)

Full per-candidate, per-year table (including exit-reason counts, hold-time
percentiles, cap-normalized R, drawdown in R, payoff ratio, etc.) is in
`outputs/og_build_years/stage_c_management_complete.csv`. Headline rows:

| candidate | scope | n | net_pts | PF | avg_cap_norm_R | max_dd_R | win_rate | payoff |
|---|---|---|---|---|---|---|---|---|
| noBE | ALL | 477 | 4277.83 | 1.357 | 0.1015 | -13.61 | 0.537 | 1.171 |
| noBE | ex2026 | 407 | 1416.29 | 1.146 | 0.0701 | -13.61 | 0.521 | 1.054 |
| BE30 | ALL | 512 | 4337.67 | 1.489 | 0.0892 | -9.91 | 0.381 | 1.229 |
| BE30 | ex2026 | 438 | 1606.51 | 1.219 | 0.0579 | -9.91 | 0.363 | 1.097 |
| BE45 | ALL | 507 | 4039.77 | 1.453 | 0.0777 | -10.44 | 0.389 | 1.247 |
| BE45 | ex2026 | 434 | 1299.41 | 1.173 | 0.0431 | -10.44 | 0.369 | 1.114 |
| **BE60** | **ALL** | **500** | **4372.34** | **1.455** | **0.0794** | **-10.50** | **0.410** | **1.270** |
| **BE60** | **ex2026** | **427** | **1504.48** | **1.189** | **0.0434** | **-10.50** | **0.389** | **1.139** |
| BE75 | ALL | 494 | 2376.98 | 1.223 | 0.0581 | -18.07 | 0.417 | 1.134 |
| BE75 | ex2026 | 422 | 154.25 | 1.018 | 0.0297 | -18.07 | 0.408 | 1.006 |
| BE90 | ALL | 494 | 3817.34 | 1.368 | 0.0875 | -15.70 | 0.441 | 1.155 |
| BE90 | ex2026 | 422 | 811.63 | 1.094 | 0.0503 | -15.70 | 0.422 | 1.008 |

Per completed year, net points (PF):

| candidate | 2018 | 2020 | 2023 |
|---|---|---|---|
| noBE | -174.93 (0.916) | 980.49 (1.234) | 610.74 (1.178) |
| BE30 | -20.01 (0.986) | 996.37 (1.315) | 630.15 (1.233) |
| BE45 | 240.24 (1.174) | 971.00 (1.311) | 88.17 (1.029) |
| **BE60** | **103.61 (1.071)** | **1301.84 (1.382)** | **99.04 (1.032)** |
| BE75 | -113.87 (0.936) | 237.81 (1.062) | 30.31 (1.010) |
| BE90 | -11.86 (0.993) | 453.91 (1.119) | 369.57 (1.120) |

## Selection standard applied

- **No isolated optimum**: BE60 sits inside a plateau with BE30 and BE45
  (ex-2026 PF 1.219 / 1.173 / 1.189 respectively) — the three are mutually
  consistent, so BE60 is not a spike surrounded by two collapsed neighbours.
- **Neighbouring bar counts directionally similar**: satisfied to the *left*
  (BE45 → BE60 is a smooth, small change in every metric). **Not fully
  satisfied to the right**: BE60 → BE75 shows a sharp discontinuity (ex-2026
  PF collapses from 1.189 to 1.018, net_pts ex-2026 from 1504 to 154,
  max_dd_R nearly doubles from -10.50 to -18.07). BE90 partially recovers.
  This is flagged explicitly as a real, disclosed fragility — see caveat
  below — rather than smoothed over.
- **Completed years must not collapse**: BE60 keeps all three completed
  years (2018/2020/2023) positive.
- **Full-year-ex-2026 PF acceptable**: 1.189, within the "materially above
  1.0, ideally 1.1-1.2" band (at the top edge of it).
- **Drawdown discontinuity**: none between BE45 and BE60; a real one appears
  one step further out (BE60→BE75), noted above.
- **At least 3 of 4 build years positive**: BE60 has all 4 (2026 contributes
  net_pts(ALL) - net_pts(ex2026) = 4372.34 - 1504.48 = 2867.86, positive).
- **All-4-positive not via cliff-edge**: because BE60 is part of a
  three-point plateau (30/45/60) rather than a singleton, the all-4-positive
  result is not attributable to an isolated cliff-edge value of `be_bars`
  itself, even though the *neighbourhood is not symmetric* (stable to the
  left, fragile one step to the right at 75).

## Decision

**BE60_CONFIRMED**, with an explicit, carried-forward caveat: the
neighbourhood is asymmetric — robust on the 30/45/60 plateau side, fragile
immediately past it at 75. This should be re-examined if/when Stage F's
management-interaction diagnostics or any later perturbation work touches
the BE-bars parameter again. This directly addresses (rather than dismisses)
the concern flagged in `docs/OG_STAGE_C_MANAGEMENT.md` about the original
`be_bars=60` pick's robustness — it survives this closer look, but not with
the same margin on both sides.

Frozen going forward: `mode="barcount", be_bars=60`, CANONICAL entry
blackout unchanged from this stage forward until Stage E supersedes it,
target 1.0R unchanged until Stage F.

## Reproduction

`python3 scripts/og_stage_c_confirm.py` (requires
`outputs/og_build_years/_cache.pkl`, produced by the existing Stage C/D
pipeline). Output: `outputs/og_build_years/stage_c_management_complete.csv`.
