"""
Background System Tray Manager and Global Hotkey Daemon for JARVIS.
Integrates pystray for Windows taskbar tray persistence and keyboard for
system-wide Alt+Space hotkey registration.
"""

import threading
from typing import TYPE_CHECKING, Optional

from PIL import Image, ImageDraw
import pystray

if TYPE_CHECKING:
    from ui.app_controller import AppController

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False


class TrayManager:
    """
    Manages the Windows notification system tray icon, context menu,
    and global hotkey listener.
    """

    def __init__(self, controller: "AppController", hotkey: str = "alt+space"):
        self.controller = controller
        self.hotkey = hotkey
        self._icon: Optional[pystray.Icon] = None
        self._tray_thread: Optional[threading.Thread] = None
        self._hotkey_hooked = False

    @staticmethod
    def create_arc_reactor_icon(size: int = 64) -> Image.Image:
        """
        Synthesize a crisp, glowing JARVIS Arc-Reactor icon for the system tray
        using Pillow drawing primitives.
        """
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        # Outer glowing halo
        draw.ellipse([2, 2, size - 3, size - 3], outline=(0, 229, 255, 180), width=3)

        # Intermediate dark ring
        draw.ellipse([10, 10, size - 11, size - 11], outline=(14, 116, 144, 255), width=2)

        # Inner vibrant core
        draw.ellipse([18, 18, size - 19, size - 19], fill=(6, 182, 212, 220), outline=(255, 255, 255, 255), width=2)

        # Center bright energy node
        draw.ellipse([26, 26, size - 27, size - 27], fill=(255, 255, 255, 255))

        return image

    def start(self) -> None:
        """Start the background system tray icon and register global hotkeys."""
        self._setup_tray_icon()
        self._register_hotkey()

    def _setup_tray_icon(self) -> None:
        """Instantiate pystray.Icon and run in a daemon thread."""
        icon_image = self.create_arc_reactor_icon(64)

        menu = pystray.Menu(
            pystray.MenuItem("Toggle HUD (Alt+Space)", lambda: self.controller.toggle_hud(), default=True),
            pystray.MenuItem("Voice Query", lambda: self.controller.trigger_voice()),
            pystray.MenuItem("System Stats", lambda: self.controller.trigger_system_stats()),
            pystray.MenuItem("Clear History", lambda: self.controller.clear_output()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit JARVIS", lambda: self.controller.shutdown()),
        )

        self._icon = pystray.Icon(
            name="JARVIS-Hub",
            icon=icon_image,
            title="JARVIS Desktop Assistant",
            menu=menu,
        )

        # Run pystray in a dedicated background daemon thread
        self._tray_thread = threading.Thread(
            target=self._icon.run,
            daemon=True,
            name="JARVIS-Tray-Thread",
        )
        self._tray_thread.start()

    def _register_hotkey(self) -> None:
        """Register the system-wide global hotkey hook."""
        if not HAS_KEYBOARD:
            return

        try:
            keyboard.add_hotkey(self.hotkey, self.controller.toggle_hud)
            self._hotkey_hooked = True
        except Exception:
            # Catch permissions/OS restrictions gracefully
            self._hotkey_hooked = False

    def stop(self) -> None:
        """Unhook hotkeys and terminate the tray icon."""
        if HAS_KEYBOARD and self._hotkey_hooked:
            try:
                keyboard.unhook_all_hotkeys()
            except Exception:
                pass
            self._hotkey_hooked = False

        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
