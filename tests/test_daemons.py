"""
Unit tests for Proactive Daemons, Windows Toast Notifications, and Temporal Task Scheduler (Phase 6).
Tests SQLite reminder persistence, HardwareSentry telemetry thresholds and debouncing,
TaskScheduler tick processing, ToastNotifier dispatch, and agent reminder tools.
"""

import os
import time
from unittest.mock import ANY, MagicMock, patch
import pytest

from daemon.notifier import ToastNotifier, send_notification, toast_notifier
from daemon.scheduler import TaskScheduler
from daemon.sentry import HardwareSentry
from memory.memory_store import MemoryStore
from tools.reminder_tools import list_active_reminders, schedule_reminder
from voice.voice_manager import VoiceManager


@pytest.fixture
def temp_memory_store(tmp_path):
    """Isolated temporary SQLite database for memory store and reminder tests."""
    db_file = str(tmp_path / "test_reminders.db")
    store = MemoryStore(db_path=db_file)
    yield store
    store.clear()


@pytest.fixture
def mock_vm():
    """Mock VoiceManager for speech alert assertions."""
    vm = MagicMock(spec=VoiceManager)
    vm.is_tts_available = True
    return vm


# =====================================================================
# 1. SQLite Scheduled Reminders CRUD Tests
# =====================================================================

def test_reminder_crud_flow(temp_memory_store):
    """Test adding, querying, and marking reminders completed in SQLite."""
    now = time.time()

    # Add a reminder due in 60 seconds and one due in 10 seconds
    id1 = temp_memory_store.add_reminder("Buy milk", now + 60.0)
    id2 = temp_memory_store.add_reminder("Call doctor", now + 10.0)

    assert isinstance(id1, int) and id1 > 0
    assert isinstance(id2, int) and id2 > 0

    # At current time, neither is due
    due = temp_memory_store.get_due_reminders(current_time=now)
    assert len(due) == 0

    # At now + 15 seconds, only #id2 is due
    due_15 = temp_memory_store.get_due_reminders(current_time=now + 15.0)
    assert len(due_15) == 1
    assert due_15[0]["id"] == id2
    assert due_15[0]["reminder_text"] == "Call doctor"
    assert due_15[0]["status"] == "pending"

    # Mark id2 completed
    success = temp_memory_store.mark_reminder_completed(id2)
    assert success is True

    # At now + 15 seconds, id2 is no longer returned because status is 'completed'
    due_after = temp_memory_store.get_due_reminders(current_time=now + 15.0)
    assert len(due_after) == 0

    # Active reminders should only contain id1
    active = temp_memory_store.list_active_reminders()
    assert len(active) == 1
    assert active[0]["id"] == id1


# =====================================================================
# 2. Toast Notifier Unit Tests
# =====================================================================

def test_toast_notifier_native_dispatch():
    """Verify ToastNotifier creates Toast and calls show_toast with callback."""
    notifier = ToastNotifier(app_id="JARVIS Test")
    mock_toaster = MagicMock()
    notifier.toaster = mock_toaster

    callback_called = []
    def on_click():
        callback_called.append(True)

    with patch("daemon.notifier.HAS_WINDOWS_TOASTS", True):
        sent = notifier.send_notification("Test Title", "Test Body", on_activated=on_click)
        assert sent is True
        mock_toaster.show_toast.assert_called_once()
        toast_arg = mock_toaster.show_toast.call_args[0][0]
        assert toast_arg.text_fields == ["Test Title", "Test Body"]
        # Trigger the wrapped on_activated
        if toast_arg.on_activated:
            toast_arg.on_activated()
        assert callback_called == [True]


def test_toast_notifier_fallback_logging(capsys):
    """Verify ToastNotifier falls back to console output if native toaster is None."""
    notifier = ToastNotifier(app_id="JARVIS Test")
    notifier.toaster = None

    sent = notifier.send_notification("Offline Alert", "System running normally")
    assert sent is False
    captured = capsys.readouterr()
    assert "Offline Alert" in captured.out
    assert "System running normally" in captured.out


# =====================================================================
# 3. Hardware Sentry Daemon Tests
# =====================================================================

def test_hardware_sentry_ram_threshold(mock_vm):
    """Verify HardwareSentry triggers alert when RAM exceeds threshold."""
    sentry = HardwareSentry(
        ram_threshold=85.0,
        cooldown_seconds=600.0,
        vm=mock_vm,
        voice_alert=True,
    )

    mock_mem = MagicMock(percent=89.0)
    mock_disk = MagicMock(free=50 * 1024 * 1024 * 1024)  # 50 GB free (safe)

    with patch("psutil.virtual_memory", return_value=mock_mem), \
         patch("psutil.disk_usage", return_value=mock_disk), \
         patch("psutil.sensors_battery", return_value=None), \
         patch("daemon.sentry.send_notification") as mock_notify:

        triggered = sentry.check_metrics()
        assert triggered["ram"] is True
        assert triggered["disk"] is False
        mock_notify.assert_called_once()
        assert "High Memory" in mock_notify.call_args[0][0]
        mock_vm.speak.assert_called_once()


def test_hardware_sentry_disk_threshold(mock_vm):
    """Verify HardwareSentry triggers alert when free disk space is below minimum GB."""
    sentry = HardwareSentry(
        min_disk_gb=15.0,
        cooldown_seconds=600.0,
        vm=mock_vm,
        voice_alert=True,
    )

    mock_mem = MagicMock(percent=50.0)
    mock_disk = MagicMock(free=10 * 1024 * 1024 * 1024)  # 10 GB free (below 15 GB)

    with patch("psutil.virtual_memory", return_value=mock_mem), \
         patch("psutil.disk_usage", return_value=mock_disk), \
         patch("psutil.sensors_battery", return_value=None), \
         patch("daemon.sentry.send_notification") as mock_notify:

        triggered = sentry.check_metrics()
        assert triggered["disk"] is True
        mock_notify.assert_called_once()
        assert "Low Disk Space" in mock_notify.call_args[0][0]


