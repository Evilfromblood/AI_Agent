"""
Application Controller for JARVIS Desktop Assistant.
Decouples CustomTkinter UI event loop from agent execution using background threads,
thread-safe tkinter dispatcher callbacks, and coordinated voice interactions.
"""

import sys
import threading
from typing import TYPE_CHECKING, Optional

from agent.core import JarvisAgent
from tools.browser_tools import browser_controller
from voice.voice_manager import VoiceManager, voice_manager

if TYPE_CHECKING:
    from ui.floating_hud import JarvisFloatingHUD
    from ui.tray_manager import TrayManager


class AppController:
    """
    Bridge coordinator between JarvisAgent, JarvisFloatingHUD,
    VoiceManager, and the background System Tray Daemon.
    """

    def __init__(
        self,
        agent: JarvisAgent,
        vm: Optional[VoiceManager] = None,
        hud: Optional["JarvisFloatingHUD"] = None,
        voice_feedback: bool = True,
    ):
        self.agent = agent
        self.voice_manager = vm or voice_manager
        self.hud = hud
        self.tray_manager: Optional["TrayManager"] = None
        self.voice_feedback = voice_feedback

        self._is_processing = False
        self._lock = threading.Lock()

        # Connect agent logging callback to our controller
        self.agent.log_callback = self._on_agent_log

    def set_hud(self, hud: "JarvisFloatingHUD") -> None:
        """Associate the floating HUD instance."""
        self.hud = hud
        self.hud.controller = self

    def set_tray_manager(self, tray_manager: "TrayManager") -> None:
        """Associate the system tray manager instance."""
        self.tray_manager = tray_manager

    def handle_user_query(self, prompt: str) -> None:
        """
        Receive user prompt from HUD or external hook and dispatch
        to an asynchronous background worker thread.
        """
        if not prompt or not prompt.strip():
            return

        with self._lock:
            if self._is_processing:
                if self.hud:
                    self.hud.after(0, lambda: self.hud.append_activity("info", "JARVIS is currently processing a prior request..."))
                return
            self._is_processing = True

        # Dispatch background worker
        worker = threading.Thread(
            target=self._execute_query_worker,
            args=(prompt.strip(),),
            daemon=True,
            name="JARVIS-Agent-Worker",
        )
        worker.start()

    def _execute_query_worker(self, prompt: str) -> None:
        """Background worker thread executing agent ReAct loop and voice feedback."""
        try:
            if self.hud:
                self.hud.after(0, lambda: self.hud.set_status("THINKING"))
                self.hud.after(0, lambda: self.hud.append_activity("info", f"User > {prompt}"))

            # Execute agent reasoning and tool loop
            response = self.agent.run(prompt)

            if self.hud:
                self.hud.after(0, lambda: self.hud.display_response(response))

            # Voice synthesis if enabled
            if self.voice_feedback and response and self.voice_manager.is_tts_available:
                if self.hud:
                    self.hud.after(0, lambda: self.hud.set_status("SPEAKING"))
                self.voice_manager.speak(response, blocking=True)

        except Exception as e:
            if self.hud:
                self.hud.after(0, lambda: self.hud.append_activity("error", str(e)))
                self.hud.after(0, lambda: self.hud.set_status("ERROR"))
        finally:
            with self._lock:
                self._is_processing = False
            if self.hud:
                self.hud.after(0, lambda: self.hud.set_status("IDLE"))

    def _on_agent_log(self, channel: str, message: str) -> None:
        """
        Thread-safe callback invoked by JarvisAgent during reasoning steps.
        Updates HUD status indicator and appends to activity feed.
        """
        if not self.hud:
            return

        channel_lower = channel.lower()

        # Update HUD state badge depending on agent activity
        if channel_lower in ("thought", "plan", "critique"):
            self.hud.after(0, lambda: self.hud.set_status("THINKING"))
        elif channel_lower in ("action", "action_input"):
            self.hud.after(0, lambda: self.hud.set_status("EXECUTING TOOL"))
        elif channel_lower == "observation":
            self.hud.after(0, lambda: self.hud.set_status("THINKING"))
        elif channel_lower == "final_answer":
            self.hud.after(0, lambda: self.hud.set_status("IDLE"))
        elif channel_lower == "error":
            self.hud.after(0, lambda: self.hud.set_status("ERROR"))

        # Stream activity to textbox
        self.hud.after(0, lambda c=channel, m=message: self.hud.append_activity(c, m))

    def trigger_voice(self) -> None:
        """Start an ambient voice listening turn in a worker thread."""
        with self._lock:
            if self._is_processing:
                return
            self._is_processing = True

        def _voice_worker():
            try:
                if self.hud:
                    self.hud.after(0, self.hud.show_window)
                    self.hud.after(0, lambda: self.hud.set_status("LISTENING"))
                    self.hud.after(0, lambda: self.hud.append_activity("info", "Listening for voice input..."))

                spoken = self.voice_manager.listen_once()
                if spoken:
                    if self.hud:
                        self.hud.after(0, lambda: self.hud.append_activity("info", f"Voice Heard: \"{spoken}\""))
                    with self._lock:
                        self._is_processing = False
                    self.handle_user_query(spoken)
                else:
                    if self.hud:
                        self.hud.after(0, lambda: self.hud.append_activity("info", "No speech detected."))
                        self.hud.after(0, lambda: self.hud.set_status("IDLE"))
                    with self._lock:
                        self._is_processing = False
            except Exception as e:
                if self.hud:
                    self.hud.after(0, lambda: self.hud.append_activity("error", f"Voice error: {e}"))
                    self.hud.after(0, lambda: self.hud.set_status("ERROR"))
                with self._lock:
                    self._is_processing = False

        threading.Thread(target=_voice_worker, daemon=True, name="JARVIS-Voice-Worker").start()

    def trigger_screen_vision(self) -> None:
        """Trigger immediate screenshot capture and vision analysis."""
        prompt = "Take a screenshot of the current screen and analyze what is visible on display."
        self.handle_user_query(prompt)

    def trigger_system_stats(self) -> None:
        """Trigger immediate telemetry inquiry."""
        prompt = "Check current system stats including CPU usage, RAM utilization, and disk status."
        self.handle_user_query(prompt)

    def clear_output(self) -> None:
        """Clear conversation memory and reset HUD feed."""
        self.agent.reset()
        if self.hud:
            self.hud.after(0, self.hud.clear_activity)
            self.hud.after(0, lambda: self.hud.set_status("IDLE"))

    def toggle_hud(self) -> None:
        """Toggle HUD window visibility from hotkey or tray icon."""
        if self.hud:
            self.hud.after(0, self.hud.toggle_window)

    def shutdown(self) -> None:
        """Perform comprehensive resource cleanup and terminate the application."""
        try:
            self.voice_manager.stop_speech()
            browser_controller.close_browser()
        except Exception:
            pass

        if self.tray_manager:
            try:
                self.tray_manager.stop()
            except Exception:
                pass

        if self.hud:
            try:
                self.hud.after(0, self.hud.destroy)
            except Exception:
                pass

        sys.exit(0)
