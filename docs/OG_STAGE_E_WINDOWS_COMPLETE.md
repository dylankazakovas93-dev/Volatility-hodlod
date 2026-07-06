# Stage E — Entry-Blackout / Session-Entry Study (COMPLETE)

Status: COMPLETE. **Supersedes `docs/OG_STAGE_E_WINDOWS.md`**, which used an
insufficient two-sided "blocked window" framing and did not test session-entry
variants or run a window-perturbation robustness check. This document is the
authoritative Stage E result going forward.

## Scope and held-constant parameters

Build years only: **{2018 (full), 2020 (full), 2023 (full), 2026 (partial)}**.
No metric below includes 2019/2021/2022/2024/2025 trade outcomes. No
`OG_PRE_VALIDATION_LOCK` is used.

Held constant across every candidate:
- SAL off (Stage B freeze).
- **BE60 management** (Stage C final, `docs/OG_STAGE_C_MANAGEMENT_COMPLETE.md`):
  `mode="barcount", be_bars=60`, simulated via
  `src/og_management_variants.py::run_variant_managed` /
  `simulate_managed` directly (not reimplemented in this stage's runner,
  `scripts/og_stage_e_windows_complete.py`).
- No HMM gate (Stage D freeze) -- except that the session-entry candidates
  below reuse the `hmm_gate` *hook* (a plain `callable(ts) -> bool`) purely as
  a session-membership filter; no HMM model is involved in those runs.
- Target fixed at 1.0R (`cap = min(1.5*anchor, SL_CAP)`, unchanged).
- Forced liquidation 15:00 ET (`session_cutoff()`, unchanged).
- `PROP_HARD_BLACKOUT` (16:00-19:00 ET) always on, unconditional, checked
  inside `run_variant_managed` itself and independently re-verified below
  against every candidate's actual trade output.

## Terminology

The variable under test is a **BLOCKED ENTRY INTERVAL**: entries are blocked
from a start time until a cutoff. It is never described as an "allowed
trading window" -- see `docs/OG_STAGE_E_WINDOWS.md`'s terminology note, which
still applies. For the primary candidates the cutoff is always the 15:00 ET
forced-liquidation time; a redundant "until 16:00" label is tested alongside
each start to demonstrate numerically that the extra hour is a no-op (see
below).

## Session definitions

Checked `docs/OG_STAGE_E_WINDOWS.md`, `docs/OG_PROP_HARD_BLACKOUT.md`, and
`docs/OG_CONFIG_LIVE_RULES.md` -- none define Asia/London/New-York session
boundaries. The following are therefore defined for this stage only, per the
task spec, all in ET:

| Session | Interval (ET) |
|---|---|
| Asia | 19:00-03:00 (wraps midnight) |
| London | 03:00-08:00 |
| New York | 08:00-16:00 |
| NY-pre-10:00 | 08:00-10:00 (subset of New York) |

## Primary candidates: blocked-until-15:00 (7 starts) + redundant until-16:00 labels (7 starts)

Full-year (`ALL`) and ex-2026 (`ALL_ex2026`) results:

| Candidate (blocked from -> 15:00) | n (ALL) | net_pts (ALL) | PF (ALL) | n (ex2026) | net_pts (ex2026) | PF (ex2026) | win_rate (ex2026) | payoff (ex2026) |
|---|---|---|---|---|---|---|---|---|
| 09:00 | 308 | 3728.16 | 1.8334 | 263 | 1296.66 | 1.3463 | 0.3802 | 1.131 |
| 09:30 | 319 | 4200.52 | 1.8968 | 272 | 1644.04 | 1.4194 | 0.3897 | 1.165 |
| **10:00** | **400** | **5011.09** | **1.7852** | **343** | **2307.78** | **1.4397** | **0.4111** | **1.215** |
| 10:30 | 460 | 3866.08 | 1.4362 | 395 | 1184.14 | 1.1620 | 0.3924 | 1.095 |
| 11:00 (canonical) | 500 | 4372.34 | 1.4548 | 427 | 1504.48 | 1.1891 | 0.3888 | 1.139 |
| 11:30 | 532 | 4205.31 | 1.4031 | 456 | 1721.06 | 1.2055 | 0.3794 | 1.185 |
| 12:00 | 566 | 4492.76 | 1.4002 | 488 | 2008.51 | 1.2239 | 0.3791 | 1.211 |

