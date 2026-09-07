"""
Safety and confirmation layer (guardrails) for JARVIS.
Enforces human-in-the-loop authorization before executing destructive commands.
"""

import os
import re
from typing import Callable, Optional
from config import config

# Type for authorization callback: (reason: str, command_or_action: str) -> bool
AuthCallback = Callable[[str, str], bool]

SYSTEM_PATHS = [
    r"c:\windows",
    r"c:\program files",
    r"c:\program files (x86)",
    "/bin",
    "/sbin",
    "/usr/bin",
    "/usr/sbin",
    "/etc",
    "/var",
]


class SafetyGuard:
    """Manages command inspection and human-in-the-loop authorization."""

    def __init__(self, auth_callback: Optional[AuthCallback] = None):
        """
        Initialize SafetyGuard.
        :param auth_callback: Optional custom callback for authorization.
                              If None, interactive terminal input is used.
        """
        self._auth_callback = auth_callback

    def set_auth_callback(self, callback: Optional[AuthCallback]) -> None:
        """Set or remove custom authorization callback (useful for testing)."""
        self._auth_callback = callback

    def is_destructive_command(self, command: str) -> tuple[bool, str]:
        """
        Analyze whether a terminal command appears destructive.
        Returns (is_destructive, reason).
        """
        cmd_lower = command.strip().lower()

        # Check against destructive keywords from config
        for kw in config.destructive_keywords:
            if kw in cmd_lower:
                return True, f"Command contains potentially destructive keyword: '{kw.strip()}'"

        # Check regex patterns
        patterns = [
            (r"\brm\s+(-[rfRF]+\s+)?[\w\.\*\/]+", "File/Directory removal command detected"),
            (r"\bdel\s+(/[fFqQsSaA]+\s+)?[\w\.\*\\\/]+", "Windows file deletion command detected"),
            (r"\b(format|diskpart|fdisk)\b", "Disk formatting/partitioning command detected"),
            (r"\b(shutdown|reboot|init\s+0)\b", "System shutdown or reboot command detected"),
            (r">\s*(\/|[a-zA-Z]:\\)", "Direct output redirection to root or system path"),
        ]
        for pattern, reason in patterns:
            if re.search(pattern, cmd_lower):
                return True, reason

        return False, ""

    def is_sensitive_path(self, filepath: str) -> tuple[bool, str]:
        """
        Check if a file path points to a sensitive operating system directory.
        """
        norm_path = os.path.abspath(filepath).lower()
        for sys_path in SYSTEM_PATHS:
            if norm_path.startswith(sys_path.lower()):
                return True, f"Target path '{filepath}' is within sensitive system directory '{sys_path}'"
        return False, ""

    def authorize_action(self, reason: str, action_details: str) -> bool:
        """
        Prompt user for confirmation or execute custom authorization callback.
        """
        if self._auth_callback is not None:
            return self._auth_callback(reason, action_details)

        print("\n" + "=" * 60)
        print(" [!] SAFETY GUARD TRIGGERED")
        print(f" Reason: {reason}")
        print(f" Action: {action_details}")
        print("=" * 60)

        try:
            user_input = input("Authorize? [y/N]: ").strip().lower()
            return user_input in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    def guard_terminal_command(self, command: str) -> None:
        """
        Check terminal command and request human authorization if destructive.
        Raises PermissionError if denied.
        """
        is_dest, reason = self.is_destructive_command(command)
        if is_dest:
            authorized = self.authorize_action(reason, command)
            if not authorized:
                raise PermissionError(f"Action denied by user authorization: {reason}")

    def guard_file_write(self, filepath: str, mode: str = "w") -> None:
        """
        Check file write and request human authorization if overwriting or targeting system paths.
        Raises PermissionError if denied.
        """
        is_sensitive, reason = self.is_sensitive_path(filepath)
        if is_sensitive:
            authorized = self.authorize_action(reason, f"Write to {filepath} (mode={mode})")
            if not authorized:
                raise PermissionError(f"Action denied by user authorization: {reason}")

        # If overwriting an existing file in 'w' mode, trigger confirmation
        if "w" in mode and os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            reason = f"Existing file '{filepath}' will be overwritten and truncated."
            authorized = self.authorize_action(reason, f"Overwrite {filepath}")
            if not authorized:
                raise PermissionError(f"Action denied by user authorization: {reason}")


# Global guardrail instance
guardrails = SafetyGuard()
