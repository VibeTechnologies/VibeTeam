"""
Shared Calendar tool functions for all agent frameworks.

Note: Google Calendar integration requires langchain-google-community[calendar]
or a custom connector. For now, we provide a structure that can be easily
extended when credentials are available.
"""

import os
from datetime import datetime, timedelta


def _get_calendar_service():
    """Get authenticated Google Calendar service.

    This requires setting up Google Calendar API credentials.
    See: https://developers.google.com/calendar/api/quickstart/python
    """
    try:
        from pathlib import Path

        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_path = Path(os.environ.get("GCAL_TOKEN_PATH", ".secrets/gcal-token.json"))

        if not token_path.exists():
            return (
                None,
                "Google Calendar token not found. Run calendar authentication first.",
            )

        SCOPES = [
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
        ]

        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        service = build("calendar", "v3", credentials=creds)
        return service

    except ImportError:
        return (
            None,
            "Google Calendar API not installed. Run: pip install google-api-python-client",
        )
    except Exception as e:
        return None, str(e)


async def list_calendar_events(days: int = 7, max_results: int = 10) -> str:
    """List upcoming calendar events.

    Args:
        days: Number of days to look ahead (default: 7)
        max_results: Maximum events to return (default: 10)

    Returns:
        Formatted list of calendar events or error message
    """
    result = _get_calendar_service()
    if isinstance(result, tuple):
        # Calendar not configured - return helpful message
        return f"""
=== Calendar Events (next {days} days) ===

Calendar integration not configured: {result[1]}

To enable Google Calendar:
1. Create credentials at https://console.cloud.google.com/
2. Download credentials.json to .secrets/gcal-credentials.json
3. Run authentication to generate token

For now, please describe the calendar operations you want to perform.
"""

    service = result

    try:
        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(days=days)).isoformat() + "Z"

        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = events_result.get("items", [])

        if not events:
            return f"No upcoming events in the next {days} days."

        output = f"=== Calendar Events (next {days} days) ===\n\n"
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            summary = event.get("summary", "No title")
            location = event.get("location", "")

            output += f"- **{summary}**\n"
            output += f"  Start: {start}\n"
            if location:
                output += f"  Location: {location}\n"
            output += "\n"

        return output

    except Exception as e:
        return f"Error fetching calendar events: {e}"


async def create_calendar_event(
    title: str,
    start_time: str,
    duration_minutes: int = 60,
    attendees: str = "",
    description: str = "",
) -> str:
    """Create a calendar event.

    Args:
        title: Event title
        start_time: Start time (ISO format: 2024-01-27T14:00:00)
        duration_minutes: Duration in minutes (default: 60)
        attendees: Comma-separated email addresses
        description: Event description

    Returns:
        Event creation status or error message
    """
    result = _get_calendar_service()
    if isinstance(result, tuple):
        return f"""
=== Calendar Event Draft ===
Title: {title}
Start: {start_time}
Duration: {duration_minutes} minutes
Attendees: {attendees or "None"}
Description: {description or "None"}

Status: Draft created (calendar not configured)
Note: {result[1]}
"""

    service = result

    try:
        # Parse start time and calculate end time
        start_dt = datetime.fromisoformat(start_time)
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        event = {
            "summary": title,
            "description": description,
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": "UTC",
            },
        }

        if attendees:
            event["attendees"] = [{"email": email.strip()} for email in attendees.split(",")]

        created_event = service.events().insert(calendarId="primary", body=event).execute()

        return f"""
=== Calendar Event Created ===
Title: {title}
Start: {start_time}
Duration: {duration_minutes} minutes
Event ID: {created_event.get("id")}
Link: {created_event.get("htmlLink")}
"""

    except Exception as e:
        return f"Error creating calendar event: {e}"


def get_calendar_context(days: int = 3) -> str:
    """Get calendar context for agent prompts.

    Args:
        days: Number of days to look ahead

    Returns:
        Formatted context string for agent prompts
    """
    result = _get_calendar_service()
    if isinstance(result, tuple):
        return f"## Calendar Status\n\nGoogle Calendar not configured: {result[1]}"

    import asyncio

    # Run the async function synchronously for convenience
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If we're in an async context, create a new loop
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, list_calendar_events(days=days))
                return future.result()
        else:
            return loop.run_until_complete(list_calendar_events(days=days))
    except Exception as e:
        return f"## Calendar Status\n\nError loading calendar: {e}"
