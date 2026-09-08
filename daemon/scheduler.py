"""
Temporal Task Scheduler Daemon for JARVIS Desktop Assistant.
Monitors SQLite scheduled_reminders in the background and delivers
timely Windows toast notifications and spoken reminders.
"""

import logging
import threading
import time
from typing import Optional

from daemon.notifier import send_notification
from memory.memory_store import MemoryStore, memory_store
from voice.voice_manager import VoiceManager, voice_manager

logger = logging.getLogger(__name__)


class TaskScheduler(threading.Thread):
    """
    Proactive background task scheduler.
    Periodically checks for due temporal reminders and delivers notifications.
    """

    def __init__(
        self,
        check_interval: float = 10.0,
        store: Optional[MemoryStore] = None,
        vm: Optional[VoiceManager] = None,
        voice_alert: bool = True,
    ):
        super().__init__(daemon=True, name="JARVIS-TaskScheduler")
        self.check_interval = check_interval
        self.store = store or memory_store
        self.vm = vm or voice_manager
        self.voice_alert = voice_alert
        self._stop_event = threading.Event()

    def stop(self) -> None:
        """Signal scheduler daemon to terminate cleanly."""
        self._stop_event.set()

    def run(self) -> None:
        """Scheduler daemon loop checking for due reminders."""
        logger.info("TaskScheduler daemon started (interval=%.1fs).", self.check_interval)
        while not self._stop_event.is_set():
            try:
                self.check_due_reminders()
            except Exception as e:
                logger.error("Error processing due reminders: %s", e)

            # Responsive sleep
            if self._stop_event.wait(timeout=self.check_interval):
                break

        logger.info("TaskScheduler daemon stopped.")

    def check_due_reminders(self, current_time: Optional[float] = None) -> int:
        """
        Query memory store for due reminders, deliver toast and voice alerts,
        and update status to completed.
        Returns the count of processed reminders.
        """
        now = time.time() if current_time is None else float(current_time)
        due_tasks = self.store.get_due_reminders(current_time=now)
        processed = 0

        for task in due_tasks:
            task_id = task["id"]
            text = task["reminder_text"]
            logger.info("Executing scheduled reminder #%s: %s", task_id, text)

            # 1. Native Windows Toast Notification
            send_notification(
                title="JARVIS Reminder",
                body=text,
            )

            # 2. Spoken Reminder
            if self.voice_alert and self.vm and self.vm.is_tts_available:
                speech_text = f"Sir, here is your scheduled reminder: {text}"
                self.vm.speak(speech_text, blocking=False)

            # 3. Mark completed in SQLite
            self.store.mark_reminder_completed(task_id)
            processed += 1

        return processed
