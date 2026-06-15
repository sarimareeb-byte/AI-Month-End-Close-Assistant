# Test Case 05: Under Amortization

## Expected Results

| Category | Count |
|---|---|
| Duplicate Bills | 0 |
| Missing Amortization | 0 |
| Over Amortization | 0 |
| Under Amortization | 3 |
| Manual Adjustments | 0 |
| Missing Source Invoice | 0 |
| Unlinked Schedule | 0 |

**Expected Total Findings: 3**

**Expected Total Impact: $1,200.00**

## Reasoning

Items PP-001 through PP-003 posted $600 of amortization in Dec 2025 vs scheduled $1,000.
Shortfall = $400 per item. The engine flags this as UNDER_AMORTIZATION because
actual > 0 AND actual < scheduled - $1.00 tolerance.

Total: 3 items x $400 = $1,200.

Items PP-004 through PP-006 post exact scheduled amounts — zero findings.
