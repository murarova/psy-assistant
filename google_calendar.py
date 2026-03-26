import base64
import os
from datetime import datetime, timedelta, timezone
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


def list_upcoming_meetings(max_results: int = 10) -> list[dict[str, str]]:
    env = _get_env()
    now = datetime.now(timezone.utc).isoformat()
    events_result = (
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
    )
    events = events_result.get("items", [])
    output: list[dict[str, str]] = []
    for event in events:
        start = event.get("start", {}).get("dateTime", event.get("start", {}).get("date", ""))
        output.append(
            {
                "id": event.get("id", ""),
                "summary": event.get("summary", "(no title)"),
                "start": start,
                "htmlLink": event.get("htmlLink", ""),
            }
        )
    return output


def create_meeting(summary: str, start_iso: str, duration_minutes: int = 60, description: str = "") -> dict[str, str]:
    env = _get_env()
    start_dt = _parse_user_datetime(start_iso)
    _ensure_not_past(start_dt)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    event_body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": env["timezone"]},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": env["timezone"]},
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


def reschedule_meeting(event_id: str, new_start_iso: str, duration_minutes: int = 60) -> dict[str, str]:
    env = _get_env()
    start_dt = _parse_user_datetime(new_start_iso)
    _ensure_not_past(start_dt)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

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


def cancel_meeting(event_id: str) -> dict[str, str]:
    env = _get_env()
    _service().events().delete(calendarId=env["calendar_id"], eventId=event_id).execute()
    return {"status": "cancelled", "event_id": event_id}
