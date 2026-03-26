from agents import function_tool

from google_calendar import (
    cancel_meeting as cancel_meeting_impl,
    create_meeting as create_meeting_impl,
    list_upcoming_meetings as list_upcoming_meetings_impl,
    reschedule_meeting as reschedule_meeting_impl,
)


@function_tool
def list_upcoming_meetings(max_results: int = 10) -> list[dict[str, str]]:
    return list_upcoming_meetings_impl(max_results=max_results)


@function_tool
def create_meeting(
    summary: str,
    start_iso: str,
    duration_minutes: int = 60,
    description: str = "",
) -> dict[str, str]:
    return create_meeting_impl(
        summary=summary,
        start_iso=start_iso,
        duration_minutes=duration_minutes,
        description=description,
    )


@function_tool
def reschedule_meeting(
    event_id: str,
    new_start_iso: str,
    duration_minutes: int = 60,
) -> dict[str, str]:
    return reschedule_meeting_impl(
        event_id=event_id,
        new_start_iso=new_start_iso,
        duration_minutes=duration_minutes,
    )


@function_tool
def cancel_meeting(event_id: str) -> dict[str, str]:
    return cancel_meeting_impl(event_id=event_id)
