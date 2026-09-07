"""
JARVIS Desktop Assistant - Phase 4 UI and System Tray Package.
Provides CustomTkinter floating HUD, background system tray hub, and asynchronous controller.
"""

from ui.floating_hud import JarvisFloatingHUD
from ui.app_controller import AppController
from ui.tray_manager import TrayManager
from ui.web_hud import WebHUD, WebHUDAPI, run_web_hud

__all__ = [
    "JarvisFloatingHUD",
    "AppController",
    "TrayManager",
    "WebHUD",
    "WebHUDAPI",
    "run_web_hud",
]

