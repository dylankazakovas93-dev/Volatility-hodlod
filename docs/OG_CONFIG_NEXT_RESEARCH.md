# OG_CONFIG_REPAIR_AND_ROBUSTNESS -- Next Research Plan (document-only)

Status of this document: **planning index only**. No optimization,
candidate evaluation, or code beyond documentation/indexing was performed
in the session that wrote this file. See `docs/OG_CONFIG_HISTORY.md`
section "Current-session restriction" equivalent below.

Canonical starting point for every experiment described here:

- Label: **`OG_CONFIG_CLEAN_BASELINE`**
- Status: **`OG_CONFIG_CLEAN_BASELINE__VALID_RESEARCH_STARTING_POINT`**
- Branch: `handoff/nq-strict-engine-v1`
- Commit: `a375818056ca435df021d60b111f5f58b1f3551f`
- Config: `configs/nq_current_config.yaml`
- Pointer file: `configs/OG_CONFIG_CLEAN_BASELINE.yaml`
- Live rules: `docs/OG_CONFIG_LIVE_RULES.md`
- Full lineage/hashes: `docs/OG_CONFIG_HISTORY.md`

The separate, already-completed, rejected line of research is labeled
**`GROUND_UP_F2_HMM_CONFIG__OOS_WEAK__REJECTED_FOR_DEPLOYMENT`**
(branch `research/claude-final-oos`) and must never be confused with the
above.

## Project name

**`OG_CONFIG_REPAIR_AND_ROBUSTNESS`**

## Objective

Determine whether the clean OG configuration can be improved for yearly
consistency and fixed-risk expectancy while preserving live-realistic
execution -- without ever describing a future result as untouched OOS,
fresh holdout, or independent forward validation. Every year in the
current dataset (2018-2026 partial) is retrospective development data for
this project; only genuinely new, not-yet-recorded live-forward data may
ever be called out-of-sample again.

## Mandatory execution safeguards (apply to every experiment below)

- Permanent physical first touch; creation-bar exclusion; expiry-bar
  exclusion; oldest-level-first simultaneous-touch ordering.
- One global position; no overlap; no stacking; no same-minute exit and
  re-entry; no retry after a consumed touch.
- TP and SL frozen at entry unless management is explicitly the thing
  being tested.
- Any management change takes effect no earlier than the following bar
  (except where reproducing the OG's own historical same-bar BE-45
  semantics as an explicit control -- see `docs/OG_CONFIG_LIVE_RULES.md`'s
  BE section for why that rule is same-bar by original design).
- Completed-bar information only; no smoothed HMM states (forward-filter
  only, never Viterbi/smoothed); no future HMM observations; no
  current-session data in HMM parameter fitting.
- Conservative resolution whenever TP/SL ordering on a single bar is
  unknowable (resolve to the more conservative outcome, matching the OG's
  own touch-bar stop-first convention).
- Deterministic reproducibility (identical inputs -> identical ledger
  hashes, every rerun).

Any candidate violating any of the above is invalid and must be discarded,
not reported as a passing result.

## Planned stage sequence

### Stage A -- exact baseline verification

Reproduce `OG_CONFIG_CLEAN_BASELINE` exactly before touching anything.
Required gates: matching ledger hash, matching headline metrics (the
historical reproduction target recorded in `docs/OG_CONFIG_HISTORY.md`
section 4), matching yearly metrics, no-overlap tests, no-lookahead tests,
and a complete touch/skip reconciliation (every physical touch accounted
for exactly once across executed + all skip reasons). Do not optimize
anything until this stage passes.

### Stage B -- SAL

Compare exactly two variants: the OG's exact historical SAL behavior
(control) vs. SAL off. Do not redesign SAL or create numerous SAL
variants -- this is a two-arm comparison, not a sweep.

### Stage C -- management

With SAL off, test a limited, preregistered set (fixed in advance, not
expanded after seeing results):
- exact historical OG management (BE-45, same-bar activation) as control;
- no BE at all;
- R-triggered BE (next-bar activation);
- late profit lock (next-bar activation);
- time-based BE;
- scratch-on-recovery.

Prefer broad, stable trigger regions over isolated optima -- a candidate
that only wins at one exact parameter value and collapses at its
neighbors is not preferred over a modestly-performing but stable region.

### Stage D -- HMM regimes

