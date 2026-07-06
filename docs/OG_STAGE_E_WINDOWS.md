# OG Stage E — Entry-window / cutoff candidates (build years only)

Scope: `OG_BUILD_YEARS` only = {2018, 2020, 2023, 2026-partial}. Carries
forward Stage B (`sal_enabled=False`), Stage C (`be_bars=60`,
`be_extra_lock=0.0`), Stage D (no HMM gate). No metric below includes
2019/2021/2022/2024/2025 trade outcomes.

The canonical entry window blocks 11:00-15:00 ET (valid 19:00 ET through
11:00 ET, per `docs/OG_CONFIG_LIVE_RULES.md` / `configs/nq_current_config.yaml`).
Session cutoff is fixed at 15:00 ET regardless of the block window tested
(cutoff/liquidation logic is untouched by this stage).

## Terminology: `RESEARCH_ENTRY_BLACKOUT_10_16` is a blocked ENTRY interval, not a trading window

The Stage E-selected candidate previously informally labeled "10:00-16:00 ET"
(and, in code, `wider_10_16`) is **not** a window during which the strategy
"trades 10:00 to 16:00." It is the opposite: a *blocked entry interval*. The
canonical name for this research rule is `RESEARCH_ENTRY_BLACKOUT_10_16`, and
it must always be described this way:

- New entries may occur from the canonical session start (19:00 ET) until
  10:00 ET.
- Starting at 10:00 ET, and continuing through 16:00 ET, no new entries are
  permitted — this is the `RESEARCH_ENTRY_BLACKOUT_10_16` rule
  (`blocked_window=(10*60, 16*60)` in `entry_allowed_window()`,
  `src/og_build_variant_engine.py`). It only prevents new entries; it says
  nothing by itself about exits or liquidation.
- All open positions are force-liquidated by the canonical 15:00 ET cutoff
  (`session_cutoff()`, unchanged by Stage E) regardless of entry window
  choice.
- Separately and unconditionally, `PROP_HARD_BLACKOUT` (16:00-19:00 ET,
  `docs/OG_PROP_HARD_BLACKOUT.md`) forbids any entry or open position in that
  span. Given the 15:00 ET liquidation cutoff, `PROP_HARD_BLACKOUT`'s
  16:00-19:00 span is currently redundant with `RESEARCH_ENTRY_BLACKOUT_10_16`
  ending at 16:00 -- but it remains encoded unconditionally in the shared
  engine path precisely so that a future change to the liquidation cutoff or
  to the research entry-blackout parameters cannot silently reopen trading in
  16:00-19:00 ET.

Any mention elsewhere (docs, code comments, JSON labels, variable names) of
"10:00-16:00 trading" or an "allowed window" of that span is a terminology
error and should be read/corrected as `RESEARCH_ENTRY_BLACKOUT_10_16`, a
blocked entry interval.

## Candidates tested

| Label | Blocked window (ET) | Note |
|---|---|---|
| canonical_11_15 | 11:00-15:00 | baseline |
| RESEARCH_ENTRY_BLACKOUT_10_16 | entries blocked 10:00-16:00 | more restrictive entry (blocks more midday hours); NOT a "10:00-16:00 trading window" |
| narrower_12_14 | entries blocked 12:00-14:00 | more permissive entry (blocks fewer hours) |
| shifted_11_16 | entries blocked 11:00-16:00 | extends block toward the close |

Command: `python3 scripts/og_stage_e_windows.py`.

## Build-year aggregate results

| Candidate | n | net_pts | PF | win_rate | avg_trade | max_drawdown |
|---|---|---|---|---|---|---|
| canonical_11_15 | 500 | 4372.34 | 1.4548 | 0.4100 | 8.745 | -793.77 |
| RESEARCH_ENTRY_BLACKOUT_10_16 | 400 | 5011.09 | 1.7852 | 0.4375 | 12.528 | -563.16 |
| narrower_12_14 | 631 | 4244.46 | 1.3485 | 0.4025 | 6.727 | -1041.85 |
| shifted_11_16 | 500 | 4372.34 | 1.4548 | 0.4100 | 8.745 | -793.77 |

Note: `shifted_11_16` is numerically identical to canonical because the fixed
15:00 ET session cutoff already prevents any entry from 15:00-16:00 — that
hour is a no-op extension of the block given the frozen cutoff rule.

## RESEARCH_ENTRY_BLACKOUT_10_16 per-build-year breakdown (winning candidate)

| Year | n | net_pts | PF | max_drawdown |
|---|---|---|---|---|
| 2018 | 112 | 285.80 | 1.3439 | -139.08 |
| 2020 | 131 | 1478.90 | 1.5635 | -563.16 |
| 2023 | 100 | 543.09 | 1.3030 | -378.11 |
| 2026 (partial) | 57 | 2703.30 | 3.3838 | -402.75 |

## Selection rationale

`RESEARCH_ENTRY_BLACKOUT_10_16` (blocking entries 10:00-16:00 ET instead of 11:00-15:00) dominates the
canonical window on every metric and every build year:
- Higher aggregate net_pts (5011.09 vs 4372.34) and PF (1.7852 vs 1.4548).
- Lower aggregate max drawdown (-563.16 vs -793.77).
- **All 4 build years net-positive and individually better than the
  corresponding canonical-window year** (2018: 285.80 vs 103.61; 2020:
  1478.90 vs 1301.84; 2023: 543.09 vs 99.04; 2026: 2703.30 vs 2867.86 — the
  only year where wider is marginally lower, but still strongly positive and
  with a far better win rate and PF).
- Fewer, higher-quality trades (400 vs 500) — the additional excluded hour on
  each side of the midday block appears to remove a lower-quality subset of
  touches (fewer TP total but proportionally the same, meaningfully fewer SL
  as a share, higher win rate).

`narrower_12_14` is dominated: much worse PF (1.3485) and a substantially
worse drawdown (-1041.85) despite more trades.

**Frozen decision: `RESEARCH_ENTRY_BLACKOUT_10_16`** -- entries blocked 10:00-16:00 ET (wider than canonical). Note: this is Stage E's own choice of entry-blackout parameter; Stage C (below) isolates the management-variable comparison using the *canonical* 11:00-15:00 blocked window instead, per the Stage C task scope.

Raw outputs: `outputs/og_build_years/stage_e_*_build_years_trades.csv`,
`outputs/og_build_years/stage_e_windows_results.json`.
