"""
Modern PyWebView Floating HUD and Python-JS Bridge for JARVIS Desktop Assistant.
Renders a frameless, transparent, always-on-top glassmorphic command bar
with bidirectional communication, ReAct live streaming, and global hotkey support.
"""

import json
import os
import sys
import threading
from pathlib import Path
from typing import Optional

import webview

from agent.core import JarvisAgent
from tools.browser_tools import browser_controller
from voice.voice_manager import VoiceManager, voice_manager

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False


class WebHUDAPI:
    """
    Python API exposed directly to JavaScript via `window.pywebview.api`.
    Coordinates agent execution, voice transcription, and UI updates.
    """

    def __init__(self, agent: JarvisAgent, vm: Optional[VoiceManager] = None):
        self.agent = agent
        self.vm = vm or voice_manager
        self.window: Optional[webview.Window] = None
        self.is_visible = True
        self._is_processing = False
        self._lock = threading.Lock()
        self.tray_manager = None

        # Bind agent log callback
        self.agent.log_callback = self._on_agent_log

    def set_window(self, window: webview.Window) -> None:
        """Associate the pywebview window instance."""
        self.window = window

    def _eval_js(self, script: str) -> None:
        """Evaluate a JavaScript expression safely on the window."""
        if not self.window:
            return
        try:
            self.window.evaluate_js(script)
        except Exception:
            pass

    def _on_agent_log(self, channel: str, message: str) -> None:
        """Callback invoked by JarvisAgent during reasoning steps."""
        # Stream log into the ReAct drawer
        payload_chan = json.dumps(channel)
        payload_msg = json.dumps(message)
        self._eval_js(f"if (window.onAgentLog) window.onAgentLog({payload_chan}, {payload_msg});")

        # Update status pill depending on step type
        ch_lower = channel.lower()
        if ch_lower in ("thought", "plan", "critique"):
            self._eval_js("if (window.onStatusChange) window.onStatusChange('THINKING');")
        elif ch_lower in ("action", "action_input"):
            self._eval_js("if (window.onStatusChange) window.onStatusChange('EXECUTING TOOL');")
        elif ch_lower == "observation":
            self._eval_js("if (window.onStatusChange) window.onStatusChange('THINKING');")
        elif ch_lower == "final_answer":
            self._eval_js("if (window.onStatusChange) window.onStatusChange('IDLE');")
        elif ch_lower == "error":
            self._eval_js("if (window.onStatusChange) window.onStatusChange('ERROR');")

    # === JavaScript Exposed Methods ===

    def submit_query(self, query: str) -> None:
        """Receive user query from JS input and run agent in background thread."""
        if not query or not query.strip():
            return

        with self._lock:
            if self._is_processing:
                self._eval_js("if (window.onAgentLog) window.onAgentLog('info', 'Busy processing prior request...');")
                return
            self._is_processing = True

        def _worker():
            try:
                self._eval_js("if (window.onStatusChange) window.onStatusChange('THINKING');")
                response = self.agent.run(query.strip())
                resp_json = json.dumps(response)
                self._eval_js(f"if (window.onAgentResponse) window.onAgentResponse({resp_json});")

                # Speech feedback if available
                if response and self.vm.is_tts_available:
                    self._eval_js("if (window.onStatusChange) window.onStatusChange('SPEAKING');")
                    self.vm.speak(response, blocking=True)

            except Exception as e:
                err_json = json.dumps(str(e))
                self._eval_js(f"if (window.onAgentLog) window.onAgentLog('error', {err_json});")
                self._eval_js("if (window.onStatusChange) window.onStatusChange('ERROR');")
            finally:
                with self._lock:
                    self._is_processing = False
                self._eval_js("if (window.onStatusChange) window.onStatusChange('IDLE');")

        threading.Thread(target=_worker, daemon=True, name="JARVIS-WebHUD-Worker").start()

    def trigger_voice(self) -> None:
        """Trigger voice capture turn and pipe transcription into submit_query."""
        with self._lock:
            if self._is_processing:
                return
            self._is_processing = True

        def _voice_worker():
            try:
                self._eval_js("if (window.onStatusChange) window.onStatusChange('LISTENING');")
                self._eval_js("if (window.onAgentLog) window.onAgentLog('info', 'Listening to microphone...');")
                spoken = self.vm.listen_once()
                if spoken:
                    spoken_json = json.dumps(spoken)
                    self._eval_js(f"if (window.onVoiceTranscript) window.onVoiceTranscript({spoken_json});")
                    with self._lock:
                        self._is_processing = False
                    self.submit_query(spoken)
                else:
                    self._eval_js("if (window.onAgentLog) window.onAgentLog('info', 'No speech detected.');")
                    self._eval_js("if (window.onStatusChange) window.onStatusChange('IDLE');")
                    with self._lock:
                        self._is_processing = False
            except Exception as e:
                err_json = json.dumps(str(e))
                self._eval_js(f"if (window.onAgentLog) window.onAgentLog('error', {err_json});")
                self._eval_js("if (window.onStatusChange) window.onStatusChange('ERROR');")
                with self._lock:
                    self._is_processing = False

        threading.Thread(target=_voice_worker, daemon=True, name="JARVIS-Voice-Worker").start()

    def trigger_vision(self) -> None:
        """Trigger immediate screenshot capture and vision grounding inquiry."""
        self.submit_query("Take a screenshot of the current screen and analyze what is visible on display.")

    def trigger_stats(self) -> None:
        """Trigger immediate telemetry inquiry."""
        self.submit_query("Check current system stats including CPU usage, RAM utilization, and disk status.")

    def clear_history(self) -> None:
        """Clear conversation memory and reset web feed."""
        self.agent.reset()
        self._eval_js("if (window.clearFeed) window.clearFeed();")
        self._eval_js("if (window.onStatusChange) window.onStatusChange('IDLE');")

    def hide_window(self) -> None:
        """Conceal the HUD window into background."""
        if self.window:
            try:
                self.window.hide()
            except Exception:
                pass
            self.is_visible = False

    def show_window(self) -> None:
        """Reveal and focus the HUD window."""
        if self.window:
            try:
                self.window.show()
                self._eval_js("if (window.focusInput) window.focusInput();")
            except Exception:
                pass
            self.is_visible = True

    def toggle_window(self) -> None:
        """Smoothly toggle window visibility."""
        if self.is_visible:
            self.hide_window()
        else:
            self.show_window()

    def exit_app(self) -> None:
        """Shutdown helper for tray and window."""
        try:
            self.vm.stop_speech()
            browser_controller.close_browser()
        except Exception:
            pass

        if self.tray_manager:
            try:
                self.tray_manager.stop()
            except Exception:
                pass

        if self.window:
            try:
                self.window.destroy()
            except Exception:
                pass

        sys.exit(0)


