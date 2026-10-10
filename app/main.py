
import os
import re
from datetime import date, datetime, timezone, timedelta
from typing import Optional
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "hrone_attendance")

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client[MONGO_DB]
employees = db["employees"]
attendance_logs = db["attendance_logs"]

app = FastAPI(title="HROne Attendance API", version="2.0.0")
IST = ZoneInfo("Asia/Kolkata")


def epoch_ms_to_datetime(value: int) -> datetime:
    """Convert epoch milliseconds to a whole-second UTC datetime."""
    seconds = value // 1000
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def to_epoch_ms(value: Optional[datetime]) -> Optional[int]:
    """Convert a datetime to epoch milliseconds, or preserve None."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


def round_hours_half_up(seconds: int) -> float:
    """Round work duration to two decimal places using half-up rounding."""
    hours = (Decimal(seconds) / Decimal(3600)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    return float(hours)


def calculate_late_minutes(
    punch_in: datetime,
    shift_start: str,
) -> int:
    """Apply the 10-minute grace period, then count whole elapsed minutes."""
    local_time = punch_in.astimezone(IST)
    start_hour, start_minute = map(int, shift_start.split(":"))

    shift_start_minutes = start_hour * 60 + start_minute
    punch_seconds = (
        local_time.hour * 3600
        + local_time.minute * 60
        + local_time.second
    )
    shift_start_seconds = shift_start_minutes * 60
    elapsed_seconds = punch_seconds - shift_start_seconds

    if elapsed_seconds <= 10 * 60:
        return 0

    return elapsed_seconds // 60

def calculate_overtime_minutes(
    punch_out: datetime,
    shift_end: str,
    overnight: bool = False,
) -> int:
    """Count whole overtime minutes only when the duration reaches 30 minutes."""
    local_out = punch_out.astimezone(IST)
    end_hour, end_minute = map(int, shift_end.split(":"))

    end_minutes = end_hour * 60 + end_minute
    out_minutes = local_out.hour * 60 + local_out.minute

    if overnight and out_minutes < end_minutes:
        out_minutes += 24 * 60

    overtime = out_minutes - end_minutes
    return overtime if overtime >= 30 else 0


@app.on_event("startup")
def create_indexes():
    client.admin.command("ping")
    employees.create_index([("emp_code", ASCENDING)], unique=True)
    attendance_logs.create_index(
        [("emp_code", ASCENDING), ("date", ASCENDING)],
        unique=True,
    )
    attendance_logs.create_index(
    [("date", ASCENDING), ("emp_code", ASCENDING)],
    )


class EmployeeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    department: str = Field(min_length=1, max_length=50)
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: date

    @field_validator("shift_start", "shift_end")
    @classmethod
    def validate_shift_time(cls, value: str) -> str:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("Time must use 24-hour HH:MM format")
        return value

    @field_validator("shift_end")
    @classmethod
    def different_shift_times(cls, value: str, info):
        if info.data.get("shift_start") == value:
            raise ValueError("shift_start and shift_end must differ")
        return value

class PunchInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    punched_at: Optional[int] = None
    status: str = "PRESENT"

    @field_validator("punched_at")
    @classmethod
    def validate_punched_at(cls, value):
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("punched_at must be an integer epoch-millisecond timestamp")
            if value < 100000000000:
                raise ValueError("punched_at must be in epoch milliseconds")
            if value > 253402300799999:
                raise ValueError("punched_at is out of range")
        return value

    @field_validator("status")
    @classmethod


    def validate_status(cls, value):
        if value not in {"PRESENT", "WFH", "ON_DUTY"}:
            raise ValueError("status must be PRESENT, WFH, or ON_DUTY")
        return value

class PunchOutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    punched_at: Optional[int] = None

    @field_validator("punched_at")
    @classmethod
    def validate_punched_at(cls, value):
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(
                    "punched_at must be an integer epoch-millisecond timestamp"
                )
            if value < 100000000000:
                raise ValueError("punched_at must be in epoch milliseconds")
            if value > 253402300799999:
                raise ValueError("punched_at is out of range")
        return value

class RegularizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        if value is not None and value not in {
            "PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"
        }:
            raise ValueError("Invalid attendance status")
        return value

    @field_validator("punch_in", "punch_out")
    @classmethod
    def validate_timestamp(cls, value):
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("Timestamp must be integer epoch milliseconds")
            if value < 100000000000 or value > 253402300799999:
                raise ValueError("Timestamp is out of range")
        return value

def employee_response(document: dict) -> dict:
    return {
        "emp_code": document["emp_code"],
        "name": document["name"],
        "email": document["email"],
        "department": document["department"],
        "shift_start": document["shift_start"],
        "shift_end": document["shift_end"],
        "joined_on": document["joined_on"],
        "created_at": int(document["created_at"].timestamp() * 1000),
    }
0

@app.get("/")
def home():
    return {"message": "HROne Attendance API is running"}


@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok"}
    except PyMongoError:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")


@app.post("/employees", status_code=201)
def create_employee(payload: EmployeeCreate):
    if payload.shift_start == payload.shift_end:
        raise HTTPException(
            status_code=422,
            detail="shift_start and shift_end must differ",
        )

    document = payload.model_dump()
    document["joined_on"] = payload.joined_on.isoformat()
    document["created_at"] = datetime.now(timezone.utc).replace(microsecond=0)

    try:
        employees.insert_one(document)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Employee code already exists")
    except PyMongoError:
        raise HTTPException(status_code=503, detail="Database operation failed")

    return employee_response(document)


@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    query = {}
    if department is not None:
        query["department"] = department

    total = employees.count_documents(query)
    cursor = (
        employees.find(query, {"_id": 0})
        .sort("emp_code", ASCENDING)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )

    return {
        "items": [employee_response(doc) for doc in cursor],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
def attendance_response(document: dict) -> dict:
    """Convert a MongoDB attendance document to the API response format."""
    result = {
        "emp_code": document["emp_code"],
        "date": document["date"],
        "status": document["status"],
        "punch_in": to_epoch_ms(document.get("punch_in")),
        "punch_out": to_epoch_ms(document.get("punch_out")),
        "work_hours": document.get("work_hours"),
        "late_minutes": document.get("late_minutes", 0),
        "overtime_minutes": document.get("overtime_minutes", 0),
        "half_day": document.get("half_day", False),
        "history": document.get("history", []),
    }

    for entry in result["history"]:
        if isinstance(entry.get("at"), datetime):
            entry["at"] = to_epoch_ms(entry["at"])
        for field in ("punch_in", "punch_out"):
            change = entry.get("changes", {}).get(field)
            if change:
                for side in ("from", "to"):
                    if isinstance(change.get(side), datetime):
                        change[side] = to_epoch_ms(change[side])

    return result




def shift_date_for_punch(
    punched_at: datetime,
    shift_start: str,
    shift_end: str,
) -> date:
    local = punched_at.astimezone(IST)

    start_hour, start_minute = map(int, shift_start.split(":"))
    end_hour, end_minute = map(int, shift_end.split(":"))

    start_minutes = start_hour * 60 + start_minute
    end_minutes = end_hour * 60 + end_minute
    local_minutes = local.hour * 60 + local.minute

    is_overnight = end_minutes <= start_minutes

    if is_overnight and local_minutes < end_minutes:
        return local.date() - timedelta(days=1)

    return local.date()



@app.post("/attendance/punch-in", status_code=201)
def punch_in(payload: PunchInRequest):
    employee = employees.find_one({"emp_code": payload.emp_code})

    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    if payload.punched_at is None:
        punched_at = datetime.now(timezone.utc).replace(microsecond=0)
    else:
        punched_at = epoch_ms_to_datetime(payload.punched_at)

    punched_at = punched_at.replace(microsecond=0)
    local = punched_at.astimezone(IST)
    attendance_date = shift_date_for_punch(
         punched_at,
    employee.get("shift_start", "09:30"),
    employee.get("shift_end", "18:30"),
    )

    late_minutes = calculate_late_minutes(
        punched_at,
        employee.get("shift_start", "09:30"),
    )

    document = {
        "emp_code": payload.emp_code,
        "date": attendance_date.isoformat(),
        "status": payload.status,
        "punch_in": punched_at,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": late_minutes,
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    try:
        attendance_logs.insert_one(document)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Attendance record already exists for this employee and date",
        )
    except PyMongoError:
        raise HTTPException(status_code=503, detail="Database operation failed")

    return attendance_response(document)

@app.post("/attendance/punch-out")
def punch_out(payload: PunchOutRequest):
    employee = employees.find_one({"emp_code": payload.emp_code})
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    if payload.punched_at is None:
        punched_at = datetime.now(timezone.utc).replace(microsecond=0)
    else:
        punched_at = epoch_ms_to_datetime(payload.punched_at)

    punched_at = punched_at.replace(microsecond=0)

    try:
        record = attendance_logs.find_one(
            {
                "emp_code": payload.emp_code,
                "punch_in": {"$lte": punched_at},
            },
            sort=[("punch_in", -1)],
        )

        if record is None:
            raise HTTPException(status_code=404, detail="No punch-in record found")

        if record.get("punch_out") is not None:
            raise HTTPException(status_code=409, detail="Attendance record is already punched out")

        punch_in_time = record["punch_in"]
        if punch_in_time.tzinfo is None:
            punch_in_time = punch_in_time.replace(tzinfo=timezone.utc)

        elapsed_seconds = (punched_at - punch_in_time).total_seconds()

        if elapsed_seconds <= 0 or elapsed_seconds > 24 * 60 * 60:
            raise HTTPException(
                status_code=422,
                detail="Punch-out must be after punch-in and within 24 hours",
            )

        work_hours = round_hours_half_up(int(elapsed_seconds))

        shift_start = employee.get("shift_start", "09:30")
        shift_end = employee.get("shift_end", "18:30")
        attendance_date = date.fromisoformat(record["date"])

        start_hour, start_minute = map(int, shift_start.split(":"))
        end_hour, end_minute = map(int, shift_end.split(":"))

        overnight = (
            end_hour * 60 + end_minute
        ) <= (
            start_hour * 60 + start_minute
        )

        shift_end_date = attendance_date
        if overnight:
            shift_end_date += timedelta(days=1)

        shift_end_local = datetime(
            shift_end_date.year,
            shift_end_date.month,
            shift_end_date.day,
            end_hour,
            end_minute,
            tzinfo=IST,
        )

        overtime_seconds = (
            punched_at.astimezone(IST) - shift_end_local
        ).total_seconds()

        overtime_minutes = (
            int(overtime_seconds // 60)
            if overtime_seconds >= 30 * 60
            else 0
        )

        half_day = work_hours < 4.50

        updated = attendance_logs.find_one_and_update(
            {
                "_id": record["_id"],
                "punch_out": None,
            },
            {
                "$set": {
                    "punch_out": punched_at,
                    "work_hours": work_hours,
                    "overtime_minutes": overtime_minutes,
                    "half_day": half_day,
                }
            },
            return_document=True,
        )

        if updated is None:
            raise HTTPException(
                status_code=409,
                detail="Attendance record was punched out by another request",
            )

        return attendance_response(updated)

    except HTTPException:
        raise
    except PyMongoError:
        raise HTTPException(status_code=503, detail="Database operation failed")


@app.get("/attendance")
def get_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from cannot be after date_to",
        )

    filters = {}

    if emp_code:
        filters["emp_code"] = emp_code

    if date_from or date_to:
        date_filter = {}
        if date_from:
            date_filter["$gte"] = date_from.isoformat()
        if date_to:
            date_filter["$lte"] = date_to.isoformat()
        filters["date"] = date_filter

    if status:
        allowed_statuses = {
            "PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"
        }
        if status not in allowed_statuses:
            raise HTTPException(
                status_code=422,
                detail="Invalid attendance status",
            )
        filters["status"] = status

    try:
        total = attendance_logs.count_documents(filters)

        cursor = (
            attendance_logs.find(filters)
            .sort([("date", -1), ("emp_code", 1)])
            .skip((page - 1) * page_size)
            .limit(page_size)
        )

        records = [
            attendance_response(document)
            for document in cursor
        ]

        return {
            "items": records,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    
    except PyMongoError as exc:
        print("TREND ERROR TYPE:", type(exc).__name__)
        print("TREND ERROR MESSAGE:", str(exc))
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        )


@app.patch("/attendance/{emp_code}/{record_date}")
def regularize_attendance(
    emp_code: str,
    record_date: date,
    payload: RegularizeRequest,
):
    from pymongo import ReturnDocument

    employee = employees.find_one({"emp_code": emp_code})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    query = {"emp_code": emp_code, "date": record_date.isoformat()}
    existing = attendance_logs.find_one(query)
    if not existing:
        raise HTTPException(status_code=404, detail="Attendance record not found")

    supplied = payload.model_fields_set
    status = payload.status if "status" in supplied else existing["status"]
    punch_in_ms = payload.punch_in if "punch_in" in supplied else (
        to_epoch_ms(existing["punch_in"]) if existing.get("punch_in") else None
    )
    punch_out_ms = payload.punch_out if "punch_out" in supplied else (
        to_epoch_ms(existing["punch_out"]) if existing.get("punch_out") else None
    )

    if status in {"ABSENT", "LEAVE"}:
        if "punch_in" in supplied or "punch_out" in supplied:
            raise HTTPException(
                status_code=422,
                detail="ABSENT or LEAVE cannot be supplied with punch times",
            )
        punch_in_ms = None
        punch_out_ms = None

    punch_in = epoch_ms_to_datetime(punch_in_ms) if punch_in_ms is not None else None
    punch_out = epoch_ms_to_datetime(punch_out_ms) if punch_out_ms is not None else None

    if status in {"PRESENT", "WFH", "ON_DUTY"} and punch_in is None:
        raise HTTPException(
            status_code=422,
            detail="Presence status requires a punch-in time",
        )

    if punch_in is not None:
        shift_start = employee.get("shift_start", "09:30")
        shift_end = employee.get("shift_end", "18:30")
        if shift_date_for_punch(punch_in, shift_start, shift_end) != record_date:
            raise HTTPException(
                status_code=422,
                detail="Punch-in does not belong to this attendance date",
            )

    if punch_out is not None:
        if punch_in is None:
            raise HTTPException(
                status_code=422,
                detail="Punch-out requires a punch-in time",
            )
        duration = (punch_out - punch_in).total_seconds()
        if duration <= 0 or duration > 24 * 60 * 60:
            raise HTTPException(
                status_code=422,
                detail="Punch-out must be after punch-in and within 24 hours",
            )

    shift_start = employee.get("shift_start", "09:30")
    shift_end = employee.get("shift_end", "18:30")

    late_minutes = 0
    work_hours = None
    overtime_minutes = 0
    half_day = False

    if punch_in is not None:
        late_minutes = calculate_late_minutes(punch_in, shift_start)

    if punch_in is not None and punch_out is not None:
        work_seconds = (punch_out - punch_in).total_seconds()
        work_hours = round_hours_half_up(work_seconds)
        half_day = work_hours < 4.50

        start_hour, start_minute = map(int, shift_start.split(":"))
        end_hour, end_minute = map(int, shift_end.split(":"))
        overnight = (end_hour * 60 + end_minute) <= (
            start_hour * 60 + start_minute
        )

        shift_end_date = record_date + timedelta(days=1) if overnight else record_date
        shift_end_local = datetime(
            shift_end_date.year,
            shift_end_date.month,
            shift_end_date.day,
            end_hour,
            end_minute,
            tzinfo=IST,
        )
        overtime_seconds = (
            punch_out.astimezone(IST) - shift_end_local
        ).total_seconds()
        if overtime_seconds >= 30 * 60:
            overtime_minutes = int(overtime_seconds // 60)

    new_values = {
        "status": status,
        "punch_in": punch_in,
        "punch_out": punch_out,
        "late_minutes": late_minutes,
        "work_hours": work_hours,
        "overtime_minutes": overtime_minutes,
        "half_day": half_day,
    }

    
    changes = {}
    for field, new_value in new_values.items():
        old_value = existing.get(field)

        if field in {"punch_in", "punch_out"}:
            if old_value is not None and new_value is not None:
                is_same = to_epoch_ms(old_value) == to_epoch_ms(new_value)
            else:
                is_same = old_value is None and new_value is None
        else:
            is_same = old_value == new_value

        if not is_same:
            changes[field] = {
                "from": old_value,
                "to": new_value,
            }


    if not changes:
        raise HTTPException(status_code=422, detail="Patch makes no changes")

    history_entry = {
        "at": datetime.now(timezone.utc),
        "by": payload.regularized_by,
        "reason": payload.reason,
        "changes": changes,
    }

    expected = {
        "_id": existing["_id"],
        "status": existing["status"],
        "punch_in": existing.get("punch_in"),
        "punch_out": existing.get("punch_out"),
        "history": existing.get("history", []),
    }

    try:
        updated = attendance_logs.find_one_and_update(
            expected,
            {
                "$set": new_values,
                "$push": {"history": history_entry},
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise HTTPException(
                status_code=409,
                detail="Attendance changed concurrently; retry the request",
            )
        return attendance_response(updated)
    except PyMongoError:
        raise HTTPException(status_code=503, detail="Database operation failed")


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly_analytics(
    emp_code: str,
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
):
    employee = employees.find_one({"emp_code": emp_code})
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    year, month_number = map(int, month.split("-"))
    start_date = date(year, month_number, 1)

    if month_number == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month_number + 1, 1)

    # Count weekdays from the employee's joining date through month-end.
    joined_on = date.fromisoformat(employee["joined_on"])
    period_start = max(start_date, joined_on)
    period_end = end_date - timedelta(days=1)

    working_days = 0
    current_day = period_start
    while current_day <= period_end:
        if current_day.weekday() < 5:
            working_days += 1
        current_day += timedelta(days=1)

    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {
                    "$gte": start_date.isoformat(),
                    "$lt": end_date.isoformat(),
                },
            }
        },
        {
            "$group": {
                "_id": None,
                "total_records": {"$sum": 1},
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$status",
                                            ["PRESENT", "WFH", "ON_DUTY"],
                                        ]
                                    },
                                    {
                                        "$in": [
                                            {
                                                "$dayOfWeek": {
                                                    "$dateFromString": {
                                                        "dateString": "$date"
                                                    }
                                                }
                                            },
                                            [2, 3, 4, 5, 6],
                                        ]
                                    },
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$half_day", True]},
                                    0.5,
                                    1,
                                ]
                            },
                            0,
                        ]
                    }
                },
                "late_minutes": {"$sum": "$late_minutes"},
                "overtime_minutes": {"$sum": "$overtime_minutes"},
                "work_hours": {
                    "$sum": {"$ifNull": ["$work_hours", 0]}
                },
            }
        },
    ]

    try:
        result = list(attendance_logs.aggregate(pipeline))
        summary = result[0] if result else {
            "total_records": 0,
            "present_days": 0,
            "late_minutes": 0,
            "overtime_minutes": 0,
            "work_hours": 0,
        }
        summary.pop("_id", None)

        present_days = summary["present_days"]
        attendance_rate = (
            round(present_days / working_days, 4)
            if working_days > 0
            else 0.0
        )

        return {
            "emp_code": emp_code,
            "month": month,
            "department": employee["department"],
            "working_days": working_days,
            **summary,
            "work_hours": round(summary["work_hours"] + 1e-9, 2),
            "attendance_rate": attendance_rate,
        }

    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database operation failed",
        )

 
@app.get("/analytics/departments/summary")
def department_attendance_summary(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
):
    year, month_number = map(int, month.split("-"))
    start_date = date(year, month_number, 1)

    if month_number == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month_number + 1, 1)

    period_end = end_date - timedelta(days=1)

    try:
        # Include employees who have no attendance records.
        pipeline = [
            {
                "$match": {
                    "joined_on": {"$lte": period_end.isoformat()}
                }
            },
            {
                "$lookup": {
                    "from": attendance_logs.name,
                    "let": {"employee_code": "$emp_code"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$emp_code", "$$employee_code"]},
                                        {"$gte": ["$date", start_date.isoformat()]},
                                        {"$lt": ["$date", end_date.isoformat()]},
                                    ]
                                }
                            }
                        },
                        {
                            "$group": {
                                "_id": None,
                                "present_days": {
                                    "$sum": {
                                        "$cond": [
                                            {
                                                "$and": [
                                                    {
                                                        "$in": [
                                                            "$status",
                                                            ["PRESENT", "WFH", "ON_DUTY"],
                                                        ]
                                                    },
                                                    {
                                                        "$in": [
                                                            {
                                                                "$dayOfWeek": {
                                                                    "$dateFromString": {
                                                                        "dateString": "$date"
                                                                    }
                                                                }
                                                            },
                                                            [2, 3, 4, 5, 6],
                                                        ]
                                                    },
                                                ]
                                            },
                                            {
                                                "$cond": [
                                                    {"$eq": ["$half_day", True]},
                                                    0.5,
                                                    1,
                                                ]
                                            },
                                            0,
                                        ]
                                    }
                                },
                                "late_minutes": {"$sum": "$late_minutes"},
                                "overtime_minutes": {"$sum": "$overtime_minutes"},
                                "work_hours": {
                                    "$sum": {"$ifNull": ["$work_hours", 0]}
                                },
                            }
                        },
                    ],
                    "as": "attendance",
                }
            },
            {
                "$set": {
                    "attendance": {
                        "$ifNull": [
                            {"$arrayElemAt": ["$attendance", 0]},
                            {
                                "present_days": 0,
                                "late_minutes": 0,
                                "overtime_minutes": 0,
                                "work_hours": 0,
                            },
                        ]
                    }
                }
            },
            {
                "$group": {
                    "_id": "$department",
                    "headcount": {"$sum": 1},
                    "present_days": {"$sum": "$attendance.present_days"},
                    "late_minutes": {"$sum": "$attendance.late_minutes"},
                    "overtime_minutes": {"$sum": "$attendance.overtime_minutes"},
                    "work_hours": {"$sum": "$attendance.work_hours"},
                }
            },
            {"$sort": {"_id": 1}},
        ]

        results = list(employees.aggregate(pipeline))
        departments = []

        for item in results:
            # Calculate weekday working days after each employee joined.
            working_days = 0
            for employee in employees.find(
                {
                    "department": item["_id"],
                    "joined_on": {"$lte": period_end.isoformat()},
                },
                {"joined_on": 1},
            ):
                joined_on = date.fromisoformat(employee["joined_on"])
                current_day = max(start_date, joined_on)

                while current_day <= period_end:
                    if current_day.weekday() < 5:
                        working_days += 1
                    current_day += timedelta(days=1)

            present_days = item["present_days"]
            departments.append(
                {
                    "department": item["_id"],
                    "headcount": item["headcount"],
                    "working_days": working_days,
                    "present_days": present_days,
                    "attendance_rate": (
                        round(present_days / working_days, 4)
                        if working_days > 0
                        else 0.0
                    ),
                    "late_minutes": item["late_minutes"],
                    "overtime_minutes": item["overtime_minutes"],
                    "work_hours": round(item["work_hours"] + 1e-9, 2),
                }
            )

        return {"month": month, "departments": departments}

    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database operation failed",
        )
@app.get("/analytics/leaderboard/late")
def late_arrival_leaderboard(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    limit: int = Query(10, ge=1, le=100),
):
    year, month_number = map(int, month.split("-"))
    start_date = date(year, month_number, 1)

    if month_number == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month_number + 1, 1)

    try:
        pipeline = [
            {
                "$match": {
                    "date": {
                        "$gte": start_date.isoformat(),
                        "$lt": end_date.isoformat(),
                    }
                }
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_late_minutes": {"$sum": "$late_minutes"},
                }
            },
            {
                "$lookup": {
                    "from": employees.name,
                    "localField": "_id",
                    "foreignField": "emp_code",
                    "as": "employee",
                }
            },
            {"$unwind": "$employee"},
            {
"$setWindowFields": {
    "sortBy": {
        "total_late_minutes": -1,
    },
    "output": {
        "rank": {
            "$rank": {},
        }
    },
}

            },
            {"$match": {"rank": {"$lte": limit}}},
            {
                "$project": {
                    "_id": 0,
                    "emp_code": "$_id",
                    "name": "$employee.name",
                    "department": "$employee.department",
                    "total_late_minutes": 1,
                    "rank": 1,
                }
            },
            {"$sort": {"rank": 1, "emp_code": 1}},
        ]

        results = list(attendance_logs.aggregate(pipeline))
        print("TREND RESULTS:", results)
        return {"month": month, "limit": limit, "leaderboard": results}
    except PyMongoError:
        raise HTTPException(status_code=503, detail="Database operation failed")

@app.get("/analytics/departments/{department}/trend")
def department_attendance_trend(
    department: str,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
):
    if to_date < from_date:
        raise HTTPException(status_code=422, detail="to cannot be before from")

    if (to_date - from_date).days + 1 > 92:
        raise HTTPException(status_code=422, detail="Date range cannot exceed 92 days")

    try:
        if employees.count_documents({"department": department}) == 0:
            raise HTTPException(status_code=404, detail="Unknown department")

        pipeline = [
            {"$match": {"date": {"$gte": from_date.isoformat(), "$lte": to_date.isoformat()}}},
            {"$lookup": {"from": "employees", "localField": "emp_code", "foreignField": "emp_code", "as": "employee"}},
            {"$unwind": "$employee"},
            {"$match": {"employee.department": department}},
            {"$set": {
                "_day": {"$dateFromString": {"dateString": "$date"}},
                "_presence": {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
            }},
            {"$group": {
                "_id": "$_day",
                "present_count": {"$sum": {"$cond": [
                    "$_presence", {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]}, 0
                ]}},
                "late_count": {"$sum": {"$cond": [
                    {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0
                ]}},
            }},
            {"$densify": {"field": "_id", "range": {
                "step": 1, "unit": "day",
                "bounds": [
                    datetime.combine(from_date, datetime.min.time()),
                    datetime.combine(to_date + timedelta(days=1), datetime.min.time()),
                ],
            }}},
            {"$fill": {"output": {"present_count": {"value": 0}, "late_count": {"value": 0}}}},
            {"$set": {
                "date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$_id"}},
                "weekday": {"$dayOfWeek": "$_id"},
            }},
            {"$lookup": {"from": "employees", "let": {"day": "$date"}, "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$department", department]},
                    {"$lte": ["$joined_on", "$$day"]},
                ]}}},
                {"$count": "count"},
            ], "as": "hc"}},
            {"$set": {
                "headcount": {"$ifNull": [{"$arrayElemAt": ["$hc.count", 0]}, 0]},
                "is_working_day": {"$and": [
                    {"$gte": ["$weekday", 2]}, {"$lte": ["$weekday", 6]}
                ]},
            }},
            {"$set": {"attendance_rate": {"$cond": [
                {"$and": ["$is_working_day", {"$gt": ["$headcount", 0]}]},
                {"$round": [{"$divide": ["$present_count", "$headcount"]}, 4]},
                None,
            ]}}},
            {"$setWindowFields": {"sortBy": {"_id": 1}, "output": {
                "moving_avg_7d": {"$avg": "$attendance_rate", "window": {"documents": [-6, 0]}}
            }}},
            {"$project": {
                "_id": 0, "date": 1, "is_working_day": 1, "headcount": 1,
                "present_count": 1, "late_count": 1, "attendance_rate": 1,
                "moving_avg_7d": {"$round": ["$moving_avg_7d", 4]},
            }},
            {"$sort": {"date": 1}},
        ]

        items = list(attendance_logs.aggregate(pipeline))
        for item in items:
            for key in ("attendance_rate", "moving_avg_7d"):
                if item.get(key) is not None:
                    item[key] = float(Decimal(str(item[key])).quantize(
                        Decimal("0.0001"), rounding=ROUND_HALF_UP
                    ))

        return {"department": department, "items": items}

    except PyMongoError:
        raise HTTPException(status_code=503, detail="Database operation failed")


@app.get("/admin/explain/{endpoint}")
def explain_query_plan(endpoint: str):
    allowed_endpoints = {
        "attendance": {
            "emp_code": "EMP0001",
            "date": "2026-10-10",
        },
        "employee": {
            "emp_code": "EMP0001",
        },
    }

    if endpoint not in allowed_endpoints:
        raise HTTPException(
            status_code=422,
            detail="Supported endpoints: attendance, employee",
        )

    try:
        if endpoint == "attendance":
            query = {
                "emp_code": allowed_endpoints["attendance"]["emp_code"],
                "date": allowed_endpoints["attendance"]["date"],
            }
            explanation = attendance_logs.find(query).explain()
        else:
            query = allowed_endpoints["employee"]
            explanation = employees.find(query).explain()

        def find_stages(value):
            stages = []
            if isinstance(value, dict):
                stage_name = value.get("stage")
                if stage_name:
                    stages.append(stage_name)
                for child in value.values():
                    stages.extend(find_stages(child))
            elif isinstance(value, list):
                for child in value:
                    stages.extend(find_stages(child))
            return stages

        stages = find_stages(explanation)

        return {
            "endpoint": endpoint,
            "query": query,
            "stages": sorted(set(stages)),
            "uses_index": any("IXSCAN" in stage for stage in stages),
            "has_collection_scan": "COLLSCAN" in stages,
            "explain": explanation,
        }
    
    
        
    except PyMongoError as exc:
        print("TREND ERROR TYPE:", type(exc).__name__)
        print("TREND ERROR MESSAGE:", str(exc))
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        )




