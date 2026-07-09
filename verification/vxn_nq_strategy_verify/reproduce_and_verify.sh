#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$PACKAGE_DIR/../../.." && pwd)"

echo "=== VXN + NQ Strategy — Verify ==="
echo "Package dir: $PACKAGE_DIR"
echo "Repo dir:    $REPO_DIR"
echo ""

# 1. Verify repository
EXPECTED_BRANCH="fidelity/og-operational-100r-reproduction"
CURRENT_BRANCH=$(cd "$REPO_DIR" && git branch --show-current)
if [ "$CURRENT_BRANCH" != "$EXPECTED_BRANCH" ]; then
    echo "ERROR: Expected branch $EXPECTED_BRANCH, got $CURRENT_BRANCH"
    exit 1
fi
echo "✓ Repository branch: $CURRENT_BRANCH"

# 2. Verify required data
VXN_PATH="$REPO_DIR/data/vxn_daily_2018_2026.csv"
if [ ! -f "$VXN_PATH" ]; then
    echo "ERROR: VXN data not found at $VXN_PATH"
    exit 1
fi
echo "✓ VXN data present"

NQ_PATH="$REPO_DIR/data/nq_1m/nq_continuous_2018_2026_1m.csv"
if [ ! -f "$NQ_PATH" ]; then
    echo "WARNING: NQ 1-minute bars not found at $NQ_PATH"
    echo "         Some tests will be skipped."
    echo "         Expected SHA: 9f427eb053b6c63e50f79baf666f239f851558d1558e706fc126cbe69f3a5af4"
fi

# 3. Run test suite
echo ""
echo "=== Running test suite ==="
cd "$REPO_DIR"
python -m pytest reproduction/og_operational_100r/ -v --tb=short 2>&1
PYTEST_EXIT=$?
if [ $PYTEST_EXIT -ne 0 ]; then
    echo "ERROR: Test suite failed with exit code $PYTEST_EXIT"
    exit $PYTEST_EXIT
fi
echo "✓ All tests passed"

# 4. Regenerate benchmark and validate
echo ""
echo "=== Regenerating benchmark ==="
python3 -c "
import os, json, hashlib
os.chdir('$REPO_DIR')
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
    if isinstance(v, float):
        match = abs(actual - v) < 0.001
    else:
        match = actual == v
    status = '✓' if match else '✗'
    print(f'  {status} {k}: expected={v}, actual={actual}')
    if not match:
        all_ok = False

if all_ok:
    print('Benchmark validation PASSED')
else:
    print('Benchmark validation FAILED')
    exit(1)
" 2>&1
BENCHMARK_EXIT=$?
if [ $? -ne 0 ]; then
    echo "ERROR: Benchmark validation failed"
    exit 1
fi

# 5. Compare output hashes
echo ""
echo "=== Comparing output hashes ==="
HASH_EXPECTED=$(cd "$REPO_DIR" && sha256sum artifacts/og_operational_100r_fidelity/gated_benchmark.csv | cut -d' ' -f1)
HASH_PACKAGE=$(cd "$REPO_DIR" && sha256sum "$PACKAGE_DIR/ledgers/gated_benchmark.csv" | cut -d' ' -f1)
echo "  Expected hash: $HASH_EXPECTED"
echo "  Package hash: $HASH_PACKAGE"
if [ "$HASH_EXPECTED" = "$HASH_PACKAGE" ]; then
    echo "✓ Output hash match"
else
    echo "✗ Output hash MISMATCH"
    exit 1
fi

echo ""
echo "=== ALL VERIFICATIONS PASSED ==="
