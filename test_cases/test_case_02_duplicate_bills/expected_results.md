# Test Case 02: Duplicate Bills

## Expected Results

| Category | Count |
|---|---|
| Duplicate Bills | 5 |
| Missing Amortization | 0 |
| Over Amortization | 0 |
| Under Amortization | 0 |
| Manual Adjustments | 0 |
| Missing Source Invoice | 0 |
| Unlinked Schedule | 0 |

**Expected Total Findings: 5**

**Expected Total Impact: $70,000.00**

## Reasoning

Items PP-001 through PP-005 each have the same document_number posted twice
as a Bill in the ledger. The engine groups Bills by (entity, document_number)
and flags groups with count > 1. Impact per duplicate = original invoice amount.

Items PP-006 through PP-010 are clean — single Bill, proper schedule, all JEs posted.

Duplicate amounts: $12,000.00, $13,000.00, $14,000.00, $15,000.00, $16,000.00
