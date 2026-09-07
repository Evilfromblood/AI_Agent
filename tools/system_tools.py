"""
System telemetry and desktop application control tools for JARVIS.
Provides real-time hardware statistics (CPU, RAM, Disk) and safe application launching.
"""

import os
import shutil
import subprocess
from typing import Any, Dict
import psutil

from tools.registry import registry

# Whitelist of approved applications mapped to executable commands
APPROVED_APPLICATIONS: Dict[str, str] = {
    "notepad": "notepad.exe" if os.name == "nt" else "gedit",
    "calc": "calc.exe" if os.name == "nt" else "gnome-calculator",
    "calculator": "calc.exe" if os.name == "nt" else "gnome-calculator",
    "taskmgr": "taskmgr.exe" if os.name == "nt" else "top",
    "explorer": "explorer.exe" if os.name == "nt" else "xdg-open .",
    "code": "code",
    "cmd": "cmd.exe" if os.name == "nt" else "bash",
    "powershell": "powershell.exe" if os.name == "nt" else "pwsh",
}


@registry.register
def get_system_stats() -> Dict[str, Any]:
    """
    Retrieve real-time hardware telemetry including CPU utilization, RAM usage, and available disk space.
    :return: Dictionary of system performance metrics
    """
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count(logical=True)

        mem = psutil.virtual_memory()
        ram_info = {
            "total_gb": round(mem.total / (1024 ** 3), 2),
            "used_gb": round(mem.used / (1024 ** 3), 2),
            "available_gb": round(mem.available / (1024 ** 3), 2),
            "percent": mem.percent,
        }

        # Root drive disk stats
        root_path = os.path.splitdrive(os.path.abspath("."))[0] + "\\" if os.name == "nt" else "/"
        disk = psutil.disk_usage(root_path)
        disk_info = {
            "drive": root_path,
            "total_gb": round(disk.total / (1024 ** 3), 2),
            "used_gb": round(disk.used / (1024 ** 3), 2),
            "free_gb": round(disk.free / (1024 ** 3), 2),
            "percent": disk.percent,
        }

        process_count = len(psutil.pids())

        return {
            "status": "online",
            "cpu": {
                "usage_percent": cpu_percent,
                "cores": cpu_count,
            },
            "memory": ram_info,
            "disk": disk_info,
            "active_processes": process_count,
        }
    except Exception as e:
        return {"error": f"Failed to retrieve system stats: {str(e)}"}


@registry.register
def launch_application(app_name: str) -> str:
    """
    Safely launch an approved desktop application (e.g. notepad, calc, taskmgr, explorer, code).
    :param app_name: Name or alias of the application to open
    :return: Status message confirming process launch
    """
    clean_name = app_name.strip().lower()

    if clean_name not in APPROVED_APPLICATIONS:
        approved_list = ", ".join(sorted(APPROVED_APPLICATIONS.keys()))
        return (
            f"Error: Application '{app_name}' is not in the approved whitelist. "
            f"Approved applications: {approved_list}"
        )

    executable = APPROVED_APPLICATIONS[clean_name]

    # Verify command or executable exists
    exe_binary = executable.split()[0]
    if shutil.which(exe_binary) is None and not os.path.exists(exe_binary):
        # On Windows, check standard system directory for common binaries
        win_dir = os.environ.get("WINDIR", r"C:\Windows")
        sys32_path = os.path.join(win_dir, "System32", exe_binary)
        if not os.path.exists(sys32_path):
            return f"Error: Executable for '{app_name}' ('{executable}') was not found on this system PATH."

    try:
        # Launch non-blocking background process
        subprocess.Popen(executable, shell=True)
        return f"Successfully launched application '{clean_name}' (command: {executable})."
    except Exception as e:
        return f"Error launching application '{app_name}': {type(e).__name__} - {str(e)}"
