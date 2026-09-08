"""
Native PySide6 Translucent Floating HUD for JARVIS Desktop Assistant.
Renders a frameless, transparent, always-on-top glassmorphic command bar
with thread-safe Qt signals, ReAct live execution streaming, snug canvas snapping,
global Ctrl+Space hotkey support, and Escape key speech interrupt.
"""

import html
import os
import sys
import threading
from typing import Optional

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from agent.core import JarvisAgent
from config import config
from tools.browser_tools import browser_controller
from voice.voice_manager import VoiceManager, voice_manager

try:
    import keyboard

    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False



# Theme Palette
BG_DARK = "rgba(15, 23, 42, 0.94)"
BORDER_CYAN = "rgba(6, 182, 212, 0.45)"
BORDER_FOCUS = "rgba(6, 182, 212, 0.9)"
TEXT_PRIMARY = "#f1f5f9"
TEXT_MUTED = "#94a3b8"
ACCENT_CYAN = "#06b6d4"


class HUDSignals(QObject):
    """Thread-safe Qt signal dispatcher for background worker threads."""

    agent_log = Signal(str, str)  # channel, message
    status_change = Signal(str)  # status label
    agent_response = Signal(str)  # final answer
    voice_transcript = Signal(str)  # transcribed voice prompt
    toggle_visibility = Signal()  # hotkey trigger
    show_hud = Signal()  # toast click trigger
    adjust_geometry = Signal()  # snug canvas snapping
    trigger_voice = Signal()
    trigger_vision = Signal()
    trigger_stats = Signal()
    clear_feed = Signal()
    stop_speech = Signal()
    exit_app = Signal()


