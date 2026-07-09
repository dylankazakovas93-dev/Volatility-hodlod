# Stage 3 Integrity Audit

## 1. Git State

| Field | Value |
|---|---|
| Current SHA | `5c00fb90d4688422abb2ccb7de208b03febacb56` |
| Parent SHA | `2cdcdd3624d3f85dfd1566b9248db7aa37f5cc9f` |
| Working tree | Clean |
| Branch | `fidelity/og-operational-100r-reproduction` |

## 2. Files Changed Since Stage 1 (`2cdcdd3..HEAD`)

| File | Status | Lines |
|---|---|---|
| `_synthetic_helpers.py` | Modified | +493 / -23 |
| `test_level_generation.py` | Added | +183 |
| `test_og_rules.py` | Modified | +12 / -11 |

### Changes to `_synthetic_helpers.py`

- **`ENTRY_BLOCKED_START`**: 600 → 660 (aligned with frozen `strict_engine.py` which blocks `11*60 <= m < 15*60`)
- **`first_touch`**: Unchanged from Stage 1 (cross_down already used `prev_close > level`)
- **Added**: `session_date_frozen`, `load_vxn_close`, `prior_vxn_close`, `generate_levels`, `add_level_expiry`, `bar_ranges`, `prev_completed_range`, `physical_touches_independent`, `simulate_from_touch_independent`, `run_strict_independent`, `_max_drawdown`, `_max_loss_streak`
- **No behavioral weakening**: all Stage 1 helper functions preserve exact same logic

### Changes to `test_og_rules.py`

3 tests corrected to match frozen engine's 11:00 block start:

| Original | Current | Change | Frozen Evidence |
|---|---|---|---|
| `test_entry_blocked_1000_to_1500` | `test_entry_blocked_1100_to_1500` | Block boundary 10:00→11:00, free ts 09:59→10:59 | `strict_engine.py:43`: `return not (11*60 <= m < 15*60)` |
| `test_touch_consumed_when_entry_blocked` | unchanged name | Touch ts 10:30→11:30 | Same evidence |
| `test_blocked_touch_gone_forever` | unchanged name | Touch ts 10:30→11:30 | Same evidence |

These changes do **not** weaken the tests. They correct test expectations to match the actual frozen implementation rather than a misstated constant comment.

## 3. Test-Change Reconciliation

- **Original Stage 1 tests**: 72
- **Current Stage 1 tests**: 72 (none removed, none weakened)
- **New tests added** (Stage 2): 13 level-generation tests
- **Current total**: 85

### Required Rule Coverage (all confirmed present)

| Rule | Test Coverage |
|---|---|
| Zero overlap and zero stacking | `test_zero_overlap`, `test_zero_stacking` |
| Blocked touches remain consumed | `test_touch_consumed_when_entry_blocked`, `test_blocked_touch_gone_forever`, `test_blocked_rejected_touch_cannot_become_valid` |
| No same-minute re-entry | `test_no_same_minute_reentry` |
| Simultaneous-touch ordering | `test_simultaneous_touch_tie_break` |
| Clean and gap-through fills | `test_clean_touch_fills_at_level`, `test_gap_through_entry_uses_close` |
| Touch-bar stop-only behavior | `test_touch_bar_stop_only` |
| No touch-bar target | `test_touch_bar_target_not_awarded` |
| Exact stop and exact 1R target | `test_stop_formula_long`, `test_stop_formula_short`, `test_stop_capped_at_200`, `test_target_1R_long`, `test_target_1R_short`, `test_stop_precedes_target` |
| Original stop for first 45 bars | `test_first_45_bars_original_stop` |
| One-time rest[45] BE check | `test_rest_45_one_time_be_check` |
| Failed BE check never repeats | `test_failed_be_never_repeats` |
| BE fill exactly at entry (zero PnL) | `test_be_pnl_exactly_zero` |
| No worsened BE fill | `test_be_fill_not_worsened_by_gap` |
| Current row excluded from rolling PF | `test_current_row_excluded`, `test_exclude_current_row_exact` |
| OFF rows retained in future windows | `test_off_trades_remain_shadow`, `test_off_trades_influence_future` |
| Exact 1.10 re-entry | `test_threshold_reentry`, `test_symmetric_110` |
| Prefix and append causality | `test_prefix_causality`, `test_append_causality` |

