from agents import function_tool

from google_calendar import (
    cancel_meeting as cancel_meeting_impl,
    create_meeting as create_meeting_impl,
    get_client_meetings as get_client_meetings_impl,
    get_available_time as get_available_time_impl,
    get_available_time_next_week as get_available_time_next_week_impl,
    get_available_time_this_week as get_available_time_this_week_impl,
    reschedule_meeting as reschedule_meeting_impl,
)


@function_tool
def create_meeting(
    summary: str,
    start_iso: str,
    client_email: str,
    duration_minutes: int = 60,
    description: str = "",
) -> dict[str, str]:
    return create_meeting_impl(
        summary=summary,
        start_iso=start_iso,
        client_email=client_email,
        duration_minutes=duration_minutes,
        description=description,
    )


@function_tool
def reschedule_meeting(
    event_id: str,
    new_start_iso: str,
    client_email: str,
    duration_minutes: int = 60,
) -> dict[str, str]:
    return reschedule_meeting_impl(
        event_id=event_id,
        new_start_iso=new_start_iso,
        client_email=client_email,
        duration_minutes=duration_minutes,
    )


@function_tool
def cancel_meeting(event_id: str, client_email: str) -> dict[str, str]:
    return cancel_meeting_impl(event_id=event_id, client_email=client_email)


@function_tool
def get_available_time(date_iso: str, duration_minutes: int = 60) -> dict:
    return get_available_time_impl(date_iso=date_iso, duration_minutes=duration_minutes)


@function_tool
def get_available_time_this_week() -> dict:
    return get_available_time_this_week_impl()


@function_tool
def get_available_time_next_week() -> dict:
    return get_available_time_next_week_impl()


@function_tool
def get_client_meetings(client_email: str, max_results: int = 20) -> dict:
    return get_client_meetings_impl(client_email=client_email, max_results=max_results)
