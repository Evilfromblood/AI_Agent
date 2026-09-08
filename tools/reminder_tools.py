"""
Reminder and Temporal Scheduling Tools for JARVIS Desktop Assistant.
Allows autonomous agent scheduling of time-delayed reminders with Windows toast
and spoken vocalization alerts.
"""

import datetime
import time
from tools.registry import register_tool

# Module-level reference to support testing and avoid circular import during tool registration
memory_store = None


def _resolve_store():
    global memory_store
    if memory_store is not None:
        return memory_store
    from memory.memory_store import memory_store as default_store
    return default_store


@register_tool("schedule_reminder")
def schedule_reminder(
    reminder_text: str,
    delay_minutes: float,
    recurrence: str = "none",
) -> str:
    """
    Schedule a temporal reminder task to be delivered via Windows toast notification and voice alert.
    :param reminder_text: The task or notification content to remind the user about
    :param delay_minutes: Number of minutes from now when the reminder should trigger (e.g. 5.0, 30.0)
    :param recurrence: Recurrence rule ('none', 'daily', 'hourly')
    """
    if not reminder_text or not reminder_text.strip():
        return "Error: Reminder text cannot be empty."

    try:
        delay_min = float(delay_minutes)
        if delay_min <= 0:
            return "Error: delay_minutes must be a positive number greater than 0."
    except (ValueError, TypeError):
        return f"Error: Invalid delay_minutes value '{delay_minutes}'. Must be a numeric value."

    now = time.time()
    due_timestamp = now + (delay_min * 60.0)
    due_dt = datetime.datetime.fromtimestamp(due_timestamp)
    due_str = due_dt.strftime("%I:%M %p").lstrip("0")

    store = _resolve_store()
    task_id = store.add_reminder(
        reminder_text=reminder_text.strip(),
        due_timestamp=due_timestamp,
        recurrence=recurrence,
    )

    if delay_min < 1.0:
        delay_desc = f"{int(delay_min * 60)} seconds"
    elif delay_min == 1.0:
        delay_desc = "1 minute"
    elif delay_min.is_integer():
        delay_desc = f"{int(delay_min)} minutes"
    else:
        delay_desc = f"{delay_min:.1f} minutes"

    return f"Reminder #{task_id} scheduled for {due_str} (in {delay_desc}): '{reminder_text.strip()}'."


@register_tool("list_active_reminders")
def list_active_reminders() -> str:
    """
    List all pending temporal reminders with human-readable countdowns and scheduled times.
    """
    store = _resolve_store()
    reminders = store.list_active_reminders()

    if not reminders:
        return "No active reminders currently scheduled."

    now = time.time()
    lines = [f"Active Reminders ({len(reminders)}):"]
    for r in reminders:
        due_ts = r["due_timestamp"]
        diff_sec = due_ts - now
        due_dt = datetime.datetime.fromtimestamp(due_ts)
        time_str = due_dt.strftime("%I:%M %p").lstrip("0")

        if diff_sec <= 0:
            countdown = "due now"
        elif diff_sec < 60:
            countdown = f"in {int(diff_sec)}s"
        elif diff_sec < 3600:
            countdown = f"in {int(diff_sec // 60)}m"
        else:
            hours = int(diff_sec // 3600)
            mins = int((diff_sec % 3600) // 60)
            countdown = f"in {hours}h {mins}m"

        recur_str = f" [repeat: {r['recurrence']}]" if r.get("recurrence") and r["recurrence"] != "none" else ""
        lines.append(f"- #{r['id']} ({time_str}, {countdown}){recur_str}: {r['reminder_text']}")

    return "\n".join(lines)