def test_hardware_sentry_battery_threshold(mock_vm):
    """Verify HardwareSentry alerts on low battery only when discharging."""
    sentry = HardwareSentry(
        low_battery_threshold=20.0,
        cooldown_seconds=600.0,
        vm=mock_vm,
        voice_alert=True,
    )

    mock_mem = MagicMock(percent=50.0)
    mock_disk = MagicMock(free=50 * 1024 * 1024 * 1024)

    # 1. Battery low but plugged in -> No alert
    battery_plugged = MagicMock(percent=15.0, power_plugged=True)
    with patch("psutil.virtual_memory", return_value=mock_mem), \
         patch("psutil.disk_usage", return_value=mock_disk), \
         patch("psutil.sensors_battery", return_value=battery_plugged), \
         patch("daemon.sentry.send_notification") as mock_notify:

        triggered = sentry.check_metrics()
        assert triggered["battery"] is False
        mock_notify.assert_not_called()

    # 2. Battery low and discharging -> Alert triggered
    battery_discharging = MagicMock(percent=15.0, power_plugged=False)
    with patch("psutil.virtual_memory", return_value=mock_mem), \
         patch("psutil.disk_usage", return_value=mock_disk), \
         patch("psutil.sensors_battery", return_value=battery_discharging), \
         patch("daemon.sentry.send_notification") as mock_notify:

        triggered = sentry.check_metrics()
        assert triggered["battery"] is True
        mock_notify.assert_called_once()
        assert "Low Battery" in mock_notify.call_args[0][0]


def test_hardware_sentry_cooldown_debouncing(mock_vm):
    """Verify repeated threshold breaches within cooldown period are suppressed."""
    sentry = HardwareSentry(
        ram_threshold=85.0,
        cooldown_seconds=900.0,
        vm=mock_vm,
        voice_alert=False,
    )

    mock_mem = MagicMock(percent=92.0)
    mock_disk = MagicMock(free=50 * 1024 * 1024 * 1024)

    with patch("psutil.virtual_memory", return_value=mock_mem), \
         patch("psutil.disk_usage", return_value=mock_disk), \
         patch("psutil.sensors_battery", return_value=None), \
         patch("daemon.sentry.send_notification") as mock_notify:

        # First check triggers notification
        t1 = sentry.check_metrics()
        assert t1["ram"] is True
        assert mock_notify.call_count == 1

        # Second check immediately after is debounced
        t2 = sentry.check_metrics()
        assert t2["ram"] is False
        assert mock_notify.call_count == 1


# =====================================================================
# 4. Temporal Task Scheduler Unit Tests
# =====================================================================

def test_task_scheduler_processes_due_reminders(temp_memory_store, mock_vm):
    """Verify TaskScheduler triggers notification and marks reminder completed."""
    scheduler = TaskScheduler(
        check_interval=1.0,
        store=temp_memory_store,
        vm=mock_vm,
        voice_alert=True,
    )

    now = time.time()
    # Add one task in the past (due) and one in the future (not due)
    id1 = temp_memory_store.add_reminder("Submit report", now - 10.0)
    id2 = temp_memory_store.add_reminder("Team meeting", now + 600.0)

    with patch("daemon.scheduler.send_notification") as mock_notify:
        processed = scheduler.check_due_reminders(current_time=now)
        assert processed == 1

        mock_notify.assert_called_once_with(
            title="JARVIS Reminder",
            body="Submit report",
        )
        mock_vm.speak.assert_called_once_with(
            "Sir, here is your scheduled reminder: Submit report",
            blocking=False,
        )

        # Reminder #id1 should now be completed, #id2 still active
        active = temp_memory_store.list_active_reminders()
        assert len(active) == 1
        assert active[0]["id"] == id2


# =====================================================================
# 5. Reminder Agent Tools Tests
# =====================================================================

def test_schedule_reminder_tool(temp_memory_store):
    """Verify schedule_reminder tool calculates due timestamp and returns confirmation."""
    with patch("tools.reminder_tools.memory_store", temp_memory_store):
        result = schedule_reminder("Attend keynote speech", 15.0)
        assert "scheduled for" in result
        assert "Attend keynote speech" in result

        active = temp_memory_store.list_active_reminders()
        assert len(active) == 1
        assert active[0]["reminder_text"] == "Attend keynote speech"


def test_schedule_reminder_tool_validation():
    """Verify schedule_reminder rejects empty text or non-positive delay."""
    err1 = schedule_reminder("", 10.0)
    assert "Error" in err1

    err2 = schedule_reminder("Check email", -5.0)
    assert "Error" in err2

    err3 = schedule_reminder("Check email", "invalid")  # type: ignore
    assert "Error" in err3


def test_list_active_reminders_tool(temp_memory_store):
    """Verify list_active_reminders tool formats active tasks nicely."""
    with patch("tools.reminder_tools.memory_store", temp_memory_store):
        # Empty
        assert "No active reminders" in list_active_reminders()

        # Added tasks
        now = time.time()
        temp_memory_store.add_reminder("Backup database", now + 120.0)
        temp_memory_store.add_reminder("Water plants", now + 7200.0)

        output = list_active_reminders()
        assert "Active Reminders (2)" in output
        assert "Backup database" in output
        assert "Water plants" in output
