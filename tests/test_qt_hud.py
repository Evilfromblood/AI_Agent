"""
Unit tests for Native PySide6 Translucent Floating HUD (Phase 6).
Tests QtHUD window initialization, attributes, thread-safe signal routing,
collapsible ReAct reasoning drawer, quick actions, speech interrupt, and Escape key behavior.
"""

import os
import sys
import time
from unittest.mock import ANY, MagicMock, patch
import pytest

# Ensure offscreen rendering for headless testing environments
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from agent.core import JarvisAgent
from ui.qt_hud import QtHUD, HUDSignals
from voice.voice_manager import VoiceManager


@pytest.fixture(scope="session")
def qapp():
    """Ensure a singleton QApplication exists for all Qt tests."""
    app = QApplication.instance()
    if not app:
        app = QApplication(["pytest", "-platform", "offscreen"])
    yield app


@pytest.fixture
def mock_agent():
    agent = MagicMock(spec=JarvisAgent)
    agent.run.return_value = "System is running optimally."
    return agent


@pytest.fixture
def mock_vm():
    vm = MagicMock(spec=VoiceManager)
    vm.is_speaking.return_value = False
    vm.is_tts_available = True
    vm.is_stt_available = True
    vm.listen_once.return_value = "check disk status"
    return vm


@pytest.fixture
def hud(qapp, mock_agent, mock_vm):
    """Instantiate a QtHUD with mocked agent and voice manager."""
    with patch("ui.qt_hud.HAS_KEYBOARD", False):  # Avoid binding real global hotkeys in tests
        hud_instance = QtHUD(agent=mock_agent, vm=mock_vm, width=720)
    hud_instance.show()
    qapp.processEvents()
    yield hud_instance
    hud_instance.close()


def test_qt_hud_window_properties(hud):
    """Verify frameless, translucent, and topmost window attributes."""
    flags = hud.windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.Tool

    assert hud.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
    assert hud.width() == 720
    assert hud.windowTitle() == "JARVIS Desktop HUD"


def test_qt_hud_components_exist(hud):
    """Verify all critical UI components are instantiated."""
    assert hud.container is not None
    assert hud.title_label is not None
    assert hud.status_badge is not None
    assert hud.input_line is not None
    assert hud.btn_submit is not None
    assert hud.btn_voice is not None
    assert hud.btn_vision is not None
    assert hud.btn_stats is not None
    assert hud.btn_stop is not None
    assert hud.btn_clear is not None
    assert hud.react_log is not None
    assert hud.response_box is not None

    # Collapsed by default
    assert hud.react_log.isVisible() is False
    assert hud.response_box.isVisible() is False
    assert "Ctrl+Space" in hud.input_line.placeholderText()
    assert hud.hotkey == "ctrl+space"


def test_qt_hud_agent_log_streaming(hud, qapp):
    """Verify agent reasoning logs expand the ReAct drawer and update status."""
    # 1. Thought channel
    hud._on_agent_log("thought", "Analyzing system resources...")
    qapp.processEvents()

    assert hud.react_log.isVisible() is True
    assert "THOUGHT" in hud.react_log.toHtml()
    assert "Analyzing system resources..." in hud.react_log.toHtml()
    assert "THINKING" in hud.status_badge.text()

    # 2. Action channel
    hud._on_agent_log("action", "get_system_stats")
    qapp.processEvents()
    assert "ACTION" in hud.react_log.toHtml()
    assert "EXECUTING TOOL" in hud.status_badge.text()

    # 3. Observation channel
    hud._on_agent_log("observation", "CPU load: 15%")
    qapp.processEvents()
    assert "OBSERVATION" in hud.react_log.toHtml()
    assert "THINKING" in hud.status_badge.text()

    # 4. Error channel
    hud._on_agent_log("error", "Failed to access sensor")
    qapp.processEvents()
    assert "ERROR" in hud.react_log.toHtml()
    assert "ERROR" in hud.status_badge.text()


def test_qt_hud_submit_query_worker(hud, mock_agent, mock_vm, qapp):
    """Verify submit_query executes agent.run in background and renders response."""
    hud.submit_query("Report system status")

    # Wait for worker thread to complete
    timeout = 2.0
    start = time.time()
    while hud._is_processing and (time.time() - start < timeout):
        qapp.processEvents()
        time.sleep(0.05)

    qapp.processEvents()

    mock_agent.run.assert_called_once_with("Report system status")
    assert hud.response_box.isVisible() is True
    assert "System is running optimally." in hud.response_box.toPlainText()
    mock_vm.speak.assert_called_once_with("System is running optimally.", blocking=True)


