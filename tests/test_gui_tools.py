"""
Unit tests for GUI automation, screen perception, and vision grounding tools.
"""

import os
import tempfile
from unittest.mock import MagicMock, patch
from tools.guardrails import guardrails
from tools.gui_tools import (
    analyze_screen_with_vision,
    click_screen_coordinate,
    send_system_hotkey,
    take_screenshot,
    type_screen_text,
)
from tools.registry import registry


def test_gui_tools_registered():
    names = registry.list_tool_names()
    assert "take_screenshot" in names
    assert "analyze_screen_with_vision" in names
    assert "click_screen_coordinate" in names
    assert "type_screen_text" in names
    assert "send_system_hotkey" in names


def test_take_screenshot():
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "screen.png")
        dummy_img = Image.new("RGB", (1280, 720), color="blue")
        with patch("tools.gui_tools.pyautogui.screenshot", return_value=dummy_img), \
             patch("tools.gui_tools.HAS_MSS", False):
            result = take_screenshot(filename=test_file)
            assert result["status"] == "success"
            assert os.path.exists(test_file)
            assert result["width"] == 1280
            assert result["height"] == 720


@patch("tools.gui_tools.pyautogui.size", return_value=(1920, 1080))
@patch("tools.gui_tools.pyautogui.click")
def test_click_screen_coordinate(mock_click, mock_size):
    # Valid click
    res = click_screen_coordinate(x=500, y=300, clicks=1, button="left")
    assert "Successfully clicked" in res
    mock_click.assert_called_with(x=500, y=300, clicks=1, button="left")

    # Out of bounds click
    res_err = click_screen_coordinate(x=2000, y=500)
    assert "out of screen bounds" in res_err.lower()

    # Negative bounds click
    res_err2 = click_screen_coordinate(x=-10, y=500)
    assert "out of screen bounds" in res_err2.lower()


@patch("tools.gui_tools.pyautogui.write")
@patch("tools.gui_tools.pyautogui.press")
def test_type_screen_text_safe(mock_press, mock_write):
    res = type_screen_text("Hello from JARVIS", press_enter=True)
    assert "Successfully typed text" in res
    mock_write.assert_called_once_with("Hello from JARVIS", interval=0.05)
    mock_press.assert_called_once_with("enter")


def test_type_screen_text_destructive_guardrail():
    # Set callback to deny
    guardrails.set_auth_callback(lambda reason, action: False)
    try:
        res = type_screen_text("rm -rf /")
        assert "Safety authorization denied" in res
    finally:
        guardrails.set_auth_callback(None)


@patch("tools.gui_tools.pyautogui.hotkey")
def test_send_system_hotkey_safe(mock_hotkey):
    res = send_system_hotkey(["ctrl", "c"])
    assert "Successfully executed system hotkey" in res
    mock_hotkey.assert_called_once_with("ctrl", "c")


def test_send_system_hotkey_dangerous():
    guardrails.set_auth_callback(lambda reason, action: False)
    try:
        res = send_system_hotkey(["alt", "f4"])
        assert "Safety authorization denied" in res
    finally:
        guardrails.set_auth_callback(None)


def test_send_system_hotkey_empty():
    res = send_system_hotkey([])
    assert "Error:" in res


def test_analyze_screen_missing_image():
    res = analyze_screen_with_vision("Find button", image_path="non_existent_screen_xyz.png")
    assert "does not exist" in res


@patch("tools.gui_tools.genai.Client")
def test_analyze_screen_with_vision_mocked(mock_genai_client_cls):
    with tempfile.TemporaryDirectory() as tmpdir:
        test_img = os.path.join(tmpdir, "screen.png")
        with open(test_img, "wb") as f:
            f.write(b"dummy_png_bytes")

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "Detected Submit button at (960, 540)."
        mock_client.models.generate_content.return_value = mock_resp
        mock_genai_client_cls.return_value = mock_client

        with patch("tools.gui_tools.config.gemini_api_key", "mock_key"):
            ans = analyze_screen_with_vision("Locate the Submit button", image_path=test_img)
            assert "Detected Submit button at (960, 540)." in ans
            mock_client.models.generate_content.assert_called_once()
