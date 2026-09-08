"""
Unit tests for JARVIS Floating HUD, AppController, and TrayManager (Phase 4).
Tests window geometry, status transitions, activity feeding, asynchronous
controller execution, and system tray management.
"""

import threading
import time
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image

from agent.core import JarvisAgent
from ui.app_controller import AppController
from ui.floating_hud import JarvisFloatingHUD
from ui.tray_manager import TrayManager
from voice.voice_manager import VoiceManager


@pytest.fixture(scope="module")
def hud_instance():
    """Create a single headless/hidden JarvisFloatingHUD instance for the test module."""
    mock_ctrl = MagicMock(spec=AppController)
    hud = JarvisFloatingHUD(controller=mock_ctrl, width=700, compact_height=75, expanded_height=350)
    hud.withdraw()  # Keep hidden during automated test execution
    yield hud
    try:
        hud.destroy()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def reset_hud_state(hud_instance):
    """Reset the shared HUD instance before each test."""
    mock_ctrl = MagicMock(spec=AppController)
    hud_instance.controller = mock_ctrl
    hud_instance.is_visible = True
    hud_instance.collapse_window()
    yield



def test_hud_initialization_and_geometry(hud_instance):
    hud = hud_instance
    assert hud.hud_width == 700
    assert hud.compact_height == 75
    assert hud.expanded_height == 350
    assert hud.current_height == 75
    assert hud.is_expanded is False
    assert hud.is_visible is True
    assert hud.status_badge is not None
    assert hud.entry is not None
    assert hud.activity_box is not None


def test_hud_visibility_toggling(hud_instance):
    hud = hud_instance

    hud.hide_window()
    assert hud.is_visible is False

    hud.show_window()
    assert hud.is_visible is True

    hud.toggle_window()
    assert hud.is_visible is False

    hud.toggle_window()
    assert hud.is_visible is True


def test_hud_expansion_and_collapse(hud_instance):
    hud = hud_instance

    hud.expand_window()
    assert hud.is_expanded is True
    assert hud.current_height == 350

    # Expand again should be idempotent
    hud.expand_window()
    assert hud.is_expanded is True

    hud.collapse_window()
    assert hud.is_expanded is False
    assert hud.current_height == 75


def test_hud_status_badge_updates(hud_instance):
    hud = hud_instance

    hud.set_status("THINKING")
    assert "THINKING" in hud.status_badge.cget("text")

    hud.set_status("LISTENING")
    assert "LISTENING" in hud.status_badge.cget("text")

    hud.set_status("EXECUTING TOOL")
    assert "TOOL" in hud.status_badge.cget("text")

    hud.set_status("IDLE")
    assert "IDLE" in hud.status_badge.cget("text")


def test_hud_activity_and_response_feed(hud_instance):
    hud = hud_instance

    hud.append_activity("thought", "Analyzing system state")
    assert hud.is_expanded is True
    content = hud.activity_box.get("1.0", "end")
    assert "Analyzing system state" in content
    assert "[Thought]" in content

    hud.display_response("All systems are 100% operational.")
    content = hud.activity_box.get("1.0", "end")
    assert "All systems are 100% operational." in content
    assert "[JARVIS]" in content

    hud.clear_activity()
    cleared_content = hud.activity_box.get("1.0", "end").strip()
    assert cleared_content == ""
    assert hud.is_expanded is False


def test_hud_button_callbacks_dispatch_to_controller(hud_instance):
    hud = hud_instance
    ctrl = hud.controller

    hud._on_mic_click()
    ctrl.trigger_voice.assert_called_once()

    hud._on_vision_click()
    ctrl.trigger_screen_vision.assert_called_once()

    hud._on_stats_click()
    ctrl.trigger_system_stats.assert_called_once()

    hud.entry.insert(0, "Check CPU load")
    hud._on_submit()
    ctrl.handle_user_query.assert_called_once_with("Check CPU load")
    assert hud.entry.get() == ""


