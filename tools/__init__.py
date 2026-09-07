"""
Tools package for JARVIS desktop assistant.
Importing this package automatically registers all file, scraper, and browser tools.
"""

from tools.guardrails import SafetyGuard, guardrails
from tools.registry import ToolRegistry, registry
import tools.file_tools
import tools.scraper_tools
import tools.browser_tools
import tools.system_tools

__all__ = [
    "SafetyGuard",
    "guardrails",
    "ToolRegistry",
    "registry",
]
