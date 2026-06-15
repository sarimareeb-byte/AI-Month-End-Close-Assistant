# Test Case 03: Missing Amortization

## Expected Results

| Category | Count |
|---|---|
| Duplicate Bills | 0 |
| Missing Amortization | 4 |
| Over Amortization | 0 |
| Under Amortization | 0 |
| Manual Adjustments | 0 |
| Missing Source Invoice | 0 |
| Unlinked Schedule | 0 |

**Expected Total Findings: 4**

**Expected Total Impact: $8,000.00**

## Reasoning

Items PP-001 through PP-004 each have amortization JEs for Oct–Dec 2025 and Jan 2026,
but are **missing** JEs for Feb 2026 and Mar 2026. Each missing period = $1,000.
The engine consolidates missing periods per item, so 4 findings (one per item),
each with impact of $2,000 (2 missed periods x $1,000).

Total: 4 items x $2,000 = $8,000.

Items PP-005 through PP-008 have all 6 JEs posted — zero findings.
