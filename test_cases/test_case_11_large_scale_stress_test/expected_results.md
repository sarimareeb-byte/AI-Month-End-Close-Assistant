# Test Case 11: Large Scale Stress Test

## Data Volume

| Metric | Count |
|---|---|
| Ledger rows | ~3,695 |
| Schedule rows | ~3,240 |
| Clean items | 400 |
| Items with exceptions | 130 |

## Expected Results

| Category | Count | Impact |
|---|---|---|
| Duplicate Bills | 50 | $625,000.00 |
| Missing Amortization | 40 | $80,000.00 |
| Over Amortization | 20 | $10,000.00 |
| Under Amortization | 20 | $8,000.00 |
| Manual Adjustments | 15 | $67,500.00 |
| Missing Source Invoice | 10 | $190,000.00 |

**Expected Total Findings: 155**

**Expected Total Impact: $980,500.00**

## Reasoning

- **400 clean items**: proper Bills, full 6-period schedules, all JEs posted
- **50 duplicates**: same document_number posted twice as Bills
- **40 missing amortization**: schedules exist, last 2 periods have no JE
- **20 over amortization**: posted $1,500 in Jan 2026 vs scheduled $1,000
- **20 under amortization**: posted $600 in Dec 2025 vs scheduled $1,000
- **15 manual adjustments**: JEs with "Reclassification" keyword
- **10 missing source**: orphan schedules with no Bill in ledger

This stress test validates engine performance at scale and ensures all six
detection rules fire correctly when interleaved with clean data.
