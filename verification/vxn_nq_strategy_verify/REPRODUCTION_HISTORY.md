# Reproduction History — OG_OPERATIONAL_100R

## Chronology

### Stage 0 — Evidence Lock
- **Commit**: `fe36843b4d77d54a2e8a4bf00346e6bdf0b78b99`
- **Action**: Locked repository state, frozen references, canonical configs, source hashes, and data-file expectations.
- **Branches**: `fidelity/og-operational-100r-reproduction`

### Stage 1 — Rule Implementation (72 tests)
- **Scope**: Physical touch detection, BE45 simulation, entry/exit rules, position management, stop/target calculation, rolling PF gate, cutoff logic, determinism
- **Tests**: 72 tests in `tests/test_og_rules.py`
- **Result**: ALL PASS

### Stage 2 — Level Generation (13 tests)
- **Scope**: Sigma formula, initial-balance range, line expiry after 20 sessions, creation/expiry bar exclusion from touch eligibility, VXN prior handling
- **Tests**: 13 tests in `tests/test_level_generation.py`
- **Result**: ALL PASS

### Stage 3 — Integrity Audit
- **Commit**: `279d992`
- **Scope**: Engine reproduction proof (1,107-trade strict engine reproduced), test boundary corrections (entry-blocked-inclusive fix), determinism verification
- **Documentation**: `reports/STAGE3_INTEGRITY_AUDIT.md`
- **Result**: EXACT_REPRODUCTION

### Stage 4 — Shadow Assembly + Rolling PF Gate (13 tests + benchmark)
- **Scope**: Pooled 1,355-row shadow assembly from 3 component ledgers, rolling PF gate application (w=100, t=1.10, symmetric), causality invariants
- **Tests**: 13 causality tests in `tests/test_causality.py`
- **Result**: EXACT_REPRODUCTION
- **Commit**: `173d036246c574b762da95ab2cea1dcd1a736837`

### Verification Package
- **Commit**: `edd8123630b3156fb0ad25d4ff1b2fe4bbb0a`
- **Action**: Package complete with 29 files, comprehensive verification script, all hashes locked

## Benchmark Verification Results (unchanged across all stages)

| Metric | Expected | Actual | Match |
|---|---|---|---|
| Shadow rows | 1,355 | 1,355 | YES |
| ON rows | 780 | 780 | YES |
| OFF rows | 575 | 575 | YES |
| Flat runs | 20 | 20 | YES |
| Net points | 6,738.191 | 6,738.191 | YES |
| Points PF | 1.568369 | 1.568369 | YES |
| Total R | 62.2389 | 62.2389 | YES |
| R PF | 1.249115 | 1.249115 | YES |
| MDD points | -721.5375 | -721.5375 | YES |
| MDD R | -10.9691 | -10.9691 | YES |
| Tests | 98 | 98 | YES |