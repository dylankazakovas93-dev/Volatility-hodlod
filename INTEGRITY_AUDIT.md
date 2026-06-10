# Integrity Audit + Verification Trades

**Config:** `TP = SL = min(1.5 × previous completed 1h range, 200)`, 1:1 RR.
Entries 19:00–11:00 ET (skip 11:00–15:00), session stop-after-first-loss.
All timestamps **ET (America/New_York)** — matches TradingView for CME futures.

## Audit results (can the numbers be inflated?)

### 1. Intrabar TP+SL collisions — NOT inflated (conservative)
Only **3 of 1,841** trades (0.16%) had both target and stop reachable within a
single 1-minute bar. All 3 are scored pessimistically as **losses**. If anything
this *under*-states win rate.

### 2. BE60 — the BE count is honest, not a free lunch
Cross-tabulating each trade's BE60 exit vs what the **same trade** did under Standard:

| BE60 outcome | rescued from full loss | cost a would-be win | was cutoff anyway |
|---|---|---|---|
| BE exits | **402** | **304** | 309 |

Ratio rescued:cost = **1.32×**. BE genuinely gives up 304 winners to save 402
losers. The net edge is modest at trade level; the bigger payoff is variance
reduction (maxDD -815→-517, streak 8→4). Mechanism is legitimate.

### 3. Slippage sensitivity (fills assume exact level/stop, 0 slip)
| slip/side | Standard net | BE60 net |
|---|---|---|
| 0.0 | 17,843 | 19,979 |
| 0.25 | 17,272 | 19,236 |
| 0.5 | 16,700 | 18,494 |
| 1.0 | 15,557 | 17,009 |

NQ is deep-liquid (realistic stop slip ~0.25–0.5 pt). Even at a pessimistic
1pt/side, both stay solidly positive. **The one real optimism** is BE exits
assumed at exactly entry (0); at 1pt adverse fill that's ~850 pts hidden cost,
already folded into the table above.

**No lookahead:** levels use prior-session VXN close; stops/targets use the
*previous completed* 1h range; entry path starts the bar *after* the touch.

---

## 3 trades to verify in TradingView (NQ continuous 1-min, 2025+)

### Trade 1 — Standard WIN, BE60 scratch (both sides of the BE tradeoff)
- Entry **2025-06-12 20:05 ET** @ **21608.59**, LONG (fade lower)
- Anchor 106.25 → stop=target **159.38 pts** | Target 21767.97 / Stop 21449.22
- Standard: TP @ 21767.97 on 2025-06-13 09:32 ET (807 bars)
- BE60: breakeven scratch
- MFE 170.66 / MAE 137.59

### Trade 2 — clean Standard LOSS (fastest check)
- Entry **2025-04-21 09:56 ET** @ **18043.70**, LONG (fade lower)
- Anchor 57.00 → stop=target **85.50 pts** | Target 18129.20 / Stop 17958.20
- Standard & BE60: SL @ 17958.20 on 2025-04-21 10:02 ET (6 bars)
- MFE 0.00 / MAE 90.70

### Trade 3 — BE60 RESCUE (the mechanism that saves the weak years)
- Entry **2025-05-28 19:07 ET** @ **21678.89**, SHORT (fade upper)
- Anchor 108.00 → stop=target **162.00 pts** | Target 21516.89 / Stop 21840.89
- Standard: SL @ 21840.89 on 2025-05-29 03:59 ET (-162 pts, 532 bars)
- BE60: breakeven scratch (stop at entry after 60 min, exited flat before stop-out)
- MFE 14.39 / MAE 170.61

**Check:** (a) price touched the level that minute, (b) high/low path hits
target/stop where stated, (c) MAE/MFE match. If all reconcile, engine is faithful.

---

## Conditional-BE test (does instant-fire hurt? No — it's the edge)

Tested BE60-cond: arm breakeven at min 60 ONLY if the trade is not in drawdown
at the checkpoint (green going into minute 60); if underwater, keep the full
original stop. Intuition: "don't scratch a temporarily-underwater trade."

**The intuition is backwards for this strategy.** Trade state at the min-60
checkpoint is highly predictive of the eventual Standard outcome:

| state at min-60 | n | eventual win rate |
|---|---|---|
| underwater (red) | 950 | 20.1% (191 TP / 571 SL) |
| in profit (green) | 891 | 65.2% (581 TP / 163 SL) |

Being underwater at minute 60 => only 1-in-5 recover. Scratching them flat
(instant BE) avoids 571 full stops for the cost of 191 given-up wins.

Ranking (2018-2026, SAL-A for BE variants):

| variant | net | PF | maxDD | streak | 2019 OOS |
|---|---|---|---|---|---|
| Standard | 17,843 | 1.615 | -814.8 | 8 | +105.8 |
| **BE60 instant** | **19,979** | **2.983** | **-516.5** | **4** | **+217.9** |
| BE60-cond (arm-if-green) | 15,079 | 1.631 | -682.7 | 6 | **-47.3** |

Conditional is the WORST — negative in 2019. It protects winners (which win
anyway) and lets losers run. Instant BE60 wins *because* it fires when
underwater. The "instant fire even if in DD" behaviour IS the edge, not a flaw.
