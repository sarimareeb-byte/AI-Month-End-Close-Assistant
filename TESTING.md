# Testing & Validation

## Objective

A reconciliation automation tool that produces incorrect findings is worse than no tool at all — it erodes trust, wastes investigation time, and can lead to misstated financial reports. Testing this engine requires more than checking that the code runs without errors. It requires verifying that every detection rule fires on the exact transactions it should, produces the correct financial impact, and stays silent on clean data.

This document describes the controlled synthetic testing suite used to validate the prepaid expense reconciliation engine across all six major detection rules, multi-entity scenarios, materiality boundaries, and scale.

---

## Test Design

Each test case uses **controlled synthetic data** with a known correct answer. The datasets are not randomized — every transaction, schedule row, and exception is placed deliberately so the expected finding count, category, and dollar impact can be predicted before the engine runs.

Each test case folder contains three files:

| File | Purpose |
|---|---|
| `ledger.csv` | GL prepaid expense transactions matching the engine's required schema |
| `amortization_schedule.csv` | Amortization schedule rows matching the engine's required schema |
| `expected_results.md` | Documented expected findings with category counts, impact totals, and reasoning |

The engine is run against each pair of CSVs, and the output is compared against the expected results. A test case passes when the engine produces the exact expected number of findings per root cause category and the correct total financial impact.

---

## Test Case Summary

| # | Test Case | Purpose | Expected Findings | Expected Impact | Rule Tested | Result |
|---|---|---|---|---|---|---|
| 01 | Clean Company | Confirm zero false positives | 0 | $0 | Baseline — all data correct | ✅ Pass |
| 02 | Duplicate Bills | Detect duplicate invoice postings | 5 | $70,000 | Same document number posted twice as a Bill | ✅ Pass |
| 03 | Missing Amortization | Detect unposted scheduled entries | 4 | $8,000 | Schedule exists but monthly JE not posted | ✅ Pass |
| 04 | Over Amortization | Detect excess expense recognition | 3 | $1,500 | Posted amortization exceeds scheduled amount | ✅ Pass |
| 05 | Under Amortization | Detect incomplete amortization | 3 | $1,200 | Posted amortization below scheduled amount | ✅ Pass |
| 06 | Manual Adjustments | Detect out-of-process journal entries | 3 | $5,050 | JEs with reclassification/correction/write-off keywords | ✅ Pass |
| 07 | Unlinked Schedules | Detect orphaned prepaid additions | 3 | $15,800 | Bills posted with blank prepaid_item_id | ✅ Pass |
| 08 | Missing Source Invoice | Detect schedules without originating Bills | 3 | $31,500 | Schedule exists but no matching Bill in ledger | ✅ Pass |
| 09 | Multi Entity | Validate entity-level isolation | 4 | $26,000 | One exception type per entity (US, Canada, UK, Israel) | ✅ Pass |
| 10 | Materiality Thresholds | Test small vs large exception handling | 6 | $55,660 | Duplicate invoices from $10 to $50,000 | ✅ Pass |
| 11 | Large Scale Stress Test | Performance and rule-interaction test | 155 | $980,500 | All six detection rules across 3,695 ledger rows | ✅ Pass |

---

## Validation Coverage

The test suite covers every detection rule implemented in the reconciliation engine:

- **Duplicate bill detection** — verifies the engine groups Bills by entity and document number and flags groups with count > 1 (Test Cases 02, 10, 11)
- **Missing amortization JE detection** — verifies the engine compares scheduled amortization against actual journal entries per item per period and flags periods with zero postings (Test Cases 03, 11)
- **Over-amortization detection** — verifies the engine flags periods where actual amortization exceeds the scheduled amount beyond the $1.00 tolerance (Test Cases 04, 11)
- **Under-amortization detection** — verifies the engine flags periods where actual amortization falls below the scheduled amount beyond the $1.00 tolerance, provided some amortization was posted (Test Cases 05, 11)
- **Manual adjustment detection** — verifies the engine identifies negative Journal Entries containing reclassification, correction, or write-off keywords in the description field (Test Cases 06, 11)
- **Unlinked prepaid addition detection** — verifies the engine flags Bills with positive amounts and blank prepaid_item_id as additions with no amortization schedule (Test Cases 07, 09, 11)
- **Missing source invoice detection** — verifies the engine identifies amortization schedules where the prepaid_item_id has no corresponding Bill in the ledger (Test Cases 08, 09, 11)
- **Multi-entity reconciliation** — verifies that findings are correctly attributed to individual entities and that exceptions in one entity do not produce findings in another (Test Case 09)
- **Materiality testing** — verifies that the engine detects exceptions at all dollar levels from $10 to $50,000, enabling future materiality filtering (Test Case 10)
- **Large-scale performance testing** — verifies that all six detection rules fire correctly when 530 exception items are interleaved with 400 clean items across 3,695 ledger rows and 3,240 schedule rows (Test Case 11)

---

## Results

All 11 controlled test cases passed. The engine produced the exact expected number of findings per root cause category and the correct total financial impact for every test case.

Validated outputs include:

- Finding count per root cause category
- Severity classification (HIGH / MEDIUM / LOW)
- Estimated financial impact per finding
- Suggested corrective journal entries
- Entity attribution in multi-entity scenarios
- Zero false positives on clean data (Test Case 01)

---

## Known Limitations

The test suite validates core detection rules using controlled synthetic data. The following limitations should be considered:

- **Synthetic data validates rules, not real-world messiness.** The test CSVs follow the exact engine schema. Real ERP exports (NetSuite, SAP, QuickBooks) require the data adapter layer to normalize column names, date formats, and transaction type labels before the engine can process them.
- **Data quality affects output quality.** Missing vendor names, blank descriptions, and inconsistent prepaid_item_id values reduce the engine's ability to classify transactions and link findings to schedules. The adapter handles common gaps, but heavily degraded data may produce incomplete results.
- **Large finding volumes require prioritization.** Test Case 11 produces 155 findings. In production, controllers should review findings using severity and materiality filters rather than treating every finding equally.
- **Rounding tolerance is fixed at $1.00.** Over- and under-amortization detection uses a $1.00 threshold. Environments with different rounding conventions may need this adjusted.
- **The engine does not currently validate inter-period balance continuity.** Opening and closing balance checks across periods are not part of the current rule set.

---

## Next Testing Enhancements

Planned improvements to the testing framework:

- **Automated pytest suite** — wrap each test case in a pytest function that asserts exact finding counts, categories, and impact totals, runnable via `pytest test_engine.py`
- **Confidence scoring validation** — add test cases that verify confidence scores on findings where the evidence is ambiguous (e.g., partial duplicates, approximate amount matches)
- **Materiality threshold testing** — add configurable materiality filters and test that findings below threshold are suppressed without affecting above-threshold results
- **Real ERP export benchmarks** — run the adapter + engine pipeline against anonymized NetSuite, QuickBooks, and SAP exports to measure normalization accuracy and detection rates
- **Regression testing** — establish a baseline results snapshot and run it before every engine change to ensure existing detection behavior is preserved
- **Edge case coverage** — add test cases for zero-amount transactions, negative-balance schedules, single-period amortization, and mid-period schedule modifications
