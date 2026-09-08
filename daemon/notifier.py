"""
Native Windows Toast Notification Dispatcher for JARVIS Desktop Assistant.
Wraps windows-toasts with non-blocking delivery, interactive click activation,
and graceful fallback logging.
"""

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Pre-initialize Qt runtime if present to prevent WinRT/COM apartment conflicts on Windows
try:
    import PySide6.QtCore  # noqa: F401
except Exception:
    pass

try:
    from windows_toasts import Toast, WindowsToaster

    HAS_WINDOWS_TOASTS = True
except ImportError:
    HAS_WINDOWS_TOASTS = False



class ToastNotifier:
    """
    Manages native Windows toast notifications.
    Supports interactive click callbacks to restore or focus the HUD.
    """

    def __init__(self, app_id: str = "JARVIS Assistant"):
        self.app_id = app_id
        self.toaster: Optional["WindowsToaster"] = None
        self.default_activation_callback: Optional[Callable[[], None]] = None

        if HAS_WINDOWS_TOASTS:
            try:
                self.toaster = WindowsToaster(self.app_id)
            except Exception as e:
                logger.warning("Failed to initialize WindowsToaster: %s", e)
                self.toaster = None

    def set_default_activation_callback(self, callback: Callable[[], None]) -> None:
        """Register the default action triggered when a user clicks a toast notification."""
        self.default_activation_callback = callback

    def send_notification(
        self,
        title: str,
        body: str,
        on_activated: Optional[Callable[[], None]] = None,
    ) -> bool:
        """
        Send a non-blocking toast notification.
        :param title: Notification headline
        :param body: Notification descriptive body
        :param on_activated: Optional click callback. Falls back to default_activation_callback.
        :return: True if toast dispatched natively; False if fallback logging was used.
        """
        if self.toaster is not None and HAS_WINDOWS_TOASTS:
            try:
                toast = Toast()
                toast.text_fields = [title, body]

                cb = on_activated or self.default_activation_callback
                if cb is not None:

                    def _wrapper(_args=None):
                        try:
                            cb()
                        except Exception as ex:
                            logger.warning("Error in toast on_activated callback: %s", ex)

                    toast.on_activated = _wrapper

                self.toaster.show_toast(toast)
                return True
            except Exception as e:
                logger.warning("Native toast dispatch failed: %s", e)

        # Silent console fallback if notifications are unavailable or privileged
        print(f"\n[Notification - {title}] {body}\n")
        return False


# Module singleton instance
toast_notifier = ToastNotifier()


def send_notification(
    title: str,
    body: str,
    on_activated: Optional[Callable[[], None]] = None,
) -> bool:
    """Convenience functional interface to dispatch toast notifications."""
    return toast_notifier.send_notification(title, body, on_activated=on_activated)
