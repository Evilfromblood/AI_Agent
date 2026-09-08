"""
Daemon package for proactive background services, notifications, and scheduling.
"""

from daemon.notifier import ToastNotifier, toast_notifier, send_notification
from daemon.sentry import HardwareSentry
from daemon.scheduler import TaskScheduler

__all__ = [
    "ToastNotifier",
    "toast_notifier",
    "send_notification",
    "HardwareSentry",
    "TaskScheduler",
]
