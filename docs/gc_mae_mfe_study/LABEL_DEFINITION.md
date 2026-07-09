# MAE/MFE Label Definition — GC Level-Generator Study

## Which definition is used, stated once, not mixed

This study uses **Definition C: pre-declared-event excursion**, where the
declared event is the existing, frozen, already-in-repo
`session_cutoff(touched_at)` function (`src/strict_engine.py`) — the
15:00 ET (or next-session 15:00 ET, if the touch falls in the 19:00-24:00
reset window) prop-firm forced-flat boundary. This is **not** Definition A
(realized in-position MAE/MFE, censored by the strategy's own TP/SL/BE
exit) and **not** Definition B (an arbitrary fixed bar-count horizon).

**Why C and not A:** Definition A would train a model to predict the
strategy's *own exit system*, not the market's actual future excursion —
a level that gets stopped out at -1.0R and then reverses hard to +3R would
record MAE=1.0R, MFE=0 under Definition A, even though the market itself
offered a much larger favorable move after the stop. That's the exact
"model learns the exit system, not the market" failure mode this study is
required to avoid.

**Why C and not a generic fixed bar count (B):** the strategy's real
constraint isn't "N bars after entry," it's "flat by the prop-firm
deadline." Using `session_cutoff()` — a function that returns a fixed
clock time computed *only* from the entry timestamp, with no dependence on
price — keeps the horizon causal (fully determined at entry) while still
reflecting the real operational constraint requested ("exit at an
intraday stamp roughly 15:00 or 16:00").

## Population measured

**Every physical touch** (`src/strict_engine.py::physical_touches`), not
only the subset that would be *executed* by the strategy's
single-position/SAL/simultaneous-collision management layer. Rationale:
this study asks "is this level-generation parameterization placing levels
that the market moves through favorably," a question about the level
itself — position-management skips (SAL, position-already-open,
simultaneous-touch collision) are about capital allocation across
competing signals, not about whether any individual level was a good
price. Mixing them in would make the excursion metric partly a statement
about which trades a chronological single-position engine happened to be
free to take, not about level quality.

## Exact formula

For touch `i` with `touched_at = t`, `level = L`, `side in {upper, lower}`:

```
sign      = -1 if side == "upper" (short) else +1 if side == "lower" (long)
entry     = L                                   # the level price itself
anchor    = prev_completed_range(ranges, t)      # prior completed 60-min bar range, strictly prior
cap       = min(1.5 * anchor, SL_CAP)            # SL_CAP = 200.0, identical formula to the frozen engine
cutoff    = session_cutoff(t)                    # fixed clock-time boundary, no price dependence
path      = bars.loc[t : cutoff]                 # inclusive of touch bar and cutoff bar
path_high = max(path["high"])
path_low  = min(path["low"])

if sign > 0 (long):
    MFE_pts = max(0, path_high - entry)
    MAE_pts = max(0, entry - path_low)
else (short):
    MFE_pts = max(0, entry - path_low)
    MAE_pts = max(0, path_high - entry)

MAE_R = MAE_pts / cap
MFE_R = MFE_pts / cap
```

Both `MAE_pts`/`MFE_pts` and `MAE_R`/`MFE_R` are stored (points and R kept
separate, per the label contract). `cap` — the stop distance known at
entry — is the R denominator, never the trade's own realized risk (there
is no "realized risk" here since these are excursion labels, not executed
trades). Touches where `anchor` is unavailable (no completed prior 60-min
bar — can only happen right at data start) or `cutoff` is `None` are
dropped, not imputed.

## Sign and non-negativity guarantees

`MAE_pts`/`MFE_pts`/`MAE_R`/`MFE_R` are magnitudes, floored at 0 by
construction (`max(0, ...)`) — a level that never moves favorably (or
never moves adversely) records exactly 0 for that side, not a negative
number. There is no "BE trade" division/sign-error case in this study
specifically because these are touch-level excursion labels, not executed
trade P&L — there is no BE/TP/SL exit classification being labeled here at
all, only the raw path's high/low relative to the entry.

## Known limitations of this label, stated plainly

- `cutoff` can be many hours after `t` (up to the 15:00 ET boundary),
  so `MAE_R`/`MFE_R` are not "risk to reach 1R" style labels — they are
  "worst/best excursion the market offered before the prop-firm deadline,"
  which is a different (and larger-magnitude) quantity than either the
  strategy's actual realized MAE/MFE or a short fixed-bar-count MFE. This
  is intentional per the task's request to grade the level generator
  against the deadline-bound opportunity set, not the strategy's own
  1:1 TP/SL geometry.
- Because the horizon can span many hours, `MAE_R`/`MFE_R` for a touch
  very early in the session (e.g. an Asia-session touch) is measured over
  a much longer path than a touch just before the 15:00 cutoff itself —
  this asymmetry is real and not corrected for; time-of-day is carried as
  a feature specifically so the formula study can test whether it matters
  (see `FEATURE_PROVENANCE.csv`).
