# Test Case 09: Multi Entity

## Expected Results

| Entity | Issue | Count | Impact |
|---|---|---|---|
| US Corp | Duplicate Bill | 1 | $6,000 |
| Canada Ltd | Unlinked Addition | 1 | $5,000 |
| UK PLC | Manual Adjustment | 1 | $3,000 |
| Israel Ltd | Missing Source Invoice | 1 | $12,000 |

**Expected Total Findings: 4**

**Expected Total Impact: $26,000.00**

## Reasoning

Each entity has 3 clean prepaid items plus one specific exception type:
- US Corp: INV-9000 posted twice — duplicate bill
- Canada Ltd: INV-UNLINKED-CA posted with blank prepaid_item_id — unlinked addition
- UK PLC: JE-ADJ-UK with "Reclassification" keyword — manual adjustment
- Israel Ltd: Schedule S-IL-ORPHAN with no matching Bill in ledger — missing source invoice

This tests that entity isolation works correctly — each finding is attributed
to the right entity.
