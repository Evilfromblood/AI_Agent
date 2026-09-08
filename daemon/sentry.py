"""
Hardware Sentry Daemon for JARVIS Desktop Assistant.
Monitors system RAM utilization, disk capacity, and battery telemetry in the background,
dispatching toast notifications and spoken warnings with cooldown debouncing.
"""

import logging
import os
import threading
import time
from typing import Dict, Optional

import psutil

from daemon.notifier import send_notification
from voice.voice_manager import VoiceManager, voice_manager

logger = logging.getLogger(__name__)


class HardwareSentry(threading.Thread):
    """
    Proactive background hardware telemetry sentry.
    Polls system metrics periodically and alerts on critical thresholds.
    """

    def __init__(
        self,
        poll_interval: float = 45.0,
        ram_threshold: float = 88.0,
        min_disk_gb: float = 15.0,
        low_battery_threshold: float = 20.0,
        cooldown_seconds: float = 900.0,  # 15 minutes per metric
        vm: Optional[VoiceManager] = None,
        voice_alert: bool = True,
    ):
        super().__init__(daemon=True, name="JARVIS-HardwareSentry")
        self.poll_interval = poll_interval
        self.ram_threshold = ram_threshold
        self.min_disk_bytes = min_disk_gb * 1024 * 1024 * 1024
        self.min_disk_gb = min_disk_gb
        self.low_battery_threshold = low_battery_threshold
        self.cooldown_seconds = cooldown_seconds
        self.vm = vm or voice_manager
        self.voice_alert = voice_alert

        self._stop_event = threading.Event()
        self._last_alert_time: Dict[str, float] = {}

    def stop(self) -> None:
        """Signal sentry daemon to terminate cleanly."""
        self._stop_event.set()

    def run(self) -> None:
        """Daemon loop executing periodic hardware metric evaluation."""
        logger.info("HardwareSentry daemon started (interval=%.1fs).", self.poll_interval)
        while not self._stop_event.is_set():
            try:
                self.check_metrics()
            except Exception as e:
                logger.error("Error evaluating hardware metrics: %s", e)

            # Non-blocking sleep responsive to stop signal
            if self._stop_event.wait(timeout=self.poll_interval):
                break

        logger.info("HardwareSentry daemon stopped.")

    def _should_alert(self, metric_key: str, now: float) -> bool:
        """Evaluate if enough cooldown time has elapsed to send another notification."""
        last_time = self._last_alert_time.get(metric_key, 0.0)
        if (now - last_time) >= self.cooldown_seconds:
            self._last_alert_time[metric_key] = now
            return True
        return False

    def check_metrics(self) -> Dict[str, bool]:
        """
        Evaluate current system telemetry against configured warning thresholds.
        Returns a dict indicating which metrics triggered an alert.
        """
        now = time.time()
        triggered = {
            "ram": False,
            "disk": False,
            "battery": False,
        }

        # 1. RAM Utilization
        try:
            mem = psutil.virtual_memory()
            if mem.percent >= self.ram_threshold:
                if self._should_alert("ram", now):
                    triggered["ram"] = True
                    self._dispatch_alert(
                        title="JARVIS Hardware Alert: High Memory",
                        body=f"System RAM utilization is at {mem.percent:.1f}% (threshold {self.ram_threshold}%).",
                        speech=f"Warning: System RAM utilization has reached {int(mem.percent)} percent.",
                    )
        except Exception as e:
            logger.debug("Failed checking RAM metrics: %s", e)

        # 2. System Disk Space
        try:
            drive = "C:\\" if os.name == "nt" and os.path.exists("C:\\") else os.path.abspath(os.sep)
            disk = psutil.disk_usage(drive)
            if disk.free <= self.min_disk_bytes:
                if self._should_alert("disk", now):
                    triggered["disk"] = True
                    free_gb = disk.free / (1024 * 1024 * 1024)
                    self._dispatch_alert(
                        title="JARVIS Hardware Alert: Low Disk Space",
                        body=f"Free disk space on {drive} is critically low: {free_gb:.1f} GB remaining.",
                        speech=f"Warning: Free disk space on {drive[:2]} is critically low at {free_gb:.1f} gigabytes.",
                    )
        except Exception as e:
            logger.debug("Failed checking disk metrics: %s", e)

        # 3. Battery Telemetry
        try:
            battery = psutil.sensors_battery()
            if battery is not None:
                is_discharging = not battery.power_plugged
                if is_discharging and battery.percent <= self.low_battery_threshold:
                    if self._should_alert("battery", now):
                        triggered["battery"] = True
                        self._dispatch_alert(
                            title="JARVIS Hardware Alert: Low Battery",
                            body=f"System battery is at {battery.percent:.0f}% while running on battery power.",
                            speech=f"Sir, system battery has fallen to {int(battery.percent)} percent. Please connect a charger.",
                        )
        except Exception as e:
            logger.debug("Failed checking battery metrics: %s", e)

        return triggered

    def _dispatch_alert(self, title: str, body: str, speech: str) -> None:
        """Send a Windows toast notification and optional spoken warning."""
        send_notification(title, body)
        if self.voice_alert and self.vm and self.vm.is_tts_available:
            self.vm.speak(speech, blocking=False)