**Redundant "blocked-until-16:00" verification**: for all 7 starts, the
until-16:00 candidate was run and its executed-trades dataframe compared
row-for-row (level_id, session_date, side, entry/exit time, entry/exit price,
exit_reason, pnl) against its until-15:00 counterpart. **All 7 pairs are
numerically identical** (`n_1500 == n_1600` and full row equality in every
case), confirming that stating a 16:00 blackout end is a no-op given the
frozen 15:00 ET forced-liquidation cutoff: no position can still be open, and
no new entry can occur, between 15:00 and 16:00 regardless of the stated
label. Raw dedup report: `outputs/og_build_years/stage_e_window_complete_raw.json`
(`_dedup_report` key).

Per-year net_pts for the winning 10:00 candidate (all 4 build years
positive):

| Year | n | net_pts | PF | win_rate | max_dd_pts | max_dd_R |
|---|---|---|---|---|---|---|
| 2018 | 112 | 285.80 | 1.3439 | 0.3929 | -139.08 | -5.6963 |
| 2020 | 131 | 1478.90 | 1.5635 | 0.4046 | -563.16 | -9.5677 |
| 2023 | 100 | 543.09 | 1.3030 | 0.4400 | -378.11 | -3.7536 |
| 2026 (partial) | 57 | 2703.30 | 3.3838 | 0.5965 | -402.75 | -5.0000 |

Additional metrics for 10:00 (ALL / ALL_ex2026): avg_pts_per_trade 12.528 /
6.728; cap_norm_R_total 44.9583 / 24.6381; cap_norm_R_avg 0.1124 / 0.0718;
avg_winner_pts 65.103 / 53.587; avg_loser_pts -48.349 / -44.101; exit counts
(ALL) TP 168 / SL 122 / BE 93 / cutoff 17; hold-time (ALL) median 79.0 min,
mean 158.4 min, p25 48.8, p75 210.2. Full per-candidate detail (every
metric requested: trades, net points, PF, avg points/trade, cap-normalized
total/avg R, max drawdown points and R, win rate, avg winner/loser, payoff
ratio, TP/SL/BE/cutoff counts, yearly breakdown, ex-2026, ex-best-year, trade
frequency, hold-time median/mean/p25/p75) is in
`outputs/og_build_years/stage_e_window_complete.csv`.

## Session-entry variants (7 candidates)

| Candidate | n (ALL) | net_pts (ALL) | PF (ALL) | n (ex2026) | net_pts (ex2026) | PF (ex2026) | win_rate (ex2026) |
|---|---|---|---|---|---|---|---|
| asia_only | 159 | 1836.44 | 1.7322 | 132 | 600.45 | 1.3007 | 0.4015 |
| london_only | 116 | 1391.72 | 1.9184 | 105 | 527.84 | 1.3866 | 0.3429 |
| ny_pre10_only | 139 | 1756.68 | 1.6828 | 120 | 1153.25 | 1.5492 | 0.4833 |
| asia_or_london | 266 | 3350.78 | 1.8722 | 228 | 1250.91 | 1.3933 | 0.3816 |
| asia_or_ny_pre10 | 297 | 3576.62 | 1.7040 | 251 | 1737.19 | 1.4240 | 0.4382 |
| london_or_ny_pre10 | 251 | 3068.52 | 1.7566 | 221 | 1601.21 | 1.4664 | 0.4118 |
| all_canonical_permitted_hours (control) | 500 | 4372.34 | 1.4548 | 427 | 1504.48 | 1.1891 | 0.3888 |

The `all_canonical_permitted_hours` control was implemented as a
session-style gate (allow everything except 11:00-15:00) and cross-checked
row-for-row against the primary `blocked_1100_until1500` candidate:
**identical** (confirmed in the runner output and
`_control_vs_canonical_identical: true` in the raw JSON), as required since
they express the same rule two different ways.

None of the session-entry variants beats the best blocked-interval candidate
(10:00) on ex-2026 PF; `ny_pre10_only` has the best single-session PF (1.5492)
but on materially fewer trades (120 ex-2026) and 2018 is worth checking
individually (see CSV) before treating it as a real alternative -- it was not
selected because it does not exceed the blocked-interval winner and the task
scope treats the blocked-interval family as primary.

## Selection

**Selected provisional blackout start: 10:00** (blocked-until-15:00),
chosen by the stated standard:
- Highest full-year-ex-2026 PF among the 7 blocked-interval candidates
  (1.4397, versus 1.1620-1.2239 for 10:30 through 12:00 and 1.3463-1.4194 for
  09:00/09:30).
- All 4 build years individually net-positive (2018/2020/2023/2026), not just
  3 of 4.
- Not an isolated cliff-edge: 09:00 and 09:30 are directionally similar/lower
  (PF 1.3463, 1.4194) rather than collapsed, and 10:30 is a real drop-off
  (1.1620) but still profitable -- so 10:00 sits at a local peak flanked by
  profitable, gradually-declining neighbors rather than surrounded by
  collapse.

