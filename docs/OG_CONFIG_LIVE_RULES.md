# OG_CONFIG_CLEAN_BASELINE -- Live-Realistic Rule Extraction

Status: **`OG_CONFIG_CLEAN_BASELINE__VALID_RESEARCH_STARTING_POINT`**

Every rule below is recovered directly from `docs/STRATEGY_RULES.md`,
`configs/nq_current_config.yaml`, and `src/strict_engine.py` /
`src/level_generation.py` at commit `a375818` (byte-identical through
current HEAD -- see `docs/OG_CONFIG_HISTORY.md` section 1 for the diff
proof). This file is a structured index, not a rewrite -- where the
source document already states a rule precisely, it is quoted, not
paraphrased into something that could drift from it.

**Authoritative source for every value: `configs/nq_current_config.yaml`.
If this document and that file ever disagree, the YAML file wins.**

## Level generation

- Instrument: NQ (Nasdaq-100 E-mini futures).
- RTH level-building window: 09:30-16:00 ET.
- Cash open: first RTH bar's open.
- Initial Balance (IB) duration: 60 minutes; **the IB-completion bar is
  included** in the IB high/low range (not excluded).
- VXN input: most recent VXN daily close **strictly before** the NQ
  session date (no lookahead).
- Annualization divisor: `sqrt(252)`.
- Sigma multiplier: 1.25. Fixed offset: 15.75 points.

```
sigma_day   = cash_open * (vxn_prior_close / 100) / sqrt(252)
imp_up      = cash_open + 1.25 * sigma_day
imp_dn      = cash_open - 1.25 * sigma_day
ib_range    = ib_high - ib_low          # first 60 min, IB bar included
ib_ext_up   = ib_high + ib_range
ib_ext_dn   = ib_low  - ib_range
upper_level = (ib_ext_up + imp_up) / 2 - 15.75
lower_level = (ib_ext_dn + imp_dn) / 2 + 15.75
```

- Exactly one upper level and one lower level per session.

## Level lifetime

- A level side stays live until **20 newer session levels have been
  created** (`line_days = 20`). Implemented in `src/strict_engine.py`
  via `LINE_DAYS`, `expiry = lvls[i + LINE_DAYS].created_at`.

## Entry rule / side assignment

- Upper-level touch -> **SHORT** signal. Lower-level touch -> **LONG**
  signal (fade, not breakout).
- The first physical touch of a level side triggers the entry decision
  (subject to all execution safeguards below); there is no separate
  discretionary entry filter beyond the mechanics documented here.

## TP rule

- Target distance = stop distance (see below) -- a strict **1:1
  reward-to-risk**, not an independent target formula.

## SL rule

- **Anchor:** the previous completed 60-minute high-low range at the
  physical-touch time (hourly bars, `label="left", closed="left"` --
  the anchor is the range of the hour immediately preceding the touch's
  own hour bucket).
- **Stop distance:** `min(1.5 * anchor, 200)` points.

## BE / management rule

- Conditional breakeven, bar count **45** (0-indexed bars after the
  touch bar; the touch bar itself is handled separately as bar "-1").
- Checkpoint price field: the **open** of bar index 45.
- Arming condition: long arms if `open[45] >= entry`; short arms if
  `open[45] <= entry`.
- The checkpoint decision is made **once**, the first time bar index
  `>= 45` is reached, and is **never re-evaluated** afterward.
- If armed: stop moves to entry for the remainder of the trade (target
  unaffected). If never armed: original stop remains for the whole
  trade.
- This BE rule activates on the checkpoint bar's own open -- i.e. the
  decision uses information available at that bar's open, and the moved
  stop governs from that same bar onward (this is the OG engine's own
  documented convention; it is **not** the "next-bar-only" activation
  convention used by the later ground-up management-rule research --
  see the distinction called out explicitly in
  `docs/STRATEGY_RULES.md`'s bar-45 description and preserved verbatim
  here rather than silently reconciled to match the newer convention).

## SAL (stop-after-loss)

- A qualifying loss: `pnl < -0.1` points AND `exit_reason != "BE"`.
- Arms at the **actual exit timestamp** of a qualifying loss, never
  retroactively from entry time.
- A 0-point BE scratch **never** arms SAL.
- A negative cutoff exit **does** arm SAL.
- Once armed, blocks **all** later entries in the same session (19:00 ET
  -> next-day 15:00 ET).
- Resets at the start of the next session.

## Entry hours

- Valid entries: **19:00 ET through 11:00 ET** (next day).
- No entries: 11:00 ET through 19:00 ET.
- A touch at/after 19:00 ET belongs to the **following** calendar
  session date.

## Forced-exit time

- Session cutoff: **15:00 ET**. A trade still open at cutoff closes at
  that bar's close price. Cutoff outcomes (positive or negative) are
  **included** in PF/net-points everywhere -- never excluded.

## Round-number handling

- No explicit tick-rounding rule is documented for the OG stop/target
  distances in `docs/STRATEGY_RULES.md` or `configs/nq_current_config.yaml`
  (unlike the later ground-up Stage 1-5 F2 formula, which explicitly
  rounds TP up / SL down to the nearest 0.25 tick). This is recorded as a
  fact about the OG engine, not filled in with an assumed value: **the OG
  engine's stop/target distances are used as computed by the anchor
  formula above, with no separate tick-rounding step documented**. Any
  future experiment that wants tick rounding must add and document it
  explicitly rather than assuming it was already present.

## Physical-touch semantics

- A level side is "touched" when a bar's high/low range contains the
  level, or when the close crosses the level relative to the prior
  close.
- **One physical first touch per level side, ever.** The first physical
  touch permanently consumes that side, whether or not a trade is
  actually entered on it -- a touch skipped due to position state, SAL,
  blocked time, missing anchor, or a simultaneous-touch collision is
  **never** retried.
- **No entry on the level's own creation bar** (`creation_bar_exclude=True`
  in `physical_touches()`).
- **The expiry timestamp itself is excluded** from the touch search.
- **Simultaneous-touch ordering:** if upper and lower level sides touch
  at the exact same timestamp, the **older level wins**
  (`simultaneous_touch_ordering: oldest_level_first`); the younger
  level's side is consumed without a trade.

## Position-management semantics

- **One global position maximum** -- exactly one NQ position open at any
  instant, across the whole book. A touch while a position is open
  consumes that level side without entering (`record_skip(..., "position_open", ...)`
  in `src/strict_engine.py`).
- **No same-minute exit and re-entry** -- a new touch on the exact same
  1-minute bar the active position exits is not entered
  (`record_skip(..., "same_bar_reentry", ...)`).
- **Touch-bar stop-first rule:** on the touch bar itself, only the stop
  is checked; a target hit on the touch bar is never assumed a win.
- **Gap-through fill policy:** if the level itself is not inside the
  touch bar's `[low, high]` range (touch detected via close-cross), the
  fill price is the touch bar's **close** -- a deterministic
  realistic-fill assumption, not worst-case.

## Costs

- Headline result: **0.0 points** round-trip cost (gross).
- Also reported (not headline): 0.5 / 1.0 / 2.0 points round-trip,
  applied to TP / SL / BE / cutoff exits alike.

## Verification cross-reference

Every rule above is directly asserted by the OG test suite
(`tests/test_strategy_invariants.py`, `tests/test_data.py`) against the
engine's hardcoded constants -- no rule here is a hidden, undocumented
constant. See `docs/OG_CONFIG_HISTORY.md` section 1 for the exact `git
diff` commands proving none of this code has changed since the original
handoff commit.
