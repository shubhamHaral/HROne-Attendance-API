# Technical Decisions

## 1. Technology Stack

- **Python:** Implements the API and attendance business rules.
- **FastAPI:** Provides REST endpoints, request validation, and Swagger documentation.
- **MongoDB:** Stores employee records and attendance history.
- **PyMongo:** Executes database queries, aggregation pipelines, and index operations.

## 2. Database Indexes

- A unique index on `employees.emp_code` prevents duplicate employee codes.
- A unique compound index on `attendance_logs.emp_code` and `attendance_logs.date` ensures one attendance record per employee per day.
- A date-and-employee index supports date-based attendance searches and sorting.
- Indexes are created during application startup.

## 3. Concurrency and Data Integrity

- Punch-in relies on the unique compound index to prevent duplicate daily records during concurrent requests.
- Punch-out uses a conditional database update so only one request can close an attendance record.
- Regularization uses a conditional update and appends an audit entry in the same database operation.
- Failed concurrent updates return a conflict response rather than silently overwriting another change.

## 4. Time and Attendance Calculations

- API timestamps are accepted and returned as epoch milliseconds.
- Attendance dates and shift calculations use the Asia/Kolkata timezone.
- Punch timestamps are truncated to whole seconds before calculations.
- Work hours use half-up rounding to two decimal places.
- Late arrival, overtime, and half-day calculations follow the assignment rules.

## 5. Analytics

- Analytics use MongoDB aggregation pipelines to avoid loading the entire attendance collection into application memory.
- Stored derived attendance values are used for reporting rather than recalculated during analytics.
- Employees without attendance records must still be included in applicable headcount calculations.
- Working-day calculations use Monday through Friday and account for employee joining dates.
- Leaderboard ties use standard competition ranking, with tied employees included at the rank cutoff.

## 6. Scaling

For larger attendance datasets, I would validate query plans with MongoDB `explain`, monitor index usage, and add compound indexes based on actual query patterns. Aggregations should filter records early and avoid unnecessary collection-wide joins.
