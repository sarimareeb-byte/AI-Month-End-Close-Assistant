# Test Case 10: Materiality Thresholds

## Expected Results

| Category | Count |
|---|---|
| Duplicate Bills | 6 |

| Item | Amount | Impact |
|---|---|---|
| PP-001 | $10.00 | $10.00 |
| PP-002 | $50.00 | $50.00 |
| PP-003 | $100.00 | $100.00 |
| PP-004 | $500.00 | $500.00 |
| PP-005 | $5,000.00 | $5,000.00 |
| PP-006 | $50,000.00 | $50,000.00 |

**Expected Total Findings: 6**

**Expected Total Impact: $55,660.00**

## Reasoning

Six duplicate bills at varying materiality levels from $10 to $50,000.
All are technically duplicate exceptions regardless of size. This test case
enables future materiality filtering — a controller might filter findings
below $500 to focus on material items only.
