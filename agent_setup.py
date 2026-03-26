import os
from datetime import datetime
from zoneinfo import ZoneInfo

from agents import Agent
from dotenv import load_dotenv

load_dotenv()

from calendar_tools import (
    cancel_meeting,
    create_meeting,
    list_upcoming_meetings,
    reschedule_meeting,
)

INSTRUCTIONS_TEMPLATE = """
You are my personal scheduling assistant.
You help me manage Google Calendar by using tools.

Current date and time: {current_datetime} ({timezone})

Rules:
1. Use tools for all calendar actions.
2. Never invent meeting IDs, links, or times.
3. If required fields are missing, ask a concise follow-up question.
4. Before cancelling a meeting, ask for explicit confirmation.
5. Keep responses short and practical.
6. Default meeting duration is 60 minutes unless the user specifies otherwise.
7. Always reply in Ukrainian.
8. If the year is missing, use the current year based on the date above.
9. Never schedule or move meetings to a past date or time.
10. Always convert relative dates like "tomorrow" or "завтра" to an ISO 8601
    datetime string before calling any tool.
    IMPORTANT: never add a timezone suffix (no Z, no +00:00, no +02:00).
    Always pass bare local time, for example: 2026-03-27T15:00:00
"""


def build_manager_agent(model: str) -> Agent:
    tz_name = os.getenv("TIMEZONE", "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
        tz_name = "UTC"
    current_datetime = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
    instructions = INSTRUCTIONS_TEMPLATE.format(current_datetime=current_datetime, timezone=tz_name)
    return Agent(
        name="Calendar Manager",
        instructions=instructions,
        tools=[
            list_upcoming_meetings,
            create_meeting,
            reschedule_meeting,
            cancel_meeting,
        ],
        model=model,
    )
