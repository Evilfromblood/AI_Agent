"""
Desktop GUI Automation, Screen Capture, and Vision Grounding tools for JARVIS.
Enforces PyAutoGUI fail-safe, bounds checking, and safety guardrails.
"""

import os
from typing import Any, Dict, List, Optional
from PIL import Image
import pyautogui

try:
    import mss
    import mss.tools
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

from config import config
from tools.guardrails import guardrails
from tools.registry import registry

# Global fail-safe: slamming cursor into any screen corner halts automation
pyautogui.FAILSAFE = True


@registry.register
def take_screenshot(filename: str = "workspace_screen.png", region: Optional[List[int]] = None) -> Dict[str, Any]:
    """
    Capture the active desktop display or a specific screen region and save to disk.
    :param filename: Output file path for PNG screenshot (e.g. 'screenshots/desktop.png')
    :param region: Optional bounding box [left, top, width, height]
    :return: Dictionary containing status, file_path, width, and height
    """
    out_path = os.path.abspath(filename)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    try:
        captured = False
        w, h = 0, 0

        if HAS_MSS:
            try:
                mss_cls = getattr(mss, "MSS", mss.mss)
                with mss_cls() as sct:
                    if region and len(region) == 4:
                        monitor = {
                            "left": int(region[0]),
                            "top": int(region[1]),
                            "width": int(region[2]),
                            "height": int(region[3]),
                        }
                    else:
                        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]

                    sct_img = sct.grab(monitor)
                    mss.tools.to_png(sct_img.rgb, sct_img.size, output=out_path)
                    w, h = sct_img.size
                    captured = True
            except Exception:
                captured = False

        if not captured:
            # Fallback to pyautogui / Pillow
            img = pyautogui.screenshot(region=region)
            img.save(out_path)
            w, h = img.size

        return {
            "status": "success",
            "file_path": out_path,
            "width": w,
            "height": h,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Failed to capture screenshot: {type(e).__name__} - {str(e)}",
        }


@registry.register
def analyze_screen_with_vision(prompt: str, image_path: str = "workspace_screen.png") -> str:
    """
    Inspect a captured screenshot using Google Gemini 2.5 Flash multimodal vision grounding.
    Returns detected UI elements, bounding coordinates, error dialog text, or active window states.
    :param prompt: Question or directive for the vision model (e.g. 'Find coordinates for the Submit button')
    :param image_path: Path to the image file to analyze
    :return: Textual analysis and grounding response from Gemini
    """
    if not os.path.exists(image_path):
        return f"Error: Screenshot file '{image_path}' does not exist. Call take_screenshot first."

    if not HAS_GENAI:
        return "Error: google-genai library is not installed."

    api_key = config.gemini_api_key
    if not api_key:
        return "Error: GEMINI_API_KEY environment variable is not set. Gemini vision requires a valid API key."

    try:
        client = genai.Client(api_key=api_key)
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/png")
        vision_prompt = (
            f"You are JARVIS Vision Grounding Agent. Examine this desktop screenshot.\n"
            f"User Query: {prompt}\n\n"
            f"Provide precise, actionable observations. If asked for UI locations, "
            f"estimate the approximate (x, y) center pixel coordinates."
        )

        response = client.models.generate_content(
            model=config.gemini_model,
            contents=[image_part, vision_prompt],
        )
        return (response.text or "").strip() or "[Gemini Vision returned an empty response.]"
    except Exception as e:
        return f"Error analyzing screenshot with Gemini Vision: {type(e).__name__} - {str(e)}"


@registry.register
def click_screen_coordinate(x: int, y: int, clicks: int = 1, button: str = "left") -> str:
    """
    Click mouse at specific screen coordinates (x, y) with boundary verification.
    :param x: Horizontal pixel position
    :param y: Vertical pixel position
    :param clicks: Number of clicks (default: 1, use 2 for double click)
    :param button: Mouse button ('left', 'right', 'middle')
    :return: Status confirmation message
    """
    try:
        screen_w, screen_h = pyautogui.size()
        if x < 0 or x >= screen_w or y < 0 or y >= screen_h:
            return (
                f"Error: Coordinate ({x}, {y}) is out of screen bounds "
                f"(Screen resolution is {screen_w}x{screen_h})."
            )

        pyautogui.click(x=x, y=y, clicks=clicks, button=button)
        return f"Successfully clicked at ({x}, {y}) with button='{button}' (clicks={clicks})."
    except Exception as e:
        return f"Error clicking screen coordinate ({x}, {y}): {type(e).__name__} - {str(e)}"


@registry.register
def type_screen_text(text: str, press_enter: bool = False, interval: float = 0.05) -> str:
    """
    Simulate keyboard typing into the currently focused desktop window with safety guardrails.
    :param text: Text string to type
    :param press_enter: Whether to press Enter after typing (default: False)
    :param interval: Seconds between keystrokes (default: 0.05)
    :return: Confirmation status
    """
    try:
        guardrails.guard_screen_type(text)

        pyautogui.write(text, interval=interval)
        if press_enter:
            pyautogui.press("enter")

        return f"Successfully typed text into active window ({len(text)} characters, press_enter={press_enter})."
    except PermissionError as pe:
        return f"Safety authorization denied: {str(pe)}"
    except Exception as e:
        return f"Error typing screen text: {type(e).__name__} - {str(e)}"


@registry.register
def send_system_hotkey(keys: List[str]) -> str:
    """
    Inject an OS-level keyboard shortcut (e.g. ['ctrl', 's'], ['alt', 'tab'], ['win', 'r']).
    Gated by guardrails to prevent unauthorized destruction or locking.
    :param keys: List of keys to press simultaneously (e.g. ['ctrl', 'c'])
    :return: Status confirmation message
    """
    if not keys:
        return "Error: No keys specified for hotkey combination."

    clean_keys = [str(k).strip().lower() for k in keys]

    try:
        guardrails.guard_hotkey(clean_keys)

        pyautogui.hotkey(*clean_keys)
        return f"Successfully executed system hotkey: {' + '.join(clean_keys)}."
    except PermissionError as pe:
        return f"Safety authorization denied: {str(pe)}"
    except Exception as e:
        return f"Error sending system hotkey: {type(e).__name__} - {str(e)}"
