# Strategy Rules — Frozen Current Configuration

This describes the one strategy this handoff verifies. No alternative
configuration, parameter, or rule is described anywhere in this document.

## Level generation

- Instrument: NQ (Nasdaq-100 E-mini futures)
- RTH level-building window: 09:30-16:00 ET
- Cash open: first RTH bar's open
- Initial Balance (IB) duration: 60 minutes
- **The IB-completion bar is included** in the IB high/low range (not
  excluded) — verified by `tests/test_strategy_invariants.py::test_ib_cutoff_bar_is_included`
- VXN input: the most recent VXN daily close **strictly before** the NQ
  session date (no lookahead) — verified by `test_vxn_input_uses_only_prior_data`
- Annualization divisor: `sqrt(252)`
- NQ sigma multiplier: 1.25
- NQ fixed offset: 15.75 points

```
sigma_day   = cash_open * (vxn_prior_close / 100) / sqrt(252)
imp_up      = cash_open + 1.25 * sigma_day
imp_dn      = cash_open - 1.25 * sigma_day
ib_range    = ib_high - ib_low          # ib_high/ib_low over first 60 min, IB bar included
ib_ext_up   = ib_high + ib_range
ib_ext_dn   = ib_low  - ib_range
upper_level = (ib_ext_up + imp_up) / 2 - 15.75
lower_level = (ib_ext_dn + imp_dn) / 2 + 15.75
```

- Each session produces exactly one upper level and one lower level.
- **Level lifetime:** a level side stays live until 20 newer session levels
  have been created (`line_days = 20`).

## Touch semantics

- Upper-level touch -> SHORT signal. Lower-level touch -> LONG signal.
- **One physical first touch per level side, ever.** A level side is
  "touched" when a bar's high/low range contains the level, or when the
  close crosses the level relative to the prior close.
- **The first physical touch permanently consumes that side** — whether or
  not a trade is actually entered on it. A touch skipped because of
  position state, SAL, blocked time, missing anchor, or a simultaneous-
  touch collision **never becomes eligible again**. There is no "retry on
  the next touch."
- **No entry on the level's own creation bar** — the touch search starts
  strictly after `created_at`.
- **The expiry timestamp itself is excluded** from the touch search — a
  level cannot be touched exactly on the bar it expires.

## Entry / session rules

- Valid entries: 19:00 ET through 11:00 ET (next day)
- No entries: 11:00 ET through 19:00 ET
- Session cutoff: 15:00 ET
- A touch at/after 19:00 ET belongs to the **following** calendar session
  date (evening entries roll into the next day's session).
- **One global position maximum** — across the whole book, exactly one NQ
  position may be open at any instant. A touch while a position is open
  consumes that level side without entering.
- **No same-minute exit and re-entry** — a new touch on the exact same
  1-minute bar the active position exits is not entered.

## Position sizing (points)

- **Anchor:** the previous completed 60-minute high-low range at the
  physical-touch time (hourly bars, `label="left", closed="left"`; the
  anchor is the range of the hour immediately preceding the touch's own
  hour bucket).
- **Stop distance:** `min(1.5 * anchor, 200)`
- **Target distance:** equal to stop distance (strict 1:1 reward-to-risk).

## Conditional breakeven

- Bar count: 45 (0-indexed bars **after** the touch bar — the touch bar
  itself is bar "-1" in this counting, handled separately; see touch-bar
  handling below).
- Price field at the checkpoint: the **open** of bar index 45.
- Profitable-side condition: for a long, `open[45] >= entry`; for a short,
  `open[45] <= entry`.
- The checkpoint bar (bar 45) is the bar whose open decides arming; the
  decision is made once, the first time bar index >= 45 is reached, and
  never re-evaluated afterward.
- **After BE arms**, the stop moves to entry for the remainder of the trade
  (replacing the original stop); the target is unaffected.
- If BE never arms (checkpoint bar's open is on the losing side), the
  original stop remains in place for the whole trade.

## SAL (stop-after-loss)

- A **qualifying loss**: `pnl < -0.1` points AND `exit_reason != "BE"`.
- SAL arms at the **actual exit timestamp** of a qualifying loss — never
  retroactively from the losing trade's entry time.
- **A 0-point BE scratch never arms SAL.**
- **A negative cutoff exit DOES arm SAL** (a cutoff with `pnl < -0.1` counts
  as a qualifying loss).
- Once armed, SAL blocks **all** later entries in the same session
  (19:00 ET -> next-day 15:00 ET).
- SAL resets at the start of the next session — the very next touch
  belonging to a different session date is evaluated with SAL inactive.

## Intrabar assumptions

- **Touch-bar stop-first rule:** on the touch bar itself, only the stop is
  checked. If the touch bar's range also reaches the stop, the trade exits
  there immediately as a loss. A target hit on the touch bar is **never**
  assumed a win (no causal ordering within a single bar can prove the
  target was reached before a stop that also fell within that bar's range).
- **Gap-through fill policy:** if the level itself is not inside the touch
  bar's `[low, high]` range (i.e. the touch was detected via a close-cross
  rather than a range-containment), the fill price is the touch bar's
  **close**, not the level. This is a deterministic **realistic-fill**
  assumption, not a worst-case one — it can help or hurt PnL depending on
  trade direction and the direction of the gap.
- **Simultaneous-touch ordering:** when two level sides (upper and lower)
  have their physical first touch at the exact same timestamp, the
  **older level wins** (deterministic level-age ordering) — the younger
  level's side is treated as a simultaneous-touch collision and consumed
  without a trade.
- **Cutoff price:** if a trade is still open at the session's 15:00 ET
  cutoff, it closes at that bar's close price.
- **PF includes every cutoff outcome**, positive and negative — cutoff
  exits are not excluded from profit-factor or net-points calculations
  anywhere in this handoff (verified directly by
  `test_pf_includes_cutoff_outcomes`).

## What this document does not describe

No alternative stop multiplier, reward-to-risk ratio, absolute cap, BE bar
count, or SAL on/off variant is authorized or described here. See README.md
for the explicit statement on optimization authorization.
