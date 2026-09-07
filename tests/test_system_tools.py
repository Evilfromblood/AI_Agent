"""
Unit tests for system telemetry and application control tools.
"""

from unittest.mock import MagicMock, patch
from tools.system_tools import get_system_stats, launch_application


def test_get_system_stats_structure():
    stats = get_system_stats()
    assert isinstance(stats, dict)
    assert stats["status"] == "online"

    # CPU checks
    assert "cpu" in stats
    assert "usage_percent" in stats["cpu"]
    assert isinstance(stats["cpu"]["cores"], int)

    # Memory checks
    assert "memory" in stats
    assert "total_gb" in stats["memory"]
    assert "used_gb" in stats["memory"]
    assert "percent" in stats["memory"]

    # Disk checks
    assert "disk" in stats
    assert "total_gb" in stats["disk"]
    assert "free_gb" in stats["disk"]

    # Process count
    assert "active_processes" in stats
    assert stats["active_processes"] > 0


@patch("tools.system_tools.subprocess.Popen")
@patch("tools.system_tools.shutil.which", return_value="/usr/bin/notepad")
def test_launch_application_approved(mock_which, mock_popen):
    mock_process = MagicMock()
    mock_popen.return_value = mock_process

    result = launch_application("notepad")
    assert "Successfully launched" in result
    mock_popen.assert_called_once()


def test_launch_application_disallowed():
    result = launch_application("malicious_unapproved_script.exe")
    assert "Error:" in result
    assert "not in the approved whitelist" in result
