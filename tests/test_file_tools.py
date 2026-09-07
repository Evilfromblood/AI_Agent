"""
Unit tests for file and system tools, and safety guardrails.
"""

import os
import tempfile
import pytest
from tools.file_tools import (
    list_directory,
    read_file,
    write_file,
    search_files,
    run_terminal_command,
)
from tools.guardrails import guardrails


@pytest.fixture
def temp_workspace():
    """Create a temporary directory for safe file operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create some dummy files
        f1 = os.path.join(tmpdir, "test1.txt")
        with open(f1, "w", encoding="utf-8") as f:
            f.write("Hello World 1")

        f2 = os.path.join(tmpdir, "test2.py")
        with open(f2, "w", encoding="utf-8") as f:
            f.write("print('Hello Python')")

        os.makedirs(os.path.join(tmpdir, "subdir"))
        f3 = os.path.join(tmpdir, "subdir", "subfile.txt")
        with open(f3, "w", encoding="utf-8") as f:
            f.write("Nested content")

        yield tmpdir


def test_list_directory(temp_workspace):
    entries = list_directory(temp_workspace)
    assert any("[FILE] test1.txt" in e for e in entries)
    assert any("[FILE] test2.py" in e for e in entries)
    assert any("[DIR]  subdir" in e for e in entries)


def test_read_file(temp_workspace):
    target = os.path.join(temp_workspace, "test1.txt")
    content = read_file(target)
    assert content == "Hello World 1"

    # Truncation check
    truncated = read_file(target, max_chars=5)
    assert truncated.startswith("Hello")
    assert "Truncated" in truncated

    # Non-existent file
    error_msg = read_file(os.path.join(temp_workspace, "missing.txt"))
    assert "not found" in error_msg.lower()


def test_write_file_new_and_append(temp_workspace):
    new_file = os.path.join(temp_workspace, "new.txt")
    res1 = write_file(new_file, "Line 1\n", mode="w")
    assert "Successfully written" in res1
    assert os.path.exists(new_file)

    res2 = write_file(new_file, "Line 2\n", mode="a")
    assert "Successfully appended" in res2

    with open(new_file, "r", encoding="utf-8") as f:
        full = f.read()
    assert full == "Line 1\nLine 2\n"


def test_search_files(temp_workspace):
    txt_files = search_files(temp_workspace, "*.txt")
    assert any("test1.txt" in f for f in txt_files)
    assert any("subfile.txt" in f for f in txt_files)

    py_files = search_files(temp_workspace, "*.py")
    assert any("test2.py" in f for f in py_files)
    assert not any("test1.txt" in f for f in py_files)


def test_run_terminal_command_safe():
    output = run_terminal_command("python -c \"print('JARVIS_TEST_OUTPUT')\"")
    assert "Exit Code: 0" in output
    assert "JARVIS_TEST_OUTPUT" in output


def test_guardrails_destructive_detection():
    is_dest, reason = guardrails.is_destructive_command("rm -rf /")
    assert is_dest
    assert "removal" in reason.lower() or "destructive" in reason.lower()

    is_dest, reason = guardrails.is_destructive_command("del /f /q C:\\something")
    assert is_dest

    is_dest, reason = guardrails.is_destructive_command("format C:")
    assert is_dest

    is_dest, reason = guardrails.is_destructive_command("echo Hello")
    assert not is_dest


def test_guardrails_authorization_denied(temp_workspace):
    # Set callback that always denies
    guardrails.set_auth_callback(lambda reason, action: False)

    try:
        # Destructive command should be blocked
        out = run_terminal_command("rm -rf /tmp/fake")
        assert "Safety authorization denied" in out

        # Overwrite of non-empty existing file should be blocked
        existing = os.path.join(temp_workspace, "test1.txt")
        write_res = write_file(existing, "Overwritten", mode="w")
        assert "Safety authorization denied" in write_res
    finally:
        # Reset callback
        guardrails.set_auth_callback(None)


def test_guardrails_authorization_approved(temp_workspace):
    # Set callback that approves
    guardrails.set_auth_callback(lambda reason, action: True)

    try:
        existing = os.path.join(temp_workspace, "test1.txt")
        write_res = write_file(existing, "Authorized overwrite", mode="w")
        assert "Successfully written" in write_res
        assert read_file(existing) == "Authorized overwrite"
    finally:
        guardrails.set_auth_callback(None)