## Window perturbation: start-60 / start-30 / start / start+30 / start+60

Around the selected 10:00 start (in minutes: 540/570/600/630/660), all
blocked-until-15:00:

| Perturbation | Start (ET) | n (ex2026) | net_pts (ex2026) | PF (ex2026) | win_rate (ex2026) | 2018 net | 2020 net | 2023 net | 2026 net |
|---|---|---|---|---|---|---|---|---|---|
| start-60 | 09:00 | 263 | 1296.66 | 1.3463 | 0.3802 | 165.38 | 843.29 | 288.00 | 2431.50 |
| start-30 | 09:30 | 272 | 1644.04 | 1.4194 | 0.3897 | 244.12 | 1089.41 | 310.51 | 2556.48 |
| **start** | **10:00** | **343** | **2307.78** | **1.4397** | **0.4111** | **285.80** | **1478.90** | **543.09** | **2703.30** |
| start+30 | 10:30 | 395 | 1184.14 | 1.1620 | 0.3924 | 63.61 | 937.25 | 183.27 | 2681.94 |
| start+60 | 11:00 | 427 | 1504.48 | 1.1891 | 0.3888 | 103.61 | 1301.84 | 99.04 | 2867.86 |

**Perturbation verdict: survives, with a disclosed asymmetry.** Every one of
the five settings keeps **all 4 build years individually positive** and
full-year-ex-2026 PF comfortably above 1.0 (range 1.1620-1.4397) with usable
trade frequency (263-427 trades ex-2026, ~88-142/year). Performance changes
gradually moving left (09:00 -> 09:30 -> 10:00 is a smooth, monotonic
improvement in PF and net_pts); moving right there is a real but bounded
step down at +30 (PF 1.4397 -> 1.1620) rather than a collapse, and it
partially recovers at +60. This is analogous to the disclosed BE60
neighborhood asymmetry in Stage C (stable on one side, a real but
non-catastrophic step on the other) and is flagged explicitly rather than
smoothed over. No adjacent setting becomes unprofitable and no drawdown
discontinuity or trade-frequency collapse occurs at any of the five points.

## Final Stage E decision

**`RESEARCH_ENTRY_BLACKOUT_10_15`: entries blocked from 10:00 ET until the
15:00 ET forced-liquidation cutoff.** This supersedes the prior
`RESEARCH_ENTRY_BLACKOUT_10_16` label from `docs/OG_STAGE_E_WINDOWS.md`: the
"until 16:00" framing is retired because it was shown here (and is implied by
the earlier doc's own note) to be a numerically redundant restatement of
"until 15:00" -- the two are identical trade-for-trade given the frozen 15:00
ET liquidation cutoff. The new canonical name states the true, non-redundant
interval directly: 10:00 through 15:00 ET, i.e. `blocked_window=(10*60,
15*60)` in `entry_allowed_window()` / `run_variant_managed`.

Frozen going forward: `blocked_window=(600, 900)` (10:00-15:00 ET blocked
entry interval), BE60 management (Stage C), no HMM (Stage D), SAL off
(Stage B), target 1.0R, forced liquidation 15:00 ET, `PROP_HARD_BLACKOUT`
unconditional.

## Hard-blackout re-verification

Extended `tests/test_prop_hard_blackout.py` with
`test_stage_e_candidate_trade_outputs_never_enter_hard_blackout`, which reads
every actual Stage-E-complete executed-trade CSV on disk (all blocked-interval
candidates, their until-16:00 pairs, all session-entry candidates, and all 5
perturbation candidates -- 33 files) and asserts no entry or exit timestamp
falls in [16:00, 19:00) ET. **Result: PASS** (`python -m pytest
tests/test_prop_hard_blackout.py -q` -> 10 passed, up from 9). This is in
addition to the unconditional in-engine assertions inside
`run_variant_managed` itself, which also passed (no `AssertionError` was
raised) during every one of the 33 candidate runs performed for this stage.

## Reproduction

`python3 scripts/og_stage_e_windows_complete.py` (requires
`outputs/og_build_years/_cache.pkl`, produced by the existing Stage
B/C/D pipeline). Outputs:
`outputs/og_build_years/stage_e_window_complete.csv` (full per-candidate,
per-year metric table for all primary + session + perturbation candidates),
`outputs/og_build_years/stage_e_window_complete_raw.json` (raw summaries,
dedup report, control cross-check, selection rationale),
`outputs/og_build_years/stage_e_window_perturbation.csv` /
`_raw.json` (perturbation detail), and per-candidate build-year trade
ledgers `outputs/og_build_years/stage_e_complete_<candidate>_build_years_trades.csv`.
