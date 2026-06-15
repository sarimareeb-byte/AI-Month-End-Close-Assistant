# Test Case 04: Over Amortization

## Expected Results

| Category | Count |
|---|---|
| Duplicate Bills | 0 |
| Missing Amortization | 0 |
| Over Amortization | 3 |
| Under Amortization | 0 |
| Manual Adjustments | 0 |
| Missing Source Invoice | 0 |
| Unlinked Schedule | 0 |

**Expected Total Findings: 3**

**Expected Total Impact: $1,500.00**

## Reasoning

Items PP-001 through PP-003 have $1,500 of actual amortization posted in Jan 2026
against a scheduled $1,000. Excess = $500 per item per period.

The engine compares actual_amortization vs scheduled_amortization per entity/item/period
and flags where actual > scheduled + $1.00 tolerance.

Total: 3 items x $500 = $1,500.

Items PP-004 through PP-006 post exact scheduled amounts — zero findings.
