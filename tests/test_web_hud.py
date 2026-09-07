"""
Unit tests for PyWebView Floating HUD and Python-JS Bridge (Phase 4 Rebuild).
Tests WebHUDAPI query dispatching, agent log streaming, window visibility toggling,
quick actions, and HTML/JS frontend asset integrity.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from agent.core import JarvisAgent
from ui.web_hud import WebHUD, WebHUDAPI
from voice.voice_manager import VoiceManager


def test_hud_html_asset_exists_and_valid():
    """Verify that ui/assets/hud.html exists and contains necessary DOM elements and bridge hooks."""
    html_path = Path("ui/assets/hud.html")
    assert html_path.exists(), "ui/assets/hud.html must exist"

    content = html_path.read_text(encoding="utf-8")
    assert "pywebview-drag-region" in content
    assert 'id="query-input"' in content
    assert 'id="status-pill"' in content
    assert 'id="react-drawer"' in content
    assert 'id="telemetry-gauges"' in content
    assert 'id="response-container"' in content

    # Check exposed callback hooks in JavaScript
    assert "window.onAgentLog" in content
    assert "window.onAgentResponse" in content
    assert "window.onStatusChange" in content
    assert "window.onVoiceTranscript" in content
    assert "window.clearFeed" in content
    assert "window.focusInput" in content


def test_web_hud_api_initialization():
    """Verify WebHUDAPI initializes properly and sets agent log callback."""
    mock_agent = MagicMock(spec=JarvisAgent)
    mock_vm = MagicMock(spec=VoiceManager)

    api = WebHUDAPI(agent=mock_agent, vm=mock_vm)
    assert api.is_visible is True
    assert api._is_processing is False
    assert mock_agent.log_callback == api._on_agent_log


def test_web_hud_api_eval_js_safe():
    """Verify _eval_js executes evaluate_js safely on the associated window."""
    mock_agent = MagicMock(spec=JarvisAgent)
    api = WebHUDAPI(agent=mock_agent)
    mock_window = MagicMock()
    api.set_window(mock_window)

    api._eval_js("console.log('test')")
    mock_window.evaluate_js.assert_called_once_with("console.log('test')")

    # Verify no exception is raised if evaluate_js fails
    mock_window.evaluate_js.side_effect = Exception("Window destroyed")
    api._eval_js("console.log('fail')")


def test_web_hud_api_on_agent_log_streaming():
    """Verify agent log events format correctly and update status in JS."""
    mock_agent = MagicMock(spec=JarvisAgent)
    api = WebHUDAPI(agent=mock_agent)
    mock_window = MagicMock()
    api.set_window(mock_window)

    # 1. Thought channel
    api._on_agent_log("thought", "Analyzing system state")
    calls = [call[0][0] for call in mock_window.evaluate_js.call_args_list]
    assert any("window.onAgentLog" in c and "Analyzing system state" in c for c in calls)
    assert any("window.onStatusChange('THINKING')" in c for c in calls)

    mock_window.reset_mock()

    # 2. Action channel
    api._on_agent_log("action", "get_system_stats")
    calls = [call[0][0] for call in mock_window.evaluate_js.call_args_list]
    assert any("window.onStatusChange('EXECUTING TOOL')" in c for c in calls)

    mock_window.reset_mock()

    # 3. Error channel
    api._on_agent_log("error", "Process crashed")
    calls = [call[0][0] for call in mock_window.evaluate_js.call_args_list]
    assert any("window.onStatusChange('ERROR')" in c for c in calls)


def test_web_hud_api_submit_query_worker():
    """Verify submit_query executes agent.run in background and sends response to JS."""
    mock_agent = MagicMock(spec=JarvisAgent)
    mock_agent.run.return_value = "CPU load is 15% and RAM is 45%."
    mock_vm = MagicMock(spec=VoiceManager)
    mock_vm.is_tts_available = True

    api = WebHUDAPI(agent=mock_agent, vm=mock_vm)
    mock_window = MagicMock()
    api.set_window(mock_window)

    api.submit_query("Report system status")
    time.sleep(0.1)  # Allow worker thread to finish

    mock_agent.run.assert_called_once_with("Report system status")
    mock_vm.speak.assert_called_once_with("CPU load is 15% and RAM is 45%.", blocking=True)

    calls = [call[0][0] for call in mock_window.evaluate_js.call_args_list]
    assert any("window.onAgentResponse" in c and "CPU load is 15%" in c for c in calls)
    assert any("window.onStatusChange('IDLE')" in c for c in calls)


def test_web_hud_api_quick_actions():
    """Verify quick action triggers dispatch queries or clear memory."""
    mock_agent = MagicMock(spec=JarvisAgent)
    mock_vm = MagicMock(spec=VoiceManager)
    mock_vm.listen_once.return_value = "open notepad"

    api = WebHUDAPI(agent=mock_agent, vm=mock_vm)
    mock_window = MagicMock()
    api.set_window(mock_window)

    with patch.object(api, "submit_query") as mock_submit:
        # Vision action
        api.trigger_vision()
        mock_submit.assert_called_with("Take a screenshot of the current screen and analyze what is visible on display.")

        # Stats action
        api.trigger_stats()
        mock_submit.assert_called_with("Check current system stats including CPU usage, RAM utilization, and disk status.")

        # Voice action
        api.trigger_voice()
        time.sleep(0.1)
        mock_vm.listen_once.assert_called_once()
        mock_submit.assert_called_with("open notepad")

    # Clear history action
    api.clear_history()
    mock_agent.reset.assert_called_once()
    calls = [call[0][0] for call in mock_window.evaluate_js.call_args_list]
    assert any("window.clearFeed" in c for c in calls)


def test_web_hud_api_window_visibility_toggling():
    """Verify hide, show, and toggle methods update window state."""
    mock_agent = MagicMock(spec=JarvisAgent)
    api = WebHUDAPI(agent=mock_agent)
    mock_window = MagicMock()
    api.set_window(mock_window)

    # Hide
    api.hide_window()
    assert api.is_visible is False
    mock_window.hide.assert_called_once()

    # Show
    api.show_window()
    assert api.is_visible is True
    mock_window.show.assert_called_once()

    # Toggle to hide
    api.toggle_window()
    assert api.is_visible is False

    # Toggle to show
    api.toggle_window()
    assert api.is_visible is True


def test_web_hud_position_calculation():
    """Verify WebHUD._calculate_position calculates centered screen coordinates."""
    mock_agent = MagicMock(spec=JarvisAgent)
    hud = WebHUD(agent=mock_agent, width=800, height=600)

    pos_x, pos_y = hud._calculate_position()
    assert isinstance(pos_x, int)
    assert isinstance(pos_y, int)
    assert pos_x >= 0
    assert pos_y >= 0


def test_web_hud_create_window_valid_color():
    """Verify webview.create_window succeeds with #000000 hex color and transparent=True without ValueError."""
    import webview
    # Ensure background_color="#000000" and transparent=True does not raise ValueError
    window = webview.create_window(
        title="JARVIS Test Window",
        html="<div>test</div>",
        frameless=True,
        on_top=True,
        transparent=True,
        background_color="#000000",
    )
    assert window is not None
    assert window.transparent is True
    assert window.background_color == "#000000"


def test_web_hud_api_resize_window():
    """Verify WebHUDAPI.resize_window calls window.resize with clamped bounds."""
    mock_agent = MagicMock(spec=JarvisAgent)
    api = WebHUDAPI(agent=mock_agent)
    mock_window = MagicMock()
    mock_window.width = 760
    api.set_window(mock_window)

    # Test within range
    api.resize_window(350)
    mock_window.resize.assert_called_with(760, 350)

    # Test lower bound clamp
    api.resize_window(100)
    mock_window.resize.assert_called_with(760, 200)

    # Test upper bound clamp
    api.resize_window(900)
    mock_window.resize.assert_called_with(760, 680)