def test_qt_hud_quick_actions(hud, mock_vm, qapp):
    """Verify quick action triggers dispatch queries correctly."""
    with patch.object(hud, "submit_query") as mock_submit:
        # Vision action
        hud.trigger_vision()
        mock_submit.assert_called_with("Take a screenshot of the current screen and analyze what is visible on display.")

        # Stats action
        hud.trigger_stats()
        mock_submit.assert_called_with("Check current system stats including CPU usage, RAM utilization, and disk status.")

        # Voice action
        hud.trigger_voice()
        timeout = 2.0
        start = time.time()
        while hud._is_processing and (time.time() - start < timeout):
            qapp.processEvents()
            time.sleep(0.05)

        mock_vm.listen_once.assert_called_once()
        mock_submit.assert_called_with("check disk status")


def test_qt_hud_clear_history(hud, mock_agent, qapp):
    """Verify clear_history resets memory and collapses drawers."""
    hud.react_log.setVisible(True)
    hud.response_box.setVisible(True)

    hud.clear_history()
    qapp.processEvents()

    mock_agent.reset.assert_called_once()
    assert hud.react_log.isVisible() is False
    assert hud.response_box.isVisible() is False
    assert hud.react_log.toPlainText() == ""
    assert hud.response_box.toPlainText() == ""
    assert "IDLE" in hud.status_badge.text()


def test_qt_hud_stop_speech(hud, mock_vm, qapp):
    """Verify stop_speech halts voice playback immediately."""
    hud.stop_speech()
    qapp.processEvents()

    mock_vm.stop_speaking.assert_called_once()
    assert "IDLE" in hud.status_badge.text()


def test_qt_hud_escape_key_speaking(hud, mock_vm, qapp):
    """Verify pressing Escape when speaking stops speech and keeps HUD visible."""
    mock_vm.is_speaking.return_value = True
    hud.show()
    qapp.processEvents()

    with patch.object(hud, "stop_speech") as mock_stop:
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        hud.keyPressEvent(event)
        mock_stop.assert_called_once()
        assert hud.isVisible() is True


def test_qt_hud_escape_key_idle(hud, mock_vm, qapp):
    """Verify pressing Escape when idle hides the HUD."""
    mock_vm.is_speaking.return_value = False
    hud.show()
    qapp.processEvents()
    assert hud.isVisible() is True

    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    hud.keyPressEvent(event)
    qapp.processEvents()

    assert hud.isVisible() is False


def test_qt_hud_toggle_window(hud, qapp):
    """Verify toggle_window alternates visibility."""
    hud.hide()
    qapp.processEvents()
    assert hud.isVisible() is False

    hud.toggle_window()
    qapp.processEvents()
    assert hud.isVisible() is True

    hud.toggle_window()
    qapp.processEvents()
    assert hud.isVisible() is False


def test_qt_tray_proxy_integration(hud, qapp):
    """Verify tray controller proxy emits corresponding Qt signals."""
    from ui.qt_hud import run_qt_hud

    signals_received = []
    hud.signals.toggle_visibility.connect(lambda: signals_received.append("toggle"))
    hud.signals.trigger_voice.connect(lambda: signals_received.append("voice"))
    hud.signals.trigger_stats.connect(lambda: signals_received.append("stats"))
    hud.signals.clear_feed.connect(lambda: signals_received.append("clear"))
    hud.signals.exit_app.connect(lambda: signals_received.append("exit"))

    # Test signal emissions
    hud.signals.toggle_visibility.emit()
    hud.signals.trigger_voice.emit()
    hud.signals.trigger_stats.emit()
    hud.signals.clear_feed.emit()
    hud.signals.exit_app.emit()

    qapp.processEvents()

    assert signals_received == ["toggle", "voice", "stats", "clear", "exit"]


def test_qt_hud_hotkey_registration_and_fallback(qapp, mock_agent, mock_vm):
    """Verify QtHUD registers ctrl+space and falls back to ctrl+shift+space if needed."""
    with patch("keyboard.add_hotkey") as mock_add_hotkey:
        hud1 = QtHUD(agent=mock_agent, vm=mock_vm)
        mock_add_hotkey.assert_called_with("ctrl+space", ANY)
        assert hud1._hotkey_hooked is True
        hud1.close()

    # Simulate primary failure and fallback success
    with patch("keyboard.add_hotkey") as mock_add_hotkey:
        def side_effect(key, callback):
            if key == "ctrl+space":
                raise RuntimeError("Key bound by another app")
            return None
        mock_add_hotkey.side_effect = side_effect

        hud2 = QtHUD(agent=mock_agent, vm=mock_vm)
        assert mock_add_hotkey.call_count == 2
        assert hud2.hotkey == "ctrl+shift+space"
        assert hud2._hotkey_hooked is True
        hud2.close()
