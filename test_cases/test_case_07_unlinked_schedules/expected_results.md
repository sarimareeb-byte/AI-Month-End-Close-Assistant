# Test Case 07: Unlinked Schedules

## Expected Results

| Category | Count |
|---|---|
| Duplicate Bills | 0 |
| Missing Amortization | 0 |
| Over Amortization | 0 |
| Under Amortization | 0 |
| Manual Adjustments | 0 |
| Missing Source Invoice | 0 |
| Unlinked Addition | 3 |

**Expected Total Findings: 3**

**Expected Total Impact: $15,800.00**

## Reasoning

Three Bills are posted with blank prepaid_item_id:
- HubSpot $8,500
- Oracle $4,200
- SAP $3,100

The engine classifies Bills with amount > 0 and no prepaid_item_id as UNLINKED_ADDITION.
These balances will never amortize because no schedule is linked.

Total: $15,800.00
