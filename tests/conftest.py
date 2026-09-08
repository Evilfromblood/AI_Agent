"""
Global pytest configuration for JARVIS Assistant test suite.
Ensures headless offscreen mode and pre-initializes Qt runtime before WinRT.
"""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

try:
    import PySide6.QtCore
except Exception:
    pass
