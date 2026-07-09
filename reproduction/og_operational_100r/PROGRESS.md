# OG_OPERATIONAL_100R Fidelity Reproduction — Progress

## Branch
`fidelity/og-operational-100r-reproduction`

## Local commits (chronological)
| Commit | Message | Stage |
|--------|---------|-------|
| `fe36843` | Lock OG operational 1R fidelity evidence | Stage 0 |
| `e9bd557` | Update evidence manifest with lock commit SHA and push status | Stage 0 |
| *(current)* | Add deterministic OG 1R rule tests | Stage 1 |

## Stage 1 — Synthetic rule tests

### Files created
- `reproduction/og_operational_100r/_synthetic_helpers.py` — independent helper module
- `reproduction/og_operational_100r/test_og_rules.py` — all synthetic rule tests
- `reproduction/og_operational_100r/PROGRESS.md` — this file

### Test classes (10 classes, ~73 tests)

| Class | Tests | Coverage |
|-------|-------|----------|
| `TestPositionAndTouch` | 13 | One global position, zero overlap, touch consumption, tie-breaks |
| `TestEntryBehavior` | 5 | Clean/gap fill, touch-bar stop-only, blocked touch consumption |
| `TestStopAndTarget` | 8 | Stop formula (long/short), 200 cap, 1R target, stop-before-target |
| `TestBE45` | 9 | First-45 original stop, rest[45] one-time check, eligibility, exact BE fill |
| `TestRollingPF` | 13 | Warm-up, thresholds, zero-denominator, causality invariants |
| `TestCutoff` | 1 | Forced exit at session cutoff |
| `TestEntryTime` | 5 | Entry blackout 10:00-15:00, hard blackout 16:00-19:00, cutoff rules |
| `TestDeterminism` | 4 | All operations produce identical results on repeat |
| `TestProfitFactor` | 5 | Zero-loss → inf, zero-gain → 0.0, normal, all-zeros |
| `TestPhysicalTouch` | 8 | Inside range, exact high/low, close-cross up/down, no-touch cases |

### Test command
```bash
python -m pytest reproduction/og_operational_100r/test_og_rules.py -v
```

### Dependencies
```
Python 3.12.1
pandas==3.0.3
numpy==2.5.1
pytest==9.1.1
PyYAML==6.0.3
```

### Remote push blocker
Codespace GITHUB_TOKEN lacks write permission to
`dylankazakovas93-dev/Volatility-hodlod`. Commits are local only.
Manual push: `git push origin fidelity/og-operational-100r-reproduction`

## Not started
- Stage 2 — Independent level engine
- All later stages