def test_app_controller_query_worker():
    mock_agent = MagicMock(spec=JarvisAgent)
    mock_agent.run.return_value = "CPU load is 12%."
    mock_vm = MagicMock(spec=VoiceManager)
    mock_vm.is_tts_available = True
    mock_hud = MagicMock(spec=JarvisFloatingHUD)

    # Immediately execute callbacks passed to after()
    def fake_after(ms, func, *args):
        if callable(func):
            func(*args)
    mock_hud.after = MagicMock(side_effect=fake_after)

    controller = AppController(agent=mock_agent, vm=mock_vm, hud=mock_hud, voice_feedback=True)

    controller.handle_user_query("What is the CPU usage?")
    time.sleep(0.1)  # Allow worker thread to complete

    mock_agent.run.assert_called_once_with("What is the CPU usage?")
    mock_hud.display_response.assert_called_once_with("CPU load is 12%.")
    mock_vm.speak.assert_called_once_with("CPU load is 12%.", blocking=True)



def test_app_controller_on_agent_log_callback():
    mock_agent = MagicMock(spec=JarvisAgent)
    mock_hud = MagicMock(spec=JarvisFloatingHUD)
    def fake_after(ms, func, *args):
        if callable(func):
            func(*args)
    mock_hud.after = MagicMock(side_effect=fake_after)

    controller = AppController(agent=mock_agent, hud=mock_hud)

    # Test thought channel
    controller._on_agent_log("thought", "Need to execute tool")
    mock_hud.set_status.assert_called_with("THINKING")
    mock_hud.append_activity.assert_called_with("thought", "Need to execute tool")

    # Test action channel
    controller._on_agent_log("action", "get_system_stats")
    mock_hud.set_status.assert_called_with("EXECUTING TOOL")
    mock_hud.append_activity.assert_called_with("action", "get_system_stats")

    # Test error channel
    controller._on_agent_log("error", "Process failed")
    mock_hud.set_status.assert_called_with("ERROR")


def test_app_controller_quick_actions():
    mock_agent = MagicMock(spec=JarvisAgent)
    mock_vm = MagicMock(spec=VoiceManager)
    mock_vm.listen_once.return_value = "Hello assistant"
    mock_hud = MagicMock(spec=JarvisFloatingHUD)
    def fake_after(ms, func, *args):
        if callable(func):
            func(*args)
    mock_hud.after = MagicMock(side_effect=fake_after)

    controller = AppController(agent=mock_agent, vm=mock_vm, hud=mock_hud)

    with patch.object(controller, "handle_user_query") as mock_handle:
        # 1. Vision trigger
        controller.trigger_screen_vision()
        mock_handle.assert_called_with("Take a screenshot of the current screen and analyze what is visible on display.")

        # 2. Stats trigger
        controller.trigger_system_stats()
        mock_handle.assert_called_with("Check current system stats including CPU usage, RAM utilization, and disk status.")

        # 3. Voice trigger
        controller.trigger_voice()
        time.sleep(0.1)
        mock_vm.listen_once.assert_called_once()
        mock_handle.assert_called_with("Hello assistant")

    # 4. Clear output
    controller.clear_output()
    mock_agent.reset.assert_called_once()
    mock_hud.clear_activity.assert_called_once()


def test_tray_manager_icon_generation():
    icon_image = TrayManager.create_arc_reactor_icon(64)
    assert isinstance(icon_image, Image.Image)
    assert icon_image.size == (64, 64)
    assert icon_image.mode == "RGBA"


def test_tray_manager_start_and_stop():
    mock_ctrl = MagicMock(spec=AppController)
    tray = TrayManager(controller=mock_ctrl, hotkey="ctrl+space")

    with patch("pystray.Icon") as mock_pystray_icon_cls, \
         patch("keyboard.add_hotkey") as mock_add_hotkey, \
         patch("keyboard.unhook_all_hotkeys") as mock_unhook:

        mock_icon_instance = MagicMock()
        mock_pystray_icon_cls.return_value = mock_icon_instance

        tray.start()

        mock_pystray_icon_cls.assert_called_once()
        mock_add_hotkey.assert_called_once_with("ctrl+space", mock_ctrl.toggle_hud)
        assert tray._hotkey_hooked is True

        tray.stop()
        mock_unhook.assert_called_once()
        mock_icon_instance.stop.assert_called_once()
        assert tray._hotkey_hooked is False

