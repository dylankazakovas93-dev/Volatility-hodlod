# VXN + NQ Strategy Verification Package

## Purpose

Independent frozen-strategy reproduction for the **OG_OPERATIONAL_100R** configuration (Candidate A, 1R target). Reproduces the strict-engine 1,107-trade canonical benchmark and the 1,355-row pooled/shadow-ledger benchmark with rolling-PF gate (w=100, t=1.10, symmetric).

## Package Structure

```
vxn_nq_strategy_verify/
├── engine/                    # Independent engine implementation
│   ├── _synthetic_helpers.py  # Touch detection, BE45, level gen, rolling PF
│   └── _assemble_and_gate.py  # Shadow assembly, gate application, metrics
├── config/                    # Frozen configuration files
│   ├── canonical_config.json  # Machine-readable canonical config
│   └── OG_OPERATIONAL_100R.yaml  # Source YAML config
├── tests/                     # Test suites (98 tests total)
│   ├── test_og_rules.py       # 72 Stage 1 rule tests
│   ├── test_level_generation.py  # 13 Stage 2 level-gen tests
│   └── test_causality.py      # 13 Stage 4 causality tests
├── ledgers/                   # Frozen + reproduced ledgers
│   ├── gated_benchmark.csv    # Frozen 1,355-row gated benchmark
│   ├── assembled_shadow.csv   # Frozen assembled shadow sequence
│   └── strict_canonical_1107_trades.csv  # Reproduced 1,107-trade strict engine
├── reports/                   # Verification reports
│   ├── STAGE3_INTEGRITY_AUDIT.md
│   ├── STAGE4_FINAL_REPORT.md
│   ├── EXPECTED_VS_ACTUAL_BENCHMARK.md
│   ├── CAUSALITY_AUDIT.md
│   └── MISMATCH_REPORT.md
├── manifests/                 # Evidence and reconciliation
│   ├── evidence_manifest.json
│   ├── reconciliation.json
│   └── FILE_INDEX.json
├── DATA_CONTRACT.md           # Required data files and hashes
├── FROZEN_STRATEGY_RULES.md   # Frozen strategy parameter reference
├── reproduce_and_verify.sh    # Automated verification script
└── README.md                  # This file
```

## Quick Start

```bash
# Install dependencies
pip install pandas numpy pytest PyYAML

# Run all 98 tests
python -m pytest tests/ -v

# Run automated verification
./reproduce_and_verify.sh
```

## Verification Results

- **98/98 tests passed** (72 Stage 1 + 13 Stage 2 + 13 Stage 4/causality)
- **1,107 trades**: strict engine reproduced exactly (all 15 columns match)
- **1,355 shadow rows**: assembled, gated, metrics match expected
- **Zero is_flat mismatches** across all rows
- **All 9 causality invariants** proven

## Verdict

**EXACT_REPRODUCTION**
