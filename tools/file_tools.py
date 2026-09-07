"""
System and file operations toolset for JARVIS.
Includes directory listing, file read/write, pattern search, and guarded terminal execution.
"""

import fnmatch
import os
import subprocess
from typing import List
from config import config
from tools.guardrails import guardrails
from tools.registry import registry


@registry.register
def list_directory(path: str = ".") -> List[str]:
    """
    List contents of a directory with file/dir indicators and relative names.
    :param path: Directory path to inspect (defaults to current working directory)
    :return: List of directory entries with '[DIR]' or '[FILE]' tags
    """
    try:
        if not os.path.exists(path):
            return [f"Error: Directory '{path}' does not exist."]
        if not os.path.isdir(path):
            return [f"Error: Path '{path}' is not a directory."]

        entries = os.listdir(path)
        formatted = []
        for entry in sorted(entries):
            full_path = os.path.join(path, entry)
            if os.path.isdir(full_path):
                formatted.append(f"[DIR]  {entry}")
            else:
                size_kb = os.path.getsize(full_path) / 1024
                formatted.append(f"[FILE] {entry} ({size_kb:.1f} KB)")
        return formatted
    except Exception as e:
        return [f"Error listing directory '{path}': {str(e)}"]


@registry.register
def read_file(filepath: str, max_chars: int = 5000) -> str:
    """
    Read text content from a file up to max_chars characters.
    :param filepath: Path to the file to read
    :param max_chars: Maximum number of characters to return (default: 5000)
    :return: File content or error message
    """
    try:
        if not os.path.exists(filepath):
            return f"Error: File '{filepath}' not found."
        if not os.path.isfile(filepath):
            return f"Error: Path '{filepath}' is not a file."

        # Read with UTF-8 and fallback replacement
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars + 1)

        if len(content) > max_chars:
            return content[:max_chars] + f"\n\n[... Truncated: File exceeded {max_chars} characters ...]"
        return content
    except Exception as e:
        return f"Error reading file '{filepath}': {str(e)}"


@registry.register
def write_file(filepath: str, content: str, mode: str = "w") -> str:
    """
    Write or append text content to a file with safety guardrail verification.
    :param filepath: Target file path
    :param content: Text content to write
    :param mode: File open mode ('w' for write/overwrite, 'a' for append)
    :return: Confirmation message or error
    """
    if mode not in ("w", "a"):
        return f"Error: Unsupported file mode '{mode}'. Use 'w' (overwrite) or 'a' (append)."

    try:
        # Check guardrails before writing
        guardrails.guard_file_write(filepath, mode=mode)

        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, mode, encoding="utf-8") as f:
            f.write(content)

        action = "appended to" if mode == "a" else "written to"
        return f"Successfully {action} '{filepath}' ({len(content)} characters)."
    except PermissionError as pe:
        return f"Safety authorization denied: {str(pe)}"
    except Exception as e:
        return f"Error writing to file '{filepath}': {str(e)}"


@registry.register
def search_files(base_dir: str, pattern: str) -> List[str]:
    """
    Search recursively for files matching a glob pattern (e.g. '*.py', '*test*').
    :param base_dir: Root directory from which to search
    :param pattern: Glob pattern to match against filenames
    :return: List of relative paths to matching files
    """
    if not os.path.exists(base_dir):
        return [f"Error: Base directory '{base_dir}' does not exist."]

    matches = []
    try:
        for root, _, filenames in os.walk(base_dir):
            for filename in fnmatch.filter(filenames, pattern):
                rel_path = os.path.relpath(os.path.join(root, filename), base_dir)
                matches.append(rel_path)
                if len(matches) >= 100:
                    matches.append("[... Results capped at 100 matches ...]")
                    return matches
        return matches if matches else [f"No files matching '{pattern}' found in '{base_dir}'."]
    except Exception as e:
        return [f"Error searching files in '{base_dir}': {str(e)}"]


@registry.register
def run_terminal_command(command: str) -> str:
    """
    Run terminal commands safely using subprocess.run with timeout and guardrails.
    :param command: Shell command to execute
    :return: Command standard output, standard error, and exit status
    """
    try:
        # Check safety guardrail for destructive commands
        guardrails.guard_terminal_command(command)

        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=config.command_timeout,
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        output_parts = [f"Exit Code: {proc.returncode}"]
        if stdout:
            output_parts.append(f"STDOUT:\n{stdout}")
        if stderr:
            output_parts.append(f"STDERR:\n{stderr}")
        if not stdout and not stderr:
            output_parts.append("(No output produced)")

        return "\n".join(output_parts)
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {config.command_timeout} seconds."
    except PermissionError as pe:
        return f"Safety authorization denied: {str(pe)}"
    except Exception as e:
        return f"Error executing command: {type(e).__name__} - {str(e)}"
