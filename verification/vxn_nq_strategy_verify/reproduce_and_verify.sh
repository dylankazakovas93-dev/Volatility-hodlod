#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd "$(dirname "$0")" && pwd)"
# Navigate up: verification/vxn_nq_strategy_verify -> verification -> repo root
REPO_DIR="$(cd "$PACKAGE_DIR/../.." && pwd)"

echo "=== VXN + NQ Strategy — Verify ==="
echo "Package dir: $PACKAGE_DIR"
echo "Repo dir:    $REPO_DIR"
echo ""

FAILURES=0

fail() {
    echo "  FAIL: $1"
    FAILURES=$((FAILURES + 1))
}

pass() {
    echo "  OK:   $1"
}

SHA256_FILE="$PACKAGE_DIR/ARTIFACT_HASHES.sha256"

# 1. Repository branch check
EXPECTED_BRANCH="fidelity/og-operational-100r-reproduction"
CURRENT_BRANCH=$(cd "$REPO_DIR" && git branch --show-current)
if [ "$CURRENT_BRANCH" != "$EXPECTED_BRANCH" ]; then
    fail "Expected branch $EXPECTED_BRANCH, got $CURRENT_BRANCH"
else
    pass "Repository branch: $CURRENT_BRANCH"
fi

# 2. Verify NQ data exists and hash matches
NQ_PATH="$REPO_DIR/data/nq_1m/nq_continuous_2018_2026_1m.csv"
NQ_EXPECTED_SHA="9f427eb053b6c63e50f79baf666f239f851558d1558e706fc126cbe69f3a5af4"

if [ ! -f "$NQ_PATH" ]; then
    fail "NQ 1-minute bars not found at $NQ_PATH (required — all fidelity tests need NQ data)"
elif [ "$(sha256sum "$NQ_PATH" | cut -d' ' -f1)" != "$NQ_EXPECTED_SHA" ]; then
    fail "NQ file hash mismatch at $NQ_PATH (expected $NQ_EXPECTED_SHA)"
else
    pass "NQ file present and hash matches: $NQ_EXPECTED_SHA"
fi

# 3. Verify VXN data exists and hash matches
VXN_PATH="$REPO_DIR/data/vxn_daily_2018_2026.csv"
VXN_EXPECTED_SHA="76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e"

if [ ! -f "$VXN_PATH" ]; then
    fail "VXN data not found at $VXN_PATH"
elif [ "$(sha256sum "$VXN_PATH" | cut -d' ' -f1)" != "$VXN_EXPECTED_SHA" ]; then
    fail "VXN file hash mismatch at $VXN_PATH (expected $VXN_EXPECTED_SHA)"
else
    pass "VXN data present and hash matches: $VXN_EXPECTED_SHA"
fi

# 4. Verify OG_OPERATIONAL_100R.yaml config hash
CONFIG_PATH="$REPO_DIR/configs/OG_OPERATIONAL_100R.yaml"
CONFIG_EXPECTED_SHA="ea8be55a8c5f61913a1d1b141c61a3d65d8cdc958070e8415375918e6678743f"

if [ ! -f "$CONFIG_PATH" ]; then
    fail "Config not found at $CONFIG_PATH"
elif [ "$(sha256sum "$CONFIG_PATH" | cut -d' ' -f1)" != "$CONFIG_EXPECTED_SHA" ]; then
    fail "Config file hash mismatch (expected $CONFIG_EXPECTED_SHA)"
else
    pass "OG_OPERATIONAL_100R.yaml config hash matches: $CONFIG_EXPECTED_SHA"
fi

# 5. Verify all packaged file hashes match ARTIFACT_HASHES.sha256
EXPECTED_COUNT=$(wc -l < "$SHA256_FILE")
MATCH_COUNT=0
MISMATCH_COUNT=0

while IFS=' ' read -r expected_hash relative_path; do
    full_path="$PACKAGE_DIR/$relative_path"
    if [ ! -f "$full_path" ]; then
        fail "File missing (in ARTIFACT_HASHES but not on disk): $relative_path"
        MISMATCH_COUNT=$((MISMATCH_COUNT + 1))
        continue
    fi
    actual_hash=$(sha256sum "$full_path" | cut -d' ' -f1)
    if [ "$actual_hash" = "$expected_hash" ]; then
        MATCH_COUNT=$((MATCH_COUNT + 1))
    else
        fail "Package hash mismatch: $relative_path (expected $expected_hash, got $actual_hash)"
        MISMATCH_COUNT=$((MISMATCH_COUNT + 1))
    fi
done < "$SHA256_FILE"

