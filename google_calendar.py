import base64
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from google.auth.transport.requests import Request

load_dotenv()
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _bootstrap_token() -> None:
    encoded = os.getenv("GOOGLE_TOKEN_BASE64")
    if not encoded:
        return
    token_path = os.getenv("GOOGLE_TOKEN_PATH", "token.json")
    if not os.path.exists(token_path):
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(base64.b64decode(encoded).decode("utf-8"))


_bootstrap_token()


def _get_env() -> dict[str, str]:
    return {
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
        "calendar_id": os.getenv("GOOGLE_CALENDAR_ID", "primary"),
        "token_path": os.getenv("GOOGLE_TOKEN_PATH", "token.json"),
        "timezone": os.getenv("TIMEZONE", "UTC"),
    }


def _get_credentials() -> Credentials:
    env = _get_env()
    token_path = env["token_path"]
    creds: Credentials | None = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": env["client_id"],
                    "client_secret": env["client_secret"],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            SCOPES,
        )
        creds = flow.run_local_server(port=0)

    with open(token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    return creds


def _service() -> Any:
    return build("calendar", "v3", credentials=_get_credentials())


def _get_timezone() -> ZoneInfo:
    env = _get_env()
    try:
        return ZoneInfo(env["timezone"])
    except Exception:
        return ZoneInfo("UTC")


def _parse_user_datetime(value: str) -> datetime:
    local_tz = _get_timezone()
    cleaned = value.strip()
    has_explicit_offset = (
        cleaned.endswith("Z")
        or "+" in cleaned[10:]
        or (cleaned.count("-") > 2)
    )
    normalized = cleaned.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None or not has_explicit_offset:
        dt = dt.replace(tzinfo=None).replace(tzinfo=local_tz)
    return dt


def _ensure_not_past(start_dt: datetime) -> None:
    now = datetime.now(start_dt.tzinfo or timezone.utc)
    if start_dt < now:
        raise ValueError("Cannot schedule or reschedule meetings in the past")


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _event_belongs_to_client(event: dict[str, Any], client_email: str) -> bool:
    normalized = _normalize_email(client_email)
    attendees = event.get("attendees", [])
    for attendee in attendees:
        attendee_email = attendee.get("email")
        if isinstance(attendee_email, str) and _normalize_email(attendee_email) == normalized:
            return True
    private = event.get("extendedProperties", {}).get("private", {})
    stored_email = private.get("client_email")
    if isinstance(stored_email, str) and _normalize_email(stored_email) == normalized:
        return True
    return False


def _get_event_by_id(event_id: str) -> dict[str, Any]:
    env = _get_env()
    return _service().events().get(calendarId=env["calendar_id"], eventId=event_id).execute()


def _find_conflict(
    start_dt: datetime,
    end_dt: datetime,
    *,
    exclude_event_id: str | None = None,
) -> bool:
    env = _get_env()
    events = (
        _service()
        .events()
        .list(
            calendarId=env["calendar_id"],
            timeMin=start_dt.isoformat(),
            timeMax=end_dt.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
        .get("items", [])
    )
    for event in events:
        if exclude_event_id and event.get("id") == exclude_event_id:
            continue
        start_info = event.get("start", {})
        end_info = event.get("end", {})
        if not start_info.get("dateTime") or not end_info.get("dateTime"):
            return True
        event_start = _parse_user_datetime(start_info["dateTime"])
        event_end = _parse_user_datetime(end_info["dateTime"])
        if start_dt < event_end and end_dt > event_start:
            return True
    return False


def _busy_ranges_for_day(
    target_date: date,
    *,
    exclude_event_id: str | None = None,
) -> list[tuple[datetime, datetime]]:
    env = _get_env()
    tz = _get_timezone()
    work_start = datetime.combine(target_date, time(10, 0), tzinfo=tz)
    work_end = datetime.combine(target_date, time(19, 0), tzinfo=tz)
    events = (
        _service()
        .events()
        .list(
            calendarId=env["calendar_id"],
            timeMin=work_start.isoformat(),
            timeMax=work_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
        .get("items", [])
    )
    busy_ranges: list[tuple[datetime, datetime]] = []
    for event in events:
        if exclude_event_id and event.get("id") == exclude_event_id:
            continue
        start_info = event.get("start", {})
        end_info = event.get("end", {})
        if start_info.get("dateTime") and end_info.get("dateTime"):
            start_dt = _parse_user_datetime(start_info["dateTime"]).astimezone(tz)
            end_dt = _parse_user_datetime(end_info["dateTime"]).astimezone(tz)
        elif start_info.get("date") and end_info.get("date"):
            start_day = _parse_user_date(start_info["date"])
            end_day = _parse_user_date(end_info["date"])
            if start_day <= target_date < end_day:
                start_dt = work_start
                end_dt = work_end
            else:
                continue
        else:
            continue
        if end_dt <= work_start or start_dt >= work_end:
            continue
        busy_ranges.append((max(start_dt, work_start), min(end_dt, work_end)))
    busy_ranges.sort(key=lambda x: x[0])
    merged_ranges: list[tuple[datetime, datetime]] = []
    for start_dt, end_dt in busy_ranges:
        if not merged_ranges or start_dt > merged_ranges[-1][1]:
            merged_ranges.append((start_dt, end_dt))
        else:
            prev_start, prev_end = merged_ranges[-1]
            merged_ranges[-1] = (prev_start, max(prev_end, end_dt))
    return merged_ranges


def _would_create_four_in_row(
    start_dt: datetime,
    *,
    exclude_event_id: str | None = None,
) -> bool:
    tz = _get_timezone()
    local_start = start_dt.astimezone(tz)
    target_date = local_start.date()
    work_start = datetime.combine(target_date, time(10, 0), tzinfo=tz)
    work_end = datetime.combine(target_date, time(19, 0), tzinfo=tz)
    if local_start < work_start or local_start + timedelta(hours=1) > work_end:
        return False
    busy_ranges = _busy_ranges_for_day(target_date, exclude_event_id=exclude_event_id)
    occupied: list[bool] = []
    for i in range(9):
        slot_start = work_start + timedelta(hours=i)
        slot_end = slot_start + timedelta(hours=1)
        is_busy = any(slot_start < busy_end and slot_end > busy_start for busy_start, busy_end in busy_ranges)
        occupied.append(is_busy)
    candidate_index = int((local_start - work_start).total_seconds() // 3600)
    if 0 <= candidate_index < len(occupied):
        occupied[candidate_index] = True
    for i in range(len(occupied) - 3):
        if occupied[i] and occupied[i + 1] and occupied[i + 2] and occupied[i + 3]:
            return True
    return False


def _next_available_slot(after_dt: datetime, *, exclude_event_id: str | None = None) -> datetime | None:
    tz = _get_timezone()
    current = after_dt.astimezone(tz).replace(minute=0, second=0, microsecond=0)
    if after_dt.astimezone(tz).minute > 0 or after_dt.astimezone(tz).second > 0:
        current += timedelta(hours=1)

    for _ in range(30):
        if current.weekday() > 4:
            days_ahead = 7 - current.weekday()
            current = datetime.combine((current + timedelta(days=days_ahead)).date(), time(10, 0), tzinfo=tz)
            continue
        work_start = current.replace(hour=10, minute=0, second=0, microsecond=0)
        work_end = current.replace(hour=19, minute=0, second=0, microsecond=0)
        if current < work_start:
            current = work_start
        if current + timedelta(minutes=60) > work_end:
            current = datetime.combine((current + timedelta(days=1)).date(), time(10, 0), tzinfo=tz)
            continue
        if (
            not _find_conflict(current, current + timedelta(minutes=60), exclude_event_id=exclude_event_id)
            and not _would_create_four_in_row(current, exclude_event_id=exclude_event_id)
        ):
            return current
        current += timedelta(hours=1)
    return None


def _parse_user_date(value: str) -> date:
    text = value.strip()
    try:
        return datetime.strptime(text, "%d-%m-%Y").date()
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Date must be in YYYY-MM-DD format") from exc


def get_available_time(date_iso: str, duration_minutes: int = 60) -> dict[str, Any]:
    env = _get_env()
    if duration_minutes != 60:
        raise ValueError("Meeting duration must be exactly 60 minutes")
    tz = _get_timezone()
    target_date = _parse_user_date(date_iso)

    if target_date.weekday() > 4:
        return {
            "date": target_date.isoformat(),
            "timezone": env["timezone"],
            "working_hours": "10:00-19:00",
            "available_slots": [],
            "message": "No available time. Working days are Monday to Friday.",
        }

    work_start = datetime.combine(target_date, time(10, 0), tzinfo=tz)
    work_end = datetime.combine(target_date, time(19, 0), tzinfo=tz)
    merged_ranges = _busy_ranges_for_day(target_date)

    slot_size = timedelta(minutes=duration_minutes)
    cursor = work_start
    available_slots: list[str] = []
    while cursor + slot_size <= work_end:
        slot_end = cursor + slot_size
        overlaps = any(cursor < busy_end and slot_end > busy_start for busy_start, busy_end in merged_ranges)
        if not overlaps and not _would_create_four_in_row(cursor):
            available_slots.append(cursor.strftime("%H:%M"))
        cursor += timedelta(minutes=60)

    def _format_range(start_dt: datetime, end_dt: datetime) -> str:
        if end_dt - start_dt == timedelta(hours=1):
            return start_dt.strftime("%H:%M")
        return f"{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}"

    available_ranges: list[str] = []
    if available_slots:
        range_start = datetime.combine(target_date, datetime.strptime(available_slots[0], "%H:%M").time(), tzinfo=tz)
        prev = range_start
        for slot in available_slots[1:]:
            current = datetime.combine(target_date, datetime.strptime(slot, "%H:%M").time(), tzinfo=tz)
            if current - prev == timedelta(hours=1):
                prev = current
                continue
            available_ranges.append(_format_range(range_start, prev + timedelta(hours=1)))
            range_start = current
            prev = current
        available_ranges.append(_format_range(range_start, prev + timedelta(hours=1)))

    return {
        "date": target_date.isoformat(),
        "timezone": env["timezone"],
        "working_hours": "10:00-19:00",
        "available_slots": available_ranges,
    }


def _weekdays_for_offset(weeks_ahead: int) -> list[date]:
    tz = _get_timezone()
    today = datetime.now(tz).date()
    monday = today - timedelta(days=today.weekday()) + timedelta(days=7 * weeks_ahead)
    days = [monday + timedelta(days=i) for i in range(5)]
    if weeks_ahead == 0:
        return [d for d in days if d >= today]
    return days


def get_available_time_this_week() -> dict[str, Any]:
    env = _get_env()
    days = _weekdays_for_offset(0)
    availability = [get_available_time(day.isoformat(), 60) for day in days]
    return {
        "period": "this_week",
        "timezone": env["timezone"],
        "working_hours": "10:00-19:00",
        "days": availability,
    }


def get_available_time_next_week() -> dict[str, Any]:
    env = _get_env()
    days = _weekdays_for_offset(1)
    availability = [get_available_time(day.isoformat(), 60) for day in days]
    return {
        "period": "next_week",
        "timezone": env["timezone"],
        "working_hours": "10:00-19:00",
        "days": availability,
    }


def get_client_meetings(client_email: str, max_results: int = 20) -> dict[str, Any]:
    env = _get_env()
    now = datetime.now(timezone.utc).isoformat()
    events = (
        _service()
        .events()
        .list(
            calendarId=env["calendar_id"],
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
        .get("items", [])
    )
    meetings: list[dict[str, str]] = []
    for event in events:
        if not _event_belongs_to_client(event, client_email):
            continue
        start = event.get("start", {}).get("dateTime", event.get("start", {}).get("date", ""))
        meetings.append(
            {
                "id": event.get("id", ""),
                "summary": event.get("summary", "(no title)"),
                "start": start,
                "htmlLink": event.get("htmlLink", ""),
            }
        )
    return {"client_email": client_email, "meetings": meetings}


def _client_meetings_on_date(client_email: str, target_date: date) -> list[dict[str, str]]:
    payload = get_client_meetings(client_email=client_email, max_results=100)
    meetings = payload.get("meetings", [])
    matches: list[dict[str, str]] = []
    for meeting in meetings:
        start_value = meeting.get("start", "")
        if not start_value:
            continue
        try:
            start_dt = _parse_user_datetime(start_value)
        except Exception:
            continue
        if start_dt.date() == target_date:
            matches.append(meeting)
    return matches


def create_meeting(
    summary: str,
    start_iso: str,
    duration_minutes: int = 60,
    description: str = "",
    client_email: str = "",
) -> dict[str, str]:
    env = _get_env()
    if not client_email.strip():
        raise ValueError("Client email is required")
    if duration_minutes != 60:
        raise ValueError("Meeting duration must be exactly 60 minutes")
    start_dt = _parse_user_datetime(start_iso)
    _ensure_not_past(start_dt)
    existing_same_day = _client_meetings_on_date(client_email, start_dt.date())
    if existing_same_day:
        meetings_list = "; ".join(
            f"{item.get('start', '')} (ID: {item.get('id', '')})" for item in existing_same_day
        )
        raise ValueError(
            "You already have meeting(s) on this day: "
            f"{meetings_list}. Please reschedule an existing meeting instead of creating a new one."
        )
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    if _would_create_four_in_row(start_dt):
        suggestion = _next_available_slot(start_dt)
        if suggestion is None:
            raise ValueError("Cannot book 4 meetings in a row and no alternative slot was found")
        raise ValueError(
            "Cannot book 4 meetings in a row. "
            f"Next available slot after required 1-hour rest: {suggestion.strftime('%Y-%m-%dT%H:%M:%S')}"
        )
    if _find_conflict(start_dt, end_dt):
        suggestion = _next_available_slot(start_dt)
        if suggestion is None:
            raise ValueError("Requested slot is busy and no available slot was found")
        raise ValueError(
            "Requested slot is busy. "
            f"Propose next available slot and wait for user confirmation before booking: {suggestion.strftime('%Y-%m-%dT%H:%M:%S')}"
        )

    event_body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": env["timezone"]},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": env["timezone"]},
        "attendees": [{"email": client_email}],
        "extendedProperties": {"private": {"client_email": _normalize_email(client_email)}},
    }

    event = (
        _service()
        .events()
        .insert(calendarId=env["calendar_id"], body=event_body)
        .execute()
    )
    return {
        "id": event.get("id", ""),
        "summary": event.get("summary", "(no title)"),
        "start": event.get("start", {}).get("dateTime", ""),
        "htmlLink": event.get("htmlLink", ""),
    }


def reschedule_meeting(
    event_id: str,
    new_start_iso: str,
    duration_minutes: int = 60,
    client_email: str = "",
) -> dict[str, str]:
    env = _get_env()
    if not client_email.strip():
        raise ValueError("Client email is required")
    if duration_minutes != 60:
        raise ValueError("Meeting duration must be exactly 60 minutes")
    event = _get_event_by_id(event_id)
    if not _event_belongs_to_client(event, client_email):
        raise PermissionError("Client can reschedule only meetings created for this email")
    start_dt = _parse_user_datetime(new_start_iso)
    _ensure_not_past(start_dt)
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    if _would_create_four_in_row(start_dt, exclude_event_id=event_id):
        suggestion = _next_available_slot(start_dt, exclude_event_id=event_id)
        if suggestion is None:
            raise ValueError("Cannot book 4 meetings in a row and no alternative slot was found")
        raise ValueError(
            "Cannot book 4 meetings in a row. "
            f"Next available slot after required 1-hour rest: {suggestion.strftime('%Y-%m-%dT%H:%M:%S')}"
        )
    if _find_conflict(start_dt, end_dt, exclude_event_id=event_id):
        suggestion = _next_available_slot(start_dt, exclude_event_id=event_id)
        if suggestion is None:
            raise ValueError("Requested slot is busy and no available slot was found")
        raise ValueError(
            "Requested slot is busy. "
            f"Propose next available slot and wait for user confirmation before rescheduling: {suggestion.strftime('%Y-%m-%dT%H:%M:%S')}"
        )

    body = {
        "start": {"dateTime": start_dt.isoformat(), "timeZone": env["timezone"]},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": env["timezone"]},
    }
    updated = (
        _service()
        .events()
        .patch(calendarId=env["calendar_id"], eventId=event_id, body=body)
        .execute()
    )
    return {
        "id": updated.get("id", ""),
        "summary": updated.get("summary", "(no title)"),
        "start": updated.get("start", {}).get("dateTime", ""),
        "htmlLink": updated.get("htmlLink", ""),
    }


def cancel_meeting(event_id: str, client_email: str = "") -> dict[str, str]:
    env = _get_env()
    if not client_email.strip():
        raise ValueError("Client email is required")
    event = _get_event_by_id(event_id)
    if not _event_belongs_to_client(event, client_email):
        raise PermissionError("Client can cancel only meetings created for this email")
    _service().events().delete(calendarId=env["calendar_id"], eventId=event_id).execute()
    return {"status": "cancelled", "event_id": event_id}
