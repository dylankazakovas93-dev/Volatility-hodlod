# NQ Level-Fade Strategy — Verification Handoff

Hand this folder + this prompt to a fresh chat. It contains the data, the engine,
the scripts, and every headline number with the exact command to reproduce it.
**Treat every claim below as unverified until you re-run it yourself.**

---

## 0. Standing constraint (carry forward verbatim)
Do **not** comment on prop-firm fit / fundability / "is this enough money."
Only assess statistical / technical validity.

---

## 1. Locked strategy config (`tp_sl_cap200`)
- **Entry:** fade a level on first touch. `upper` level → SHORT, `lower` level → LONG.
- **TP = SL = `min(1.5 × previous completed 1h range, 200)`** → strict **1:1 RR**.
  (TP distance and SL distance are the SAME number = `cap`.)
- **Entry window:** 19:00–11:00 ET. **Skip 11:00–15:00 ET.**
- **Session:** a "session" runs 19:00 ET → next-day 15:00 ET. A touch at/after
  19:00 ET is assigned to the next calendar day.
- **SAL (stop-after-loss):** the first **real loss** in a session stops all further
  entries that session. A 0-pt breakeven scratch does NOT stop the session.
- **lineDays = 20:** a level stays active until 20 newer levels have been created.

## 2. Level formula (per session, anchored at 09:30 ET cash open)
```
sigma_day  = cash_open × (vxn_prev_session_close / 100) / sqrt(252)
imp_up     = cash_open + 1.25 × sigma_day
imp_dn     = cash_open − 1.25 × sigma_day
IB         = 09:30–10:30 ET (first 60 min);  ib_range = ib_high − ib_low
ib_ext_up  = ib_high + ib_range
ib_ext_dn  = ib_low  − ib_range
sigma_offset = 15.75   (FIXED for NQ, never scales)
upper_level = (ib_ext_up + imp_up) / 2 − 15.75
lower_level = (ib_ext_dn + imp_dn) / 2 + 15.75
```
`vxn_prev_session_close` = the VXN daily close STRICTLY BEFORE the session date
(holiday-aware: a cash-market-holiday session uses the last real settle, e.g.
Memorial-Day Monday uses the prior Friday's VXN). Holiday-origin levels are KEPT,
not filtered.

## 3. Data in this folder
| file | what |
|---|---|
| `data/nq_continuous_2018_2026_1m.csv` | continuous front-month NQ, 1-min OHLCV, 2018→2026 (~2.96M rows) |
| `data/vxn_daily_2018_2026.csv` | VXN daily OHLC, 2017-12 → 2026-06 |
| `data/nq_standard_ledger_2018_2026.csv` | Standard variant trade ledger |
| `data/nq_be60_sala_ledger_2018_2026.csv` | BE60 SAL-A ledger (IDEALIZED — see §5 warning) |
| `data/nq_be60_sala_enriched_2018_2026.csv` | BE60 ledger + mae/mfe/uw60/be_dd flags |
| `data/nq_master_ledger.csv` | older canonical master ledger w/ holiday + event flags |
| `volgen/levels.py`, `volgen/reactions.py` | the level-generation + first-touch engine (NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily, _first_touch) |
| `scripts/*` | OOS engine, enrichment builder, report generator, BE-timing sweep |

Note: `load_gvz_daily` is the generic daily-vol loader; pass it the VXN file.

## 4. HEADLINE RESULTS — all realistic, same SAL, same data (VERIFY THESE)
Re-run: `python3 scripts/be_timing_sweep.py` (expects the bars + vxn paths inside;
edit if needed). Or rebuild ledgers with `scripts/nq_oos_2019.py` /
`scripts/build_be60_enriched.py`.

| Variant | n | Net (pts) | PF | 2019 OOS |
|---|---|---|---|---|
| **Standard (no BE)** — most trustworthy | 1143 | **17,843** | 1.61 | +106 |
| Conditional-BE @45 (arm only if green) | 1256 | 15,665 | 1.68 | +154 |
| Conditional-BE @30 | 1264 | 15,661 | 1.71 | +110 |
| Conditional-BE @90 | 1222 | 16,297 | 1.66 | −25 |
| Instant-BE @60 **(realistic)** | 1167 | 7,719 | 1.44 | −247 |
| Instant-BE @180 (realistic, best instant) | 1166 | 13,521 | 1.58 | −28 |
| ~~Instant-BE @60 (IDEALIZED — INFLATED, do not use)~~ | ~~1485~~ | ~~19,979~~ | ~~2.98~~ | ~~+218~~ |

**Honest hierarchy: Standard ≥ Conditional-BE(@30–45) ≫ Instant-BE (any timing).**

## 5. ⚠️ THE BUG THAT INFLATED EVERYTHING (verify this is fixed)
The original BE60 ("instant breakeven after 60 one-minute bars") assumed that when
the stop flips to entry at bar 60 and price is ALREADY underwater, the trade exits
at **exactly entry = 0 pts**. That fill is impossible: a stop moved to entry while
price is below entry (for a long) fills at the market = a real loss.

- Realistic fill for those underwater-at-60 ejections: **mean −25.86 pts, median −16**
  (open[60] fill = −25.86, close[59] fill = −25.84 → robust to the fill choice).
- 508 (post-SAL) / 612 (raw) BE trades were underwater at bar 60. Booking them at 0
  instead of −26 created a fake ≈ +10–15k pt swing — **that was the entire BE "edge."**
- Cohort check (612 underwater-at-60 raw trades): if simply HELD with original stop,
  **34% recover to full TP**, net −10,227 (avg −16.71). Ejecting them at BE: net
  −15,826 (avg −25.86). **Ejecting is ~5,600 pts WORSE than holding.** On 1:1, the
  34% full-cap recoveries outweigh trimming the losers from −cap to −26.
- Consequence: those ejections are real losses, so they should ALSO trigger SAL
  (they don't in the idealized ledger). Both PnL and SAL were too optimistic.

A previous session concluded "instant BE60 is vindicated; underwater-at-60 only wins
20% so scratching them is the edge." **That conclusion is RETRACTED** — it relied on
the 0-fill. With realistic fills the result inverts (see §4).

## 6. What to re-verify first (suggested order)
1. **Standard net 17,843 / PF 1.61 / 2019 +106** — pure hard-TP/hard-SL, no BE, no
   fill assumptions. If this reconciles, the engine + data are sound. This is the
   number to trust.
2. **The −26 avg underwater fill** — pick any BE trade flagged `be_dd=True` in the
   enriched ledger; confirm it was below entry at the 60th minute, so a 0-pt exit
   was unfillable.
3. **The BE-timing sweep table (§4)** — confirm no BE timing beats Standard on net.
4. Spot-check level math on a holiday-origin trade, e.g. Juneteenth 2025-06-19 origin,
   SHORT level **22028.02** (cash_open 21784.50, vxn 22.14, IB 21786.75/21650.25,
   imp_up 22164.28, offset 15.75): `(21923.25 + 22164.28)/2 − 15.75 = 22028.02`. TP'd.

## 7. Open question for the new chat
Decide the locked config: **Standard** (highest net, zero fill assumptions, +2019)
vs **Conditional-BE @45** (≈2.2k less net but higher PF 1.68 and cleaner 2019 +154,
lower variance). Instant-BE in any form should be dropped.