if [ "$MISMATCH_COUNT" -eq 0 ]; then
    pass "All $MATCH_COUNT package files match ARTIFACT_HASHES.sha256"
else
    fail "Package file hash verification: $MATCH_COUNT match, $MISMATCH_COUNT mismatch"
fi

# 6. Run test suite (all 98 tests)
echo ""
echo "=== Running test suite ==="
cd "$REPO_DIR"
python -m pytest reproduction/og_operational_100r/ -v --tb=short 2>&1
PYTEST_EXIT=$?
if [ $PYTEST_EXIT -ne 0 ]; then
    fail "Test suite failed with exit code $PYTEST_EXIT"
else
    pass "All tests passed (exit code 0)"
fi

# 7. Regenerate benchmark and validate actual metrics
echo ""
echo "=== Regenerating benchmark ==="
python3 << "PYEOF"
import os, sys
os.chdir(os.environ.get('REPO_DIR', '/workspaces/Volatility-hodlod'))
sys.path.insert(0, os.getcwd())

from reproduction.og_operational_100r._assemble_and_gate import main
gated, metrics = main()

expected = {
    'n_shadow': 1355, 'n_active': 780, 'n_flat': 575, 'n_flat_runs': 20,
    'net_pts': 6738.191, 'points_pf': 1.568369,
    'total_r': 62.2389, 'r_pf': 1.249115,
    'mdd_pts': -721.5375, 'mdd_r': -10.9691
}
all_ok = True
for k, v in expected.items():
    actual = metrics.get(k)
    if actual is None:
        print(f'  FAIL: {k} not in metrics dict')
        all_ok = False
        continue
    if isinstance(v, float):
        match = abs(actual - v) < 0.001
    else:
        match = actual == v
    status = 'OK' if match else 'FAIL'
    print(f'  {status}: {k}: expected={v}, actual={actual}')
    if not match:
        all_ok = False

if all_ok:
    print('Benchmark validation PASSED')
else:
    print('Benchmark validation FAILED')
    sys.exit(1)
PYEOF
BENCHMARK_EXIT=$?
if [ $BENCHMARK_EXIT -ne 0 ]; then
    fail "Benchmark validation failed with exit code $BENCHMARK_EXIT"
fi

# 8. Compare output hashes against frozen artifacts
echo ""
echo "=== Comparing output hashes ==="
HASH_EXPECTED=$(cd "$REPO_DIR" && sha256sum artifacts/og_operational_100r_fidelity/gated_benchmark.csv | cut -d' ' -f1)
HASH_PACKAGE=$(cd "$REPO_DIR" && sha256sum "$PACKAGE_DIR/ledgers/gated_benchmark.csv" | cut -d' ' -f1)
echo "  Expected hash: $HASH_EXPECTED"
echo "  Package hash:  $HASH_PACKAGE"
if [ "$HASH_EXPECTED" = "$HASH_PACKAGE" ]; then
    pass "Output hash match between reproduced and packaged gated_benchmark.csv"
else
    fail "Output hash MISMATCH: expected=$HASH_EXPECTED, package=$HASH_PACKAGE"
fi

# 9. Check determinism: re-run to temp path and compare hash
echo ""
echo "=== Determinism check ==="
cd "$REPO_DIR" && python3 > /dev/null 2>&1 << 'PYEOF'
import sys
sys.stdout = open('/dev/null', 'w')
from reproduction.og_operational_100r._assemble_and_gate import (
    COMPONENT_LEDGERS, assemble_shadow_sequence, apply_gate
)
shadow = assemble_shadow_sequence(COMPONENT_LEDGERS)
gated = apply_gate(shadow)
gated = gated.drop(columns=["entry_ts"])
gated.to_csv('/tmp/_verify_gated_benchmark.csv', index=True)
PYEOF
REGEN_HASH=$(sha256sum /tmp/_verify_gated_benchmark.csv | cut -d' ' -f1)
FIRST_HASH=$(cd "$REPO_DIR" && sha256sum artifacts/og_operational_100r_fidelity/gated_benchmark.csv | cut -d' ' -f1)
if [ "$REGEN_HASH" = "$FIRST_HASH" ]; then
    pass "Deterministic: regenerated gated_benchmark hash matches frozen artifact"
else
    fail "Determinism check FAILED: frozen=$FIRST_HASH, regenerated=$REGEN_HASH"
fi

# Cleanup
rm -f /tmp/_verify_gated_benchmark.csv

echo ""
if [ "$FAILURES" -eq 0 ]; then
    echo "=== ALL VERIFICATIONS PASSED ($FAILURES failures) ==="
    exit 0
else
    echo "=== VERIFICATION FAILED: $FAILURES failure(s) ==="
    exit 1
fi