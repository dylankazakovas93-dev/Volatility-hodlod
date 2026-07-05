# Historical BE45 -- Exact Committed Semantics (from `src/strict_engine.py`)

Read directly from the verified handoff's `simulate_from_touch()` /
`simulate_cond_be()` (both identical in this respect), not inferred from
the name:

```python
BE_BARS = 45   # src/strict_engine.py

# bar indexing: i=0 is the FIRST bar strictly after the touch bar
# (the touch bar itself is handled separately, stop-only, before this loop)

armed = checked = False
for i in range(len(hi)):
    if i < be_bars:
        stop = orig_stop                       # unmodified original stop
    else:
        if not checked:                        # first time i >= 45
            checked = True
            o = float(op[i])                   # bar 45's OPEN price
            armed = (o >= entry) if sign > 0 else (o <= entry)
        stop = entry if armed else orig_stop
    # then check stop/target using THIS SAME bar i's high/low
    if <stop touched>:
        exit_reason = "BE" if (i >= be_bars and armed) else "SL"
    ...
```

Exact semantics, precisely:

1. **Checkpoint is bar index 45** (0-indexed, counting from the first bar
   after the touch bar -- i.e. the 46th post-touch bar, or equivalently
   the bar whose open is 45 minutes after the first post-touch bar's
   open).
2. **The arming decision is made exactly once**, at bar 45, using that
   bar's **open** price compared to entry: armed if the open is on the
   profitable side (`open >= entry` for a long, `open <= entry` for a
   short).
3. **If armed:** the stop becomes `entry` starting **at bar 45 itself**
   (same-bar activation -- bar 45's own low/high is checked against the
   new `entry` stop immediately, in the same iteration that decided to
   arm it). **This is same-bar, not next-bar, activation** -- a real,
   deliberate difference from every other Stage 3 candidate family, which
   uses next-bar activation per the current spec's causality rule. This
   difference is reproduced faithfully here, not silently corrected.
4. **If not armed:** the original stop remains for the rest of the trade;
   there is no second chance -- the check happens exactly once, ever.
5. **Target (TP) is never affected** by BE -- it stays at the original
   distance throughout.
6. **Exit-reason labeling:** an exit via the stop is labeled `"BE"` only if
   `i >= 45 AND armed`; otherwise (whether `i < 45`, or `i >= 45` but not
   armed) it is labeled `"SL"` even though the stop price itself may be
   `entry` in the armed-but-still-a-loss-relative-to-nothing case (BE
   exits are actually flat/breakeven in points, not losses -- the "SL"
   label only applies to the *unarmed* branch where the original stop is
   still in force).
7. Bars before the touch bar's own stop-only check are unaffected;
   BE never applies retroactively to the touch bar itself.

## Stage 3 application

Reproduced verbatim as `stage3_engine.simulate_be45()`, applied on top of
Stage 3's own frozen inputs (E-F entry window, gross P&L, the fitted F2
`tp_dist`/`sl_dist` per trade -- **not** the old symmetric
`min(1.5×anchor, 200)` cap, which is explicitly retired and out of scope
here; only the BE *triggering and activation mechanism* is being
reproduced, per instructions, not the old distance formula).
