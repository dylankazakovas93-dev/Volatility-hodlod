# Stage 3 -- Breakeven / Scratch-Management Report

Branch: `research/claude-stage3-be-scratch`, from
`061d557e03e9712743685c96dafbc8bdd54d7944`. Development years only:
2018, 2020, 2023, partial 2026. Frozen: E-F entry window (08:00-11:00 ET),
F2 TP/SL coefficients (unrefit), SAL off, gross P&L, one global position,
15:59 ET forced liquidation.

## 1. Control reproduction

| | Expected | Reproduced |
|---|---|---|
| Trades | 247 | 247 |
| Net (pts) | +2,132.91 | +2,132.91 |
| PF | 1.3836 | 1.3836 |

Exact match -- confirmed before testing any management rule.

## 2. Historical BE45 -- exact semantics and result

Full semantics documented in `docs/STAGE3_BE45_HISTORICAL_SEMANTICS.md`
(read from `src/strict_engine.py`, not inferred): checkpoint at bar index
45 (0-indexed post-touch), arm decision made once using that bar's **open**
vs. entry, and -- the one deliberate, faithfully-reproduced difference from
every other Stage 3 rule -- **same-bar activation** (the checkpoint bar's
own low/high is checked against the new stop in the same iteration that
decided to arm it, not the following bar).

Result: **251 trades, net +2,041.29, PF 1.4262**, max DD -408.87 (17.3%
better than control's -494.12).

## 3-7. Candidate family results (all 22 non-control candidates)

Full table: `outputs/stage3_candidate_summary.csv`. Best per family:

| Family | Best setting | Trades | Net | PF | Max DD |
|---|---|---|---|---|---|
| Exact-R BE | 0.75R | 249 | +1,982.18 | 1.4220 | -408.50 |
| TP-progress BE | 75% | 248 | +1,875.78 | 1.3784 | -384.12 |
| Profit lock | 0.75R (+0.10R lock) | 249 | +1,968.98 | 1.4192 | -380.27 |
| Time-delayed BE | 15 min | 256 | +1,321.53 | 1.3831 | -326.50 |
| Scratch-on-recovery | 0.75R | 247 | +1,714.89 | 1.3458 | -534.00 |
| Combined BE+scratch | 0.75R/0.75R | 249 | +1,511.16 | 1.3523 | -430.50 |

Within each family there is a clear, mostly-monotonic pattern: earlier/
smaller trigger thresholds (0.25R, 25%, 15min in some families) fire too
often, cutting winners short before they reach TP and dragging net down
sharply (e.g. exact-R at 0.25R: net collapses to +833, -60.9% vs control)
without buying back enough drawdown improvement to justify it. The later/
larger thresholds (0.75R-1.00R, 75%) recover most of the net while still
meaningfully improving drawdown -- a genuine gradient, not noise.

## 4. Selection-gate evaluation

Applying the stated rule ("PF and net both improve" **or** "max DD improves
>=15% while PF falls <=0.02 and net falls <=10%") to every candidate
against the control:

| Candidate | PF | Net | DD improvement | PF change | Net change | Qualifies |
|---|---|---|---|---|---|---|
| historical_BE45 | 1.4262 | +2,041.29 | 17.3% | +0.0426 | -4.3% | **Yes** |
| exact_r_be_0.75R | 1.4220 | +1,982.18 | 17.3% | +0.0384 | -7.1% | **Yes** |
| profit_lock_0.75R | 1.4192 | +1,968.98 | 23.0% | +0.0356 | -7.7% | **Yes** |
| all other 19 candidates | -- | -- | -- | -- | -- | No (either net falls >10%, DD improves <15%, or both) |

No candidate satisfies "PF and net both improve" (criterion 1) -- the
control's net (+2,132.91) is the highest of all 24 configurations tested,
which makes sense: any stop-tightening rule caps some upside by
definition. All three qualifying candidates pass via criterion 2, and all
three independently satisfy every additional requirement: all 4
development years profitable, ex-2026 (2018+2020+2023) profitable, and
the rule helps or is neutral in 4/4 years (not just 3/4).

**These three are not isolated spikes.** `exact_r_be_0.75R` and
`profit_lock_0.75R` converge on the same 0.75R trigger threshold under two
different action rules (move-to-entry vs. lock-small-profit) -- two
independent mechanisms agreeing at the same threshold is a meaningfully
different kind of evidence than one lucky parameter. `historical_BE45`
(bar 45 ~ 45 minutes, using same-bar activation) is a single historical
reference point rather than part of a swept new family, so it isn't
subject to the same neighboring-parameter check, but its magnitude is
consistent with the 0.75R region's results (all three cluster in
PF 1.42-1.43, net +1,970-2,040, DD -380 to -410).

## 5. Recommendation

**`profit_lock_0.75R`** is the strongest of the three on the metric the
gate explicitly foregrounds (drawdown): 23.0% max-DD improvement vs. 17.3%
for the other two, at a comparable net cost (-7.7% vs -4.3%/-7.1%) and
a PF within 0.003 of `exact_r_be_0.75R`. `historical_BE45` gives up the
least net (-4.3%) and has the highest raw PF, but its drawdown improvement
is smaller (17.3%) and it inherits the historical same-bar-activation
quirk rather than the stricter next-bar causal design used elsewhere in
Stage 3. All three are legitimate, gate-passing choices; the difference
between them is a PF-vs-drawdown-vs-mechanism-purity tradeoff, not a
correctness question -- reported for your/ChatGPT's final call rather than
forced to a single number.

## 6. Results by development year (for the three qualifying candidates)

See `outputs/stage3_candidate_summary.csv`'s `yearly_json` column for the
full breakdown; all three are profitable in every one of 2018, 2020, 2023,
and 2026 individually.

## 7. No-overlap / causality confirmation

`tests/test_stage3_be_scratch.py` (8 tests, all passing): control matches
plain first-passage; exact-R BE does NOT activate on its own trigger bar
(verified with a bar that would falsely exit BE if same-bar activation
were used); it DOES activate correctly on the bar after; scratch-on-
recovery never exits on its own arming bar; historical BE45's deliberate
same-bar exception is verified explicitly; no trade overlap in the
committed control ledger; control headline reproduces exactly; no
reserved-year (2019/2021/2022/2024/2025) trade appears in any candidate's
ledger.
