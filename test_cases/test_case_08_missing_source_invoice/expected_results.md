# Test Case 08: Missing Source Invoice

## Expected Results

| Category | Count |
|---|---|
| Duplicate Bills | 0 |
| Missing Amortization | 0 |
| Over Amortization | 0 |
| Under Amortization | 0 |
| Manual Adjustments | 0 |
| Missing Source Invoice | 3 |
| Unlinked Schedule | 0 |

**Expected Total Findings: 3**

**Expected Total Impact: $31,500.00**

## Reasoning

Three amortization schedules reference prepaid_item_ids (PP-ORPHAN-001/002/003)
with no matching Bill in the ledger. The engine detects these as MISSING_ORIGINAL_BILL.

Amounts: $9,000 + $15,000 + $7,500 = $31,500.00