## 4. Test Execution

### Current 85-test suite: **85 passed, 0 failed**

```
$ python -m pytest reproduction/og_operational_100r/ -v
85 passed in 1.50s
```

### Original Stage 1 tests against current implementation: **69 passed, 3 failed**

The 3 failures are exactly the 3 tests with stale 10:00 boundaries (documented above):

```
FAILED test_touch_consumed_when_entry_blocked (expects 10:30 blocked, 10:30 is now free)
FAILED test_blocked_touch_gone_forever (same reason)
FAILED test_entry_blocked_1000_to_1500 (expects 10:00 blocked, block starts 11:00)
```

These failures confirm the boundary correction is real and explains the change.

## 5. Independent Engine Row-by-Row Validation

### Executed trades match: **ALL 15 COLUMNS, ALL 1107 TRADES**

| Column | Match |
|---|---|
| level_id | ✓ |
| session_date | ✓ |
| year | ✓ |
| side | ✓ |
| entry_time | ✓ |
| exit_time | ✓ |
| entry_price | ✓ |
| exit_price | ✓ |
| level | ✓ |
| anchor | ✓ |
| cap | ✓ |
| exit_reason | ✓ |
| pnl | ✓ |
| gap_through | ✓ |

### Executed hash (SHA-256 of pandas hash): `f8db4a85902cc889892350803ff44cd61b75e49d0fefa435fc3235a59a883e6a`

**Hash match**: frozen == independent ✓

### Aggregate metrics match

| Metric | Frozen | Independent | Match |
|---|---|---|---|
| executed | 1107 | 1107 | ✓ |
| net_pts | 6648.17 | 6648.17 | ✓ |
| PF | 1.2924 | 1.2924 | ✓ |
| win_rate | 0.3803 | 0.3803 | ✓ |
| TP | 394 | 394 | ✓ |
| SL | 333 | 333 | ✓ |
| BE | 281 | 281 | ✓ |
| cutoff | 99 | 99 | ✓ |
| max_drawdown | -1290.29 | -1290.29 | ✓ |
| gap_through_count | 8 | 8 | ✓ |
| yearly | identical | ✓ |
| cost_adjusted | identical | ✓ |

### Full ledger (3,486 rows)

All non-null values match exactly. 2,379 NaN-vs-NaT comparisons are IEEE 754 false positives (NaN != NaN by specification). Zero real value mismatches.

### Mismatch counts

| Metric | Count |
|---|---|
| PnL mismatches (real) | **0** |
| Exit reason mismatches (real) | **0** |
| Entry price mismatches (real) | **0** |
| Any field real mismatches | **0** |

## 6. Benchmark Status

| Benchmark | Status | Note |
|---|---|---|
| **1,107-trade strict canonical engine** | ✅ **Reproduced** | Stage 3 complete |
| **1,355-shadow-row OG_OPERATIONAL_100R pooled/gated** | ❌ **Not yet claimed** | Requires rolling PF gate and pooled benchmark — Stage 4 not started |

## 7. Audit Verdict

**PASS.** The independent engine reproduces the frozen canonical engine exactly. No Stage 1 test was removed or weakened. All 28 required behavioral rules remain covered. The 1,107-trade benchmark is confirmed reproduced. The 1,355-shadow-row benchmark is not claimed. Stage 4 has not been started.

### Supporting Files

- `reconciliation.json` — machine-readable audit evidence
- `audit_current_test_log.txt` — test output
- `_synthetic_helpers.py` — independent implementation
