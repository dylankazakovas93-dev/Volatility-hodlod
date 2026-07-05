# Stage 1 Method -- Dynamic TP/SL Discovery

Research branch: `research/claude-stage1-tpsl-v1`

## Starting point (deviation from the requested spec, documented)

The spec named a starting branch/commit (`verification/codex-stage0-v1` @
`9408dae181fcd619068b417eb5c30c0dbb662537`) that does not exist anywhere in
this repository (verified: `git fetch` + `git cat-file -e` both fail). Per
the user's direction ("codex cannot push its results however it confirmed
everything you produced"), this branch is built from Claude's own verified
Stage 0 branch instead: `research/claude-stage0-excursions` @
`05fd1c83825943b960043c29c15f28adc0c4ed1a`. Section 5's required Stage 0
population numbers were re-verified to reproduce exactly on this branch
before any Stage 1 work began (see `docs/STAGE1_TPSL_REPORT.md` section 1).

## Data hash note (carried over from `verification/claude-baseline-v1`)

`data/nq_1m/nq_continuous_2018_2026_1m.csv` in this environment hashes to
`9f427eb0...`, not the frozen `3d0228fc...`. This was diagnosed at length in
the verification branch: every structural check (row count, span, per-
contract segment table, both engines' full trade-for-trade reproduction of
the committed baseline ledger) indicates identical content; the byte-hash
mismatch's root cause was not identified. Stage 1 proceeds on this same
file, since it is the only NQ bars file available in this environment and
its semantic equivalence to the frozen file was already established as
rigorously as this environment permits.

## Rebuilt trade management (sections 3-4, 9-13)

Everything from level generation through physical first touch is reused
verbatim (imported directly from `src.level_generation` /
`src.strict_engine`, not reimplemented) to guarantee it cannot silently
drift from the verified foundation. Everything after entry -- TP/SL
distance, first-passage resolution, position management -- is implemented
fresh in `scripts/stage1_engine.py`, with no BE/SAL/time-filter/cutoff
alternative of any kind.

### First-passage engine (`scripts/stage1_engine.py`)

- Entry bar: stop-only check (an entry-bar TP is never credited).
- Later bars: TP-only -> TP; SL-only -> SL; both on the same bar -> SL
  (unknowable ordering resolves conservatively).
- No resolution before forced liquidation -> exit at the liquidation bar's
  close.
- TP distance rounds up to the next 0.25-pt tick; SL distance rounds down;
  both floored at a 0.25-pt minimum.
- One global position; a touch while a position is open is permanently
  skipped (never retried).

### Why one replay per fold-agnostic simple candidate is valid

Every simple candidate is a **fixed** rule (scale, gamma, a, b chosen
before running anything). Its causal chronological replay over 2018-2025
does not depend on which years are later called "training" vs. "test" --
so each of the 980 candidates is replayed **once**, and outer walk-forward
selection is a matter of slicing that one ledger's per-year metrics by
fold. This is not true for the learned family (coefficients genuinely
differ per fold), so each of the 36 learned candidates is refit and
re-replayed once per outer fold (5 folds x 36 = 180 replays).

## Learned-formula fitting (section 13) -- documented simplification

`sklearn.linear_model.QuantileRegressor` has no built-in coefficient-sign
constraint (unlike a bounded linear-programming quantile-regression
formulation). Range/ATR coefficients are clipped to `>= 0` and the RVOL
coefficient to `[-0.30, 0.30]` **after** unconstrained fitting, not as an
in-loop constraint. This is a pragmatic approximation of the spec's
constrained-fitting requirement -- see `docs/STAGE1_KNOWN_LIMITATIONS.md`
for how often this clipping actually binds.

## Robust-neighborhood selection (section 16)

For each outer fold and each base scale, candidates are restricted to
those profitable in the fold's training years, then connected via
one-preregistered-step adjacency in exactly one of {gamma, a, b} (6-
directional graph on the index grid). Neighborhoods are ranked by
(training-period median PF, then size); the top neighborhood's **medoid**
(minimum total normalized grid distance to the rest of the neighborhood)
is the fold's frozen candidate, evaluated once on the fold's test year.
