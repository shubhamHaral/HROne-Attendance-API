# HROne Employee Attendance & Analytics API

A REST API built with Python, FastAPI, and MongoDB for employee management, attendance tracking, attendance regularization, and attendance analytics.

## Features

- Employee creation and listing
- Employee attendance punch-in and punch-out
- Attendance filtering and pagination
- Attendance regularization with an audit trail
- Monthly employee analytics
- Department attendance summaries
- Late-arrival leaderboard
- Department daily trends
- MongoDB query-plan inspection

## Requirements

- Python 3.11 or newer
- MongoDB 6.0 or newer
- Git

## Setup

### 1. Clone the repository

Replace the example URL and folder name with your actual public GitHub repository details.

```bash
git clone YOUR_PUBLIC_GITHUB_REPOSITORY_URL
cd YOUR_REPOSITORY_FOLDER
```

### 2. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### 4. Configure MongoDB

Make sure MongoDB is running and accessible.

Set the `MONGO_URI` environment variable to your MongoDB connection URI and `MONGO_DB` to the database name expected by the application. Use your own local values or deployment configuration. Do not commit secrets or `.env` files.

Example for the current PowerShell session (replace the database name if needed):

```powershell
$env:MONGO_URI = "mongodb://localhost:27017"
$env:MONGO_DB = "hrone_attendance"
```

Confirm the exact environment variable names and default database behavior against `app/main.py`.

## Run the API

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## API Documentation

With the server running:

- Swagger UI: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

## Design and Code Review

See `DECISIONS.md` for technical decisions and `REVIEW.md` for the review of the supplied starter implementation.

## Testing

Manually verify request validation, attendance calculations, regularization audit history, concurrent requests, analytics results, and MongoDB query plans. Run automated tests if provided, and document any remaining limitations accurately.