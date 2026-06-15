# Test Case 06: Manual Adjustments

## Expected Results

| Category | Count |
|---|---|
| Duplicate Bills | 0 |
| Missing Amortization | 0 |
| Over Amortization | 0 |
| Under Amortization | 0 |
| Manual Adjustments | 3 |
| Missing Source Invoice | 0 |
| Unlinked Schedule | 0 |

**Expected Total Findings: 3**

**Expected Total Impact: $5,050.00**

## Reasoning

Three Journal Entries with negative amounts contain manual adjustment keywords:
- "Reclassification" ($2,500)
- "Correction" ($1,800)
- "Write-off" ($750)

The engine classifies JEs with amount < 0 and keywords like "reclassif", "correction",
"write-off" as MANUAL_ADJUSTMENT. Each generates one finding.

Total: $5,050.00
