# Starter Code Review

## 1. Overview

I reviewed the attendance API for correctness, validation, data integrity, concurrency, analytics, and MongoDB query performance. The review focused on attendance calculations, ranking behavior, trend generation, and query-plan reporting.

## 2. Defects Found

### Defect 1: Incorrect leaderboard tie handling

- **Location:** `app/main.py` — `late_arrival_leaderboard`
- **Problem:** Including the employee code in the ranking sort can cause employees with equal total late minutes to receive different ranks.
- **Impact:** Employees with the same score should receive the same competition rank.
- **Fix:** Use only total late minutes in the ranking window's sort criteria. Apply employee code as a separate sort criterion for deterministic output ordering.
- **Verification:** Review the ranking pipeline and test multiple employees with equal late-minute totals before submission.

### Defect 2: Employee query-plan index detection

- **Location:** `app/main.py` — employee explain endpoint
- **Problem:** Checking only for the exact stage name `IXSCAN` misses other index-scan stage names, such as `EXPRESS_IXSCAN`.
- **Impact:** The endpoint can incorrectly report that an index is not being used.
- **Fix:** Detect index usage by checking whether any reported stage name contains `IXSCAN`.
- **Verification:** A request to `/admin/explain/employee` returned `uses_index: True` and `has_collection_scan: False` for `EMP0001`.

## 3. Other Behaviors Checked

- The attendance explain endpoint returned `uses_index: True` and `has_collection_scan: False`.
- The employee list, attendance list, monthly analytics, department summary, and department trend endpoints returned responses during manual testing.
- These successful requests establish basic endpoint behavior but do not replace automated tests or boundary-case testing.

## 4. Remaining Validation

Before submission, verify attendance and half-day rules, regularization audit history, duplicate and concurrent punch requests, leaderboard ties, date-range boundaries, analytics for employees without logs, and request validation. Confirm the behavior against the assignment's `openapi.yaml`.