Test, separately and never mixed:
- causal two-state HMM;
- causal three-state HMM;
- individual states and excluding individual states;
- completed five-minute bar inputs only;
- rolling fits using strictly prior sessions (never current or future);
- filtered probabilities only (forward algorithm, never smoothed/Viterbi);
- state ordering by fitted volatility characteristic only, never by P&L.

Rolling-Python and frozen-Pine implementations are kept completely
separate at every step (same convention already established and verified
in the ground-up Stage 4/5/OOS work -- reuse that verified machinery,
don't redesign it).

### Stage E -- entry windows

Test a limited, preregistered family only:
- the exact OG window (19:00-11:00 ET);
- nearby wider and narrower contiguous windows;
- Asia / London / New York sessions;
- a limited set of non-contiguous session combinations.

Explicitly account for permanent first-touch consumption outside allowed
windows -- a touch that falls outside a narrower test window still
permanently consumes that level side (it is not "returned" to a wider
window later). Do not run arbitrary minute-level optimization -- the
window family must be fixed before any result is seen.

### Stage F -- limited combinations

Only combine components that pass independently in Stages B-E. Do not run
a large combinatorial search across all of SAL x management x HMM x
window.

## Selection priority (in order)

1. Number of individually positive years, in R.
2. Result excluding the best year.
3. Pooled total R.
4. Average R/trade.
5. Annual fixed-risk EV.
6. Drawdown.
7. Trade frequency.
8. PF.
9. Simplicity.

Do not select a candidate merely because it raises pooled PF -- a
candidate must be evaluated on the full ordered list above, and PF is
deliberately ranked last among the quantitative criteria.

## Required candidate reporting fields

For every candidate that reaches a report (not just the winner):
trades; net points; total R; average R/trade; PF (points); PF (R); maximum
drawdown (points and R); true TP-only win rate; every individual year;
result excluding the best year; result excluding the worst year; long and
short results; exit-reason counts; position-open skips; same-bar skips;
blocked-touch counts by reason; annual trade frequency; and
neighboring-parameter results (to demonstrate stability, not just a point
estimate). For every negative or weak OG year, explicitly show whether the
candidate improves it and what is sacrificed elsewhere in exchange -- never
show only the aggregate improvement.

## Probability work (gated)

Do not begin heavy probability analysis until a repaired OG configuration
is frozen. Once frozen, the probability stage may include: seasonal
monthly block resampling; session-block resampling; fixed-risk equity
paths; prop-account breach probabilities; payout probabilities; maximum-
drawdown distributions; loss-streak distributions; losing-year
probabilities; copied-account portfolio outcomes. IID individual-trade
shuffling must not be used as the primary simulation method (trades are
serially and seasonally correlated; block resampling preserves that
structure, IID shuffling destroys it).

## Required shorthand (for unambiguous future requests)

All shorthand below refers to `OG_CONFIG_CLEAN_BASELINE`
(branch `handoff/nq-strict-engine-v1`, commit `a375818`, config
`configs/nq_current_config.yaml`) unless the request explicitly says
otherwise:

- "Audit `OG_CONFIG_CLEAN_BASELINE`." -> run Stage A only.
- "Remove SAL from `OG_CONFIG_CLEAN_BASELINE`." -> run Stage B.
- "Optimize management on `OG_CONFIG_CLEAN_BASELINE`." -> run Stage C
  (requires Stage A passed, SAL setting from Stage B decision).
- "Test HMMs on `OG_CONFIG_CLEAN_BASELINE`." -> run Stage D.
- "Test time windows on `OG_CONFIG_CLEAN_BASELINE`." -> run Stage E.
- "Compare the repaired OG config with the rejected ground-up
  configuration." -> compare the Stage F output (once frozen) against
  `GROUND_UP_F2_HMM_CONFIG__OOS_WEAK__REJECTED_FOR_DEPLOYMENT`
  (`research/claude-final-oos`, commit `7e29fbad2437ccbf6f4e7783d07b20af073dc412`).
- "Run probabilities on the frozen repaired OG config." -> only valid
  after a Stage F candidate has been explicitly frozen by the user.

## Current-session restriction (this document's own scope)

The session that authored this document performed **only** documentation
and indexing of the OG baseline. No Stage A-F experiment, optimization, or
code beyond the four files listed at the top of `docs/OG_CONFIG_HISTORY.md`
was run. A fresh session must first independently reproduce
`OG_CONFIG_CLEAN_BASELINE` (Stage A) before changing anything -- this
handoff is written so that reproduction can happen with zero additional
context beyond these four documents.