class QtHUD(QWidget):
    """
    Native PySide6 Translucent HUD.
    Features dark glassmorphism styling, a snug dynamic canvas,
    collapsible ReAct reasoning drawer, quick action pills, and hotkey control.
    """

    def __init__(
        self,
        agent: JarvisAgent,
        vm: Optional[VoiceManager] = None,
        width: int = 740,
        hotkey: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.agent = agent
        self.vm = vm or voice_manager
        self.hud_width = width
        self.hotkey = hotkey if hotkey is not None else getattr(config, "hud_hotkey", "ctrl+space")
        self.fallback_hotkey = getattr(config, "hud_hotkey_fallback", "ctrl+shift+space")

        self._is_processing = False
        self._lock = threading.Lock()
        self._hotkey_hooked = False
        self._drag_pos: Optional[QPoint] = None
        self.tray_manager = None

        # Setup Thread-Safe Signals
        self.signals = HUDSignals()
        self._connect_signals()

        # Wire Agent Log Callback to Qt Signal
        self.agent.log_callback = self._on_agent_log

        # Configure Window
        self._configure_window()
        self._build_ui()
        self._center_window()
        self._register_hotkey()

    def _configure_window(self) -> None:
        """Set frameless, translucent, and topmost window attributes."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # Keeps HUD clean from Alt-Tab clutter
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(self.hud_width)
        self.setWindowTitle("JARVIS Desktop HUD")

    def _connect_signals(self) -> None:
        """Connect worker signals to UI slots executing on the main Qt thread."""
        self.signals.agent_log.connect(self._handle_agent_log)
        self.signals.status_change.connect(self._handle_status_change)
        self.signals.agent_response.connect(self._handle_agent_response)
        self.signals.voice_transcript.connect(self._handle_voice_transcript)
        self.signals.toggle_visibility.connect(self.toggle_window, Qt.ConnectionType.QueuedConnection)
        self.signals.show_hud.connect(self.show_and_focus, Qt.ConnectionType.QueuedConnection)
        self.signals.adjust_geometry.connect(self._snap_geometry)
        self.signals.trigger_voice.connect(self.trigger_voice)
        self.signals.trigger_vision.connect(self.trigger_vision)
        self.signals.trigger_stats.connect(self.trigger_stats)
        self.signals.clear_feed.connect(self.clear_history)
        self.signals.stop_speech.connect(self.stop_speech)
        self.signals.exit_app.connect(self.exit_app)


    def _build_ui(self) -> None:
        """Build the glassmorphic HUD layout and widgets."""
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(0)

        # Central Rounded Glass Container
        self.container = QFrame(self)
        self.container.setObjectName("Container")
        self.container.setStyleSheet(f"""
            #Container {{
                background-color: {BG_DARK};
                border: 1px solid {BORDER_CYAN};
                border-radius: 16px;
            }}
        """)

        # Drop Shadow for Depth & Glow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setColor(QColor(6, 182, 212, 70))
        shadow.setOffset(0, 4)
        self.container.setGraphicsEffect(shadow)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(18, 14, 18, 16)
        container_layout.setSpacing(10)

        # --- Top Header Bar ---
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        # Logo / Name
        self.title_label = QLabel("⚡ JARVIS", self.container)
        self.title_label.setStyleSheet(f"""
            color: {ACCENT_CYAN};
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 1px;
        """)

        # Status Pill Badge
        self.status_badge = QLabel("● IDLE", self.container)
        self.status_badge.setObjectName("StatusBadge")
        self._update_status_badge_style("IDLE")

        header_layout.addWidget(self.title_label)
        header_layout.addWidget(self.status_badge)
        header_layout.addStretch()

        # Keyboard Shortcut Hint
        shortcut_hint = QLabel("Ctrl+Space / Esc", self.container)
        shortcut_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        header_layout.addWidget(shortcut_hint)

        # Close / Hide Button
        self.btn_hide = QPushButton("✕", self.container)
        self.btn_hide.setFixedSize(22, 22)
        self.btn_hide.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_hide.setToolTip("Hide HUD (Esc)")
        self.btn_hide.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {TEXT_MUTED};
                font-size: 12px;
                font-weight: bold;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: rgba(244, 63, 94, 0.2);
                color: #f87171;
            }}
        """)
        self.btn_hide.clicked.connect(self.hide)
        header_layout.addWidget(self.btn_hide)

        container_layout.addLayout(header_layout)

        # --- Query Input Bar ---
        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)

        self.input_line = QLineEdit(self.container)
        self.input_line.setObjectName("QueryInput")
        self.input_line.setPlaceholderText("Ask JARVIS or speak... (Ctrl+Space to toggle, Esc to hide)")
        self.input_line.setStyleSheet(f"""
            QLineEdit {{
                background-color: rgba(30, 41, 59, 0.7);
                border: 1px solid rgba(148, 163, 184, 0.25);
                border-radius: 10px;
                padding: 9px 14px;
                color: {TEXT_PRIMARY};
                font-size: 13px;
                selection-background-color: {ACCENT_CYAN};
            }}
            QLineEdit:focus {{
                border: 1px solid {BORDER_FOCUS};
                background-color: rgba(15, 23, 42, 0.9);
            }}
        """)
        self.input_line.returnPressed.connect(self._on_submit_pressed)
        input_layout.addWidget(self.input_line)

        # Submit Action Button
        self.btn_submit = QPushButton("↵", self.container)
        self.btn_submit.setFixedSize(36, 36)
        self.btn_submit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_submit.setToolTip("Submit Query (Enter)")
        self.btn_submit.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT_CYAN};
                border: none;
                border-radius: 10px;
                color: #0f172a;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #22d3ee;
            }}
            QPushButton:pressed {{
                background-color: #0891b2;
            }}
        """)
        self.btn_submit.clicked.connect(self._on_submit_pressed)
        input_layout.addWidget(self.btn_submit)

        container_layout.addLayout(input_layout)

        # --- Action Chips Bar ---
        chips_layout = QHBoxLayout()
        chips_layout.setSpacing(6)

        chip_css = f"""
            QPushButton {{
                background-color: rgba(30, 41, 59, 0.55);
                border: 1px solid rgba(148, 163, 184, 0.2);
                border-radius: 8px;
                color: {TEXT_MUTED};
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: rgba(51, 65, 85, 0.85);
                border-color: {BORDER_CYAN};
                color: #38bdf8;
            }}
            QPushButton:pressed {{
                background-color: rgba(14, 116, 144, 0.4);
            }}
        """

        self.btn_voice = QPushButton("🎤 Voice", self.container)
        self.btn_voice.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_voice.setStyleSheet(chip_css)
        self.btn_voice.clicked.connect(self.trigger_voice)
        chips_layout.addWidget(self.btn_voice)

        self.btn_vision = QPushButton("👁️ Vision", self.container)
        self.btn_vision.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_vision.setStyleSheet(chip_css)
        self.btn_vision.clicked.connect(self.trigger_vision)
        chips_layout.addWidget(self.btn_vision)

        self.btn_stats = QPushButton("📊 Telemetry", self.container)
        self.btn_stats.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stats.setStyleSheet(chip_css)
        self.btn_stats.clicked.connect(self.trigger_stats)
        chips_layout.addWidget(self.btn_stats)

        # Stop Speech Pill (Visible when speaking or controllable)
        self.btn_stop = QPushButton("🛑 Stop", self.container)
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setObjectName("BtnStop")
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background-color: rgba(244, 63, 94, 0.15);
                border: 1px solid rgba(244, 63, 94, 0.4);
                border-radius: 8px;
                color: #fda4af;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(244, 63, 94, 0.35);
                color: #ffffff;
            }
        """)
        self.btn_stop.clicked.connect(self.stop_speech)
        self.btn_stop.setVisible(False)
        chips_layout.addWidget(self.btn_stop)

        chips_layout.addStretch()

        self.btn_clear = QPushButton("🧹 Clear", self.container)
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.setStyleSheet(chip_css)
        self.btn_clear.clicked.connect(self.clear_history)
        chips_layout.addWidget(self.btn_clear)

        container_layout.addLayout(chips_layout)

        # --- Collapsible ReAct Reasoning Drawer ---
        self.react_log = QTextEdit(self.container)
        self.react_log.setObjectName("ReActLog")
        self.react_log.setReadOnly(True)
        self.react_log.setMaximumHeight(140)
        self.react_log.setMinimumHeight(60)
        self.react_log.setStyleSheet("""
            QTextEdit {
                background-color: rgba(10, 15, 30, 0.85);
                border: 1px solid rgba(6, 182, 212, 0.25);
                border-radius: 10px;
                color: #94a3b8;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                padding: 8px;
            }
        """)
        self.react_log.setVisible(False)
        container_layout.addWidget(self.react_log)

        # --- Formatted Response Display ---
        self.response_box = QTextBrowser(self.container)
        self.response_box.setObjectName("ResponseBox")
        self.response_box.setReadOnly(True)
        self.response_box.setOpenExternalLinks(True)
        self.response_box.setMaximumHeight(260)
        self.response_box.setMinimumHeight(70)
        self.response_box.setStyleSheet(f"""
            QTextBrowser {{
                background-color: rgba(15, 23, 42, 0.8);
                border: 1px solid rgba(148, 163, 184, 0.2);
                border-radius: 10px;
                color: {TEXT_PRIMARY};
                font-size: 13px;
                line-height: 1.4;
                padding: 10px;
            }}
        """)
        self.response_box.setVisible(False)
        container_layout.addWidget(self.response_box)

        root_layout.addWidget(self.container)

        # Snug initial geometry
        self._snap_geometry()

    def _update_status_badge_style(self, status: str) -> None:
        """Update status badge text and colored indicator."""
        st = status.upper()
        if st == "IDLE":
            color = "#34d399"  # Emerald
            bg = "rgba(52, 211, 153, 0.15)"
            border = "rgba(52, 211, 153, 0.3)"
        elif st in ("THINKING", "EXECUTING TOOL"):
            color = "#fbbf24"  # Amber
            bg = "rgba(251, 191, 36, 0.15)"
            border = "rgba(251, 191, 36, 0.3)"
        elif st == "SPEAKING":
            color = "#c084fc"  # Purple
            bg = "rgba(192, 132, 252, 0.2)"
            border = "rgba(192, 132, 252, 0.4)"
        elif st == "LISTENING":
            color = "#38bdf8"  # Cyan
            bg = "rgba(56, 189, 248, 0.2)"
            border = "rgba(56, 189, 248, 0.4)"
        else:  # ERROR
            color = "#f87171"  # Rose
            bg = "rgba(248, 113, 113, 0.2)"
            border = "rgba(248, 113, 113, 0.4)"

        self.status_badge.setText(f"● {st}")
        self.status_badge.setStyleSheet(f"""
            QLabel#StatusBadge {{
                color: {color};
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 10px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: 600;
            }}
        """)

        # Toggle Stop button visibility on speech
        if hasattr(self, "btn_stop"):
            self.btn_stop.setVisible(st == "SPEAKING")

    def _center_window(self) -> None:
        """Center the HUD horizontally near the top (~10% display height)."""
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            pos_x = (screen_geo.width() - self.hud_width) // 2 + screen_geo.x()
            pos_y = int(screen_geo.height() * 0.10) + screen_geo.y()
            self.move(pos_x, pos_y)

    def _snap_geometry(self) -> None:
        """
        Dynamically snap the window bounding box tightly to the container size
        so no invisible click-blocking box covers the desktop underneath.
        """
        self.container.adjustSize()
        self.adjustSize()

    # --- ReAct & Worker Signals Integration ---

    def _on_agent_log(self, channel: str, message: str) -> None:
        """Callback from JarvisAgent thread; emits Qt signal safely."""
        self.signals.agent_log.emit(channel, message)

        ch = channel.lower()
        if ch in ("thought", "plan", "critique"):
            self.signals.status_change.emit("THINKING")
        elif ch in ("action", "action_input"):
            self.signals.status_change.emit("EXECUTING TOOL")
        elif ch == "observation":
            self.signals.status_change.emit("THINKING")
        elif ch == "final_answer":
            self.signals.status_change.emit("IDLE")
        elif ch == "error":
            self.signals.status_change.emit("ERROR")

    def _handle_agent_log(self, channel: str, message: str) -> None:
        """Append streamed reasoning step into the collapsible ReAct drawer."""
        ch = channel.upper()
        if ch in ("THOUGHT", "PLAN"):
            color = "#fbbf24"
        elif ch in ("ACTION", "ACTION_INPUT"):
            color = "#38bdf8"
        elif ch == "OBSERVATION":
            color = "#34d399"
        elif ch == "ERROR":
            color = "#f87171"
        else:
            color = "#94a3b8"

        escaped_msg = html.escape(message)
        line_html = f"<div style='margin-bottom: 3px;'><b style='color: {color};'>[{ch}]</b> {escaped_msg}</div>"

        if not self.react_log.isVisible():
            self.react_log.setVisible(True)
            self._snap_geometry()

        self.react_log.append(line_html)
        # Auto scroll to bottom
        sb = self.react_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _handle_status_change(self, status: str) -> None:
        """Update status badge on the main thread."""
        self._update_status_badge_style(status)

    def _handle_agent_response(self, response: str) -> None:
        """Display final formatted response and snug-fit the canvas."""
        if not response:
            return

        # Render response with basic markdown-friendly HTML formatting
        escaped_resp = html.escape(response)
        formatted_html = escaped_resp.replace("\n\n", "<p style='margin: 6px 0;'></p>").replace("\n", "<br>")

        self.response_box.setHtml(f"<div style='color: {TEXT_PRIMARY}; font-size: 13px;'>{formatted_html}</div>")
        self.response_box.setVisible(True)
        self._snap_geometry()

    def _handle_voice_transcript(self, transcript: str) -> None:
        """Populate input line with transcribed voice speech."""
        self.input_line.setText(transcript)

    # --- User Actions & Background Execution ---

    def _on_submit_pressed(self) -> None:
        """Handle Enter key or submit button click."""
        text = self.input_line.text().strip()
        if text:
            self.submit_query(text)

    def submit_query(self, query: str) -> None:
        """Execute agent query in a background worker thread."""
        if not query or not query.strip():
            return

        with self._lock:
            if self._is_processing:
                self.signals.agent_log.emit("info", "Busy processing previous request...")
                return
            self._is_processing = True

        self.input_line.clear()
        self.input_line.setPlaceholderText(f"Executing: {query[:45]}...")

        def _worker():
            try:
                self.signals.status_change.emit("THINKING")
                response = self.agent.run(query.strip())
                self.signals.agent_response.emit(str(response) if response else "Done.")

                # Vocalize response if TTS available
                if response and self.vm and self.vm.is_tts_available:
                    self.signals.status_change.emit("SPEAKING")
                    self.vm.speak(str(response), blocking=True)


            except Exception as e:
                self.signals.agent_log.emit("error", str(e))
                self.signals.status_change.emit("ERROR")
            finally:
                with self._lock:
                    self._is_processing = False
                self.signals.status_change.emit("IDLE")
                # Restore placeholder on main thread
                QTimer.singleShot(100, lambda: self.input_line.setPlaceholderText("Ask JARVIS or speak... (Ctrl+Space to toggle, Esc to hide)"))

        threading.Thread(target=_worker, daemon=True, name="JARVIS-QtHUD-Worker").start()

    def trigger_voice(self) -> None:
        """Trigger microphone capture and pipe speech into submit_query."""
        with self._lock:
            if self._is_processing:
                return
            self._is_processing = True

        def _voice_worker():
            try:
                self.signals.status_change.emit("LISTENING")
                self.signals.agent_log.emit("info", "Listening to microphone...")
                spoken = self.vm.listen_once()
                if spoken:
                    self.signals.voice_transcript.emit(spoken)
                    with self._lock:
                        self._is_processing = False
                    self.submit_query(spoken)
                else:
                    self.signals.agent_log.emit("info", "No speech detected.")
                    self.signals.status_change.emit("IDLE")
                    with self._lock:
                        self._is_processing = False
            except Exception as e:
                self.signals.agent_log.emit("error", str(e))
                self.signals.status_change.emit("ERROR")
                with self._lock:
                    self._is_processing = False

        threading.Thread(target=_voice_worker, daemon=True, name="JARVIS-Voice-Worker").start()

    def trigger_vision(self) -> None:
        """Trigger screenshot capture and vision inquiry."""
        self.submit_query("Take a screenshot of the current screen and analyze what is visible on display.")

    def trigger_stats(self) -> None:
        """Trigger system telemetry inquiry."""
        self.submit_query("Check current system stats including CPU usage, RAM utilization, and disk status.")

    def clear_history(self) -> None:
        """Reset conversation memory and hide expanded drawers."""
        self.agent.reset()
        self.react_log.clear()
        self.react_log.setVisible(False)
        self.response_box.clear()
        self.response_box.setVisible(False)
        self.signals.status_change.emit("IDLE")
        self._snap_geometry()

    def stop_speech(self) -> None:
        """Interrupt active speech synthesis immediately."""
        if self.vm:
            self.vm.stop_speaking()
        self.signals.status_change.emit("IDLE")

    # --- Hotkey, Escape & Window Management ---

    def _register_hotkey(self) -> None:
        """Register the system-wide global hotkey hook with fallback support."""
        if not HAS_KEYBOARD or not self.hotkey:
            return

        candidates = [self.hotkey]
        if self.fallback_hotkey and self.fallback_hotkey not in candidates:
            candidates.append(self.fallback_hotkey)

        for hk in candidates:
            try:
                keyboard.add_hotkey(hk, lambda: self.signals.toggle_visibility.emit())
                self._hotkey_hooked = True
                self.hotkey = hk
                break
            except Exception:
                self._hotkey_hooked = False

    def toggle_window(self) -> None:
        """Toggle HUD visibility smoothly and reliably regain focus over active windows."""
        if self.isVisible():
            self.hide()
        else:
            if self.isMinimized():
                self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
            self.show()
            self.raise_()
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
            self.activateWindow()
            self.input_line.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def show_and_focus(self) -> None:
        """Bring floating HUD to foreground, unminimize if needed, and focus input."""
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.activateWindow()
        self.input_line.setFocus(Qt.FocusReason.ActiveWindowFocusReason)


    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle Escape key: stop speech if speaking, else hide HUD."""
        if event.key() == Qt.Key.Key_Escape:
            if self.vm and self.vm.is_speaking():
                self.stop_speech()
            else:
                self.hide()
            event.accept()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Enable dragging anywhere on the header / container."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update window position smoothly while dragging."""
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Release drag position."""
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def exit_app(self) -> None:
        """Clean up resources and terminate application."""
        if HAS_KEYBOARD and self._hotkey_hooked:
            try:
                keyboard.unhook_all_hotkeys()
            except Exception:
                pass
            self._hotkey_hooked = False

        try:
            if self.vm:
                self.vm.stop_speaking()
            browser_controller.close_browser()
        except Exception:
            pass

        if self.tray_manager:
            try:
                self.tray_manager.stop()
            except Exception:
                pass

        app = QApplication.instance()
        if app:
            app.quit()
        else:
            sys.exit(0)


def run_qt_hud(agent: JarvisAgent, vm: Optional[VoiceManager] = None) -> None:
    """Launch the PySide6 HUD application and system tray hub."""
    from ui.tray_manager import TrayManager

    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)

    hud = QtHUD(agent=agent, vm=vm)

    # Bridge TrayManager with thread-safe Qt Signals
    class QtTrayProxy:
        def __init__(self, hud_instance: QtHUD):
            self.hud = hud_instance

        def toggle_hud(self):
            self.hud.signals.toggle_visibility.emit()

        def trigger_voice(self):
            self.hud.signals.trigger_voice.emit()

        def trigger_system_stats(self):
            self.hud.signals.trigger_stats.emit()

        def clear_output(self):
            self.hud.signals.clear_feed.emit()

        def shutdown(self):
            self.hud.signals.exit_app.emit()

    from daemon.notifier import toast_notifier
    toast_notifier.set_default_activation_callback(lambda: hud.signals.show_hud.emit())

    proxy = QtTrayProxy(hud)
    tray = TrayManager(controller=proxy, hotkey=None)
    hud.tray_manager = tray

    tray.start()


    hud.show()
    hud.raise_()
    hud.activateWindow()

    try:
        sys.exit(app.exec())
    finally:
        hud.exit_app()