class WebHUD:
    """
    Manages the PyWebView window lifecycle, global Alt+Space hotkey hook,
    and system tray hub persistence.
    """

    def __init__(
        self,
        agent: JarvisAgent,
        vm: Optional[VoiceManager] = None,
        width: int = 820,
        height: int = 620,
        hotkey: str = "alt+space",
    ):
        self.agent = agent
        self.vm = vm or voice_manager
        self.width = width
        self.height = height
        self.hotkey = hotkey

        self.api = WebHUDAPI(agent=self.agent, vm=self.vm)
        self.window: Optional[webview.Window] = None
        self._hotkey_hooked = False

        self.html_path = Path(__file__).parent / "assets" / "hud.html"

    def _calculate_position(self) -> tuple[int, int]:
        """Calculate horizontally centered, top-aligned coordinates."""
        screen_w = 1920
        screen_h = 1080

        try:
            if webview.screens:
                primary = webview.screens[0]
                screen_w = primary.width
                screen_h = primary.height
        except Exception:
            pass

        pos_x = (screen_w - self.width) // 2
        pos_y = int(screen_h * 0.08)
        return pos_x, pos_y

    def start(self) -> None:
        """Initialize window, register hotkey, and launch pywebview loop."""
        pos_x, pos_y = self._calculate_position()

        # Build pywebview window with frameless, transparent, on_top settings
        self.window = webview.create_window(
            title="JARVIS Floating HUD",
            url=str(self.html_path.resolve()),
            js_api=self.api,
            width=self.width,
            height=self.height,
            x=pos_x,
            y=pos_y,
            frameless=True,
            on_top=True,
            transparent=True,
            easy_drag=True,
            shadow=True,
            background_color="#000000",
        )
        self.api.set_window(self.window)

        # Register global OS hotkey Alt+Space
        self._register_hotkey()

        # Start PyWebView GUI event loop
        try:
            webview.start(debug=False)
        finally:
            self._cleanup()

    def _register_hotkey(self) -> None:
        """Register the system-wide global hotkey without blocking the main loop."""
        if not HAS_KEYBOARD:
            return

        try:
            keyboard.add_hotkey(self.hotkey, self.api.toggle_window)
            self._hotkey_hooked = True
        except Exception:
            self._hotkey_hooked = False

    def _cleanup(self) -> None:
        """Clean up hotkeys and background processes upon exit."""
        if HAS_KEYBOARD and self._hotkey_hooked:
            try:
                keyboard.unhook_all_hotkeys()
            except Exception:
                pass
            self._hotkey_hooked = False


def run_web_hud(agent: JarvisAgent, vm: Optional[VoiceManager] = None) -> None:
    """Launch the WebHUD and System Tray Hub."""
    from ui.tray_manager import TrayManager

    hud = WebHUD(agent=agent, vm=vm)

    # Bridge tray manager with WebHUD API
    class TrayControllerProxy:
        def __init__(self, api: WebHUDAPI):
            self.api = api
        def toggle_hud(self):
            self.api.toggle_window()
        def trigger_voice(self):
            self.api.trigger_voice()
        def trigger_system_stats(self):
            self.api.trigger_stats()
        def clear_output(self):
            self.api.clear_history()
        def shutdown(self):
            self.api.exit_app()

    tray_proxy = TrayControllerProxy(hud.api)
    tray = TrayManager(controller=tray_proxy, hotkey="alt+space")
    hud.api.tray_manager = tray
    tray.start()

    hud.start()
