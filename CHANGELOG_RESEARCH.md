# Research Changelog — NQ Strategy Claims

Status legend: **CURRENT** (stands), **RETRACTED** (superseded, do not use
for deployable execution), **FAILED REPRODUCTION** (could not be rebuilt
from source in this repo), **VALIDATION PENDING** (not yet checked here).

| Claim | PF | Net (pts) | Trades | Status | Notes |
|---|---|---|---|---|---|
| `nq_cond_be45.py` + SAL (frozen fingerprint, `verify_canonical.py`) | 1.678 | +15,664.99 | 1,256 | **RETRACTED** for deployable execution | Real, reproducible from source (gate 1,841 -> 1,256 post-SAL) but positions can overlap; SAL is entry-blocking only, not causally time-aware of exit timestamps. Still valid as the candidate-population generator. |
| "Genuinely single-position, time-aware-SAL" claim, PF ~1.2-1.4, net ~+3,918, 3,093 trades | 1.227 | +3,918.27 | 3,093 | **FAILED REPRODUCTION** | Could not be rebuilt against the canonical 1,841-candidate gate in this repo. Trade count (3,093) exceeds what the `LINE_DAYS`-bounded touch architecture can produce (max ~4,338 level-sides exist at all; only 1,841 pass the static gates). Most likely built without `volgen.reactions._first_touch` / `LINE_DAYS` expiry, allowing effective re-touch of the same level across sessions. |
| Strict one-position, time-aware-SAL, PRIMARY conservative (this changelog entry) | 1.2924 | +6,648.17 | 1,107 | **CURRENT** | See `docs/NQ_STRICT_RECONCILIATION.md`. Built from the 1,841-candidate gate, chronological single-global-position state machine, six edge cases resolved conservatively with individually-reported sensitivities (PF range across all sensitivities: 1.28-1.33; net range +6,421 to +7,291). Negative years: 2019, 2023, 2024. |

## Entry: strict reconciliation committed

- Rebuilt the 1,841 candidate gate from source and confirmed exact match.
- Diagnosed and documented why the SAL-only engine (1.678 PF) overstates
  performance: no global single-position constraint.
- Attempted to recover the previously-claimed "single-position" PF 1.2-1.4
  result; could not reproduce it from the files present in this repo — the
  trade count it reported (3,093) is structurally inconsistent with the
  1,841-candidate ceiling. Marked FAILED REPRODUCTION rather than assumed
  correct.
- Built `scripts/reconcile_strict_one_position.py`: a from-scratch, causally
  correct single-position / time-aware-SAL state machine with six explicit
  edge-case resolutions (creation-bar touches, touch-bar TP/SL ordering,
  gap-through fills, same-bar exit/re-entry, simultaneous touches, expiry
  timestamp inclusion), each with its own individually-reported sensitivity
  run so no single design choice is silently baked into the headline number.
- Final, fully conservative result: **PF 1.2924, net +6,648.17 pts, 1,107
  trades, 2018-2026**. Strategy remains net profitable overall and under
  every sensitivity tested, but three of nine years (2019, 2023, 2024) are
  negative and 2018 is marginal.
- ES companion research remains blocked pending this commit, per the task
  instructions.

## Entry: cleanup pass — exit_price fix, cost-adjusted table, canonical config, invariant tests, cross-model protocol

- Fixed a hardcoded `if False` that left `exit_price` blank on every executed
  row. Now populated (`entry_price + sign*pnl`) for TP/SL/BE/cutoff alike.
  This changed `outputs/nq_strict_executed.csv` and `outputs/nq_strict_skipped.csv`
  hashes; PnL/net/PF numbers are unchanged (bookkeeping-only fix).
- Added round-trip cost-adjusted net/PF/maxDD at 0.0/0.5/1.0/2.0 pts, applied
  to every executed trade including BE and cutoff. Strategy stays net
  profitable through 2.0 pts round-trip; PF compresses from 1.2924 to 1.1839.
- Relabeled the gap-through fill policy as a deterministic realistic-fill
  assumption, not a worst-case one (it improves PnL by +146.6 pts vs
  assuming level-fill on the 8 gap-through trades in the dataset).
- Fixed the source-code-commit / output-commit conflation: the summary JSON
  now records `source_code_commit` (the commit containing the exact script
  version that ran) separately from the later commit that adds the
  generated output files.
- Froze canonical semantics in `configs/nq_canonical_strict.yaml`.
- Added `tests/test_nq_strict_invariants.py` — 18 machine-verifiable
  invariants (data hashes, eligible-candidate gate, headline numbers within
  tolerance, no-overlap, no-same-bar-reentry, no-blocked-time-entry, SAL
  causality, skip-category reconciliation, annual-sum reconciliation, PF
  includes cutoff). All 18 currently pass.
- Added `docs/CROSS_MODEL_RECONCILIATION_PROTOCOL.md` and
  `scripts/compare_strict_ledgers.py` so Claude 2 and Codex can verify this
  package by hash and by row-level ledger diff rather than by trusting a
  summary number.
- Regenerated result, confirmed unchanged from the prior commit:
  **executed=1107, net=+6648.17, PF=1.2924**, negative years
  [2019, 2023, 2024] — unaffected by the cleanup, as expected since no
  simulation logic changed.
