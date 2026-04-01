"""
Tool definitions and executors.

Design borrowed from Claude Code's Tool.ts:
  - Each tool has a name, description, JSON schema, and execute function.
  - Tools declare whether they are read-only (safe for concurrent execution).
  - Errors are returned as strings, not raised — this lets the model self-correct.
  - Output is truncated to a budget so one huge result doesn't blow the context.
"""

import os
import re
import subprocess
import json
import difflib
from dataclasses import dataclass, field
from typing import Callable, Any

MAX_OUTPUT_CHARS = 12_000  # Claude Code uses maxResultSizeChars per tool


@dataclass
class ToolDef:
    """Mirrors Claude Code's Tool<Input, Output> interface."""
    name: str
    description: str
    parameters: dict
    execute: Callable[[dict], str]
    read_only: bool = True  # isConcurrencySafe in Claude Code


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n... (truncated — {len(text)} chars total, showing first {limit})"


# ── Bash ──────────────────────────────────────────────────────────────────────

def _run_bash(args: dict) -> str:
    command = args["command"]
    timeout = min(args.get("timeout", 120), 300)

    # Safety: refuse obviously dangerous commands
    dangerous = ["rm -rf /", "mkfs", ":(){:|:&};:", "dd if=/dev/zero"]
    for d in dangerous:
        if d in command:
            return f"Error: refusing to run dangerous command: {command}"

    try:
        r = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd(),
            env={**os.environ, "TERM": "dumb"},
        )
        output = ""
        if r.stdout:
            output += r.stdout
        if r.stderr:
            output += ("\n" if output else "") + r.stderr
        if r.returncode != 0:
            output += f"\n(exit code {r.returncode})"
        return _truncate(output) or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


BashTool = ToolDef(
    name="Bash",
    description="Execute a shell command. Use for running tests, installing packages, git operations, and system commands. Prefer dedicated tools (Read, Edit, Grep, Glob) over shell equivalents (cat, sed, grep, find) when possible.",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 120, max 300)"},
        },
        "required": ["command"],
    },
    execute=_run_bash,
    read_only=False,
)


# ── Read ──────────────────────────────────────────────────────────────────────

def _read_file(args: dict) -> str:
    path = args["path"]
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)

    if not os.path.exists(path):
        return f"Error: file not found: {path}"
    if os.path.isdir(path):
        return f"Error: {path} is a directory, not a file. Use Bash('ls {path}') to list contents."

    try:
        with open(path, "r", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return f"Error reading {path}: {e}"

    offset = args.get("offset", 0)
    limit = args.get("limit", 2000)
    selected = lines[offset : offset + limit]

    if not selected:
        return "(empty file)" if not lines else f"(no lines in range {offset}–{offset + limit}, file has {len(lines)} lines)"

    numbered = [f"{i + offset + 1}\t{line}" for i, line in enumerate(selected)]
    result = "".join(numbered)

    if offset + limit < len(lines):
        result += f"\n... ({len(lines) - offset - limit} more lines)"

    return _truncate(result)


ReadTool = ToolDef(
    name="Read",
    description="Read a file's contents with line numbers. Use offset and limit for large files.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path"},
            "offset": {"type": "integer", "description": "Start line (0-based, default 0)"},
            "limit": {"type": "integer", "description": "Max lines to read (default 2000)"},
        },
        "required": ["path"],
    },
    execute=_read_file,
    read_only=True,
)


# ── Edit ──────────────────────────────────────────────────────────────────────

def _edit_file(args: dict) -> str:
    path = args["file_path"]
    old = args["old_string"]
    new = args["new_string"]

    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)

    if not os.path.exists(path):
        return f"Error: file not found: {path}"

    try:
        with open(path, "r") as f:
            content = f.read()
    except Exception as e:
        return f"Error reading {path}: {e}"

    if old == new:
        return "Error: old_string and new_string are identical"

    count = content.count(old)
    if count == 0:
        # Provide helpful context for debugging
        lines = content.split("\n")
        first_word = old.split()[0] if old.split() else old[:20]
        matches = [f"  L{i+1}: {l.strip()}" for i, l in enumerate(lines) if first_word in l]
        hint = "\nLines containing '{}':".format(first_word) + "\n".join(matches[:5]) if matches else ""
        return f"Error: old_string not found in {path}.{hint}"
    if count > 1 and not args.get("replace_all"):
        return f"Error: old_string appears {count} times in {path}. Provide more context to make it unique, or set replace_all=true."

    new_content = content.replace(old, new) if args.get("replace_all") else content.replace(old, new, 1)

    try:
        with open(path, "w") as f:
            f.write(new_content)
    except Exception as e:
        return f"Error writing {path}: {e}"

    # Show a diff snippet
    old_lines = content.split("\n")
    new_lines = new_content.split("\n")
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=2))
    diff_str = "\n".join(diff[:30])

    replaced = count if args.get("replace_all") else 1
    return f"Edited {path} ({replaced} replacement{'s' if replaced > 1 else ''})\n{diff_str}"


EditTool = ToolDef(
    name="Edit",
    description="Make exact string replacements in a file. You MUST read the file first before editing. The old_string must match exactly (including whitespace/indentation).",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "The file to edit"},
            "old_string": {"type": "string", "description": "The exact text to replace"},
            "new_string": {"type": "string", "description": "The replacement text"},
            "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false)"},
        },
        "required": ["file_path", "old_string", "new_string"],
    },
    execute=_edit_file,
    read_only=False,
)


# ── Write ─────────────────────────────────────────────────────────────────────

def _write_file(args: dict) -> str:
    path = args["file_path"]
    content = args["content"]

    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)

    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        return f"Wrote {len(content)} chars ({lines} lines) to {path}"
    except Exception as e:
        return f"Error writing {path}: {e}"


WriteTool = ToolDef(
    name="Write",
    description="Create a new file or completely overwrite an existing file. For partial modifications, prefer the Edit tool.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Path to create/overwrite"},
            "content": {"type": "string", "description": "The full file content to write"},
        },
        "required": ["file_path", "content"],
    },
    execute=_write_file,
    read_only=False,
)


# ── Glob ──────────────────────────────────────────────────────────────────────

def _glob_search(args: dict) -> str:
    import glob as g
    pattern = args["pattern"]
    path = args.get("path", os.getcwd())

    try:
        matches = sorted(g.glob(os.path.join(path, pattern), recursive=True))
        if not matches:
            return f"No files matching '{pattern}' in {path}"
        # Show relative paths
        rel = [os.path.relpath(m, os.getcwd()) for m in matches[:200]]
        result = "\n".join(rel)
        if len(matches) > 200:
            result += f"\n... ({len(matches) - 200} more files)"
        return result
    except Exception as e:
        return f"Error: {e}"


GlobTool = ToolDef(
    name="Glob",
    description="Find files by glob pattern (e.g., '**/*.py', 'src/**/*.ts'). Returns matching file paths.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern (supports ** for recursive)"},
            "path": {"type": "string", "description": "Directory to search in (default: cwd)"},
        },
        "required": ["pattern"],
    },
    execute=_glob_search,
    read_only=True,
)


# ── Grep ──────────────────────────────────────────────────────────────────────

def _grep_search(args: dict) -> str:
    pattern = args["pattern"]
    path = args.get("path", os.getcwd())
    include = args.get("include", "")

    cmd = ["grep", "-rn", "--color=never", "-E", pattern]
    if include:
        cmd.extend(["--include", include])
    cmd.append(path)

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        output = r.stdout
        if not output:
            return f"No matches for pattern '{pattern}'"
        # Make paths relative
        cwd = os.getcwd()
        lines = output.split("\n")
        rel_lines = []
        for line in lines[:100]:
            if line.startswith(cwd):
                line = line[len(cwd)+1:]
            rel_lines.append(line)
        result = "\n".join(rel_lines)
        if len(lines) > 100:
            result += f"\n... ({len(lines) - 100} more matches)"
        return _truncate(result)
    except subprocess.TimeoutExpired:
        return "Error: grep timed out"
    except Exception as e:
        return f"Error: {e}"


GrepTool = ToolDef(
    name="Grep",
    description="Search file contents for a regex pattern. Returns matching lines with file paths and line numbers.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "path": {"type": "string", "description": "Directory or file to search (default: cwd)"},
            "include": {"type": "string", "description": "File glob filter (e.g., '*.py')"},
        },
        "required": ["pattern"],
    },
    execute=_grep_search,
    read_only=True,
)


# ── Registry ──────────────────────────────────────────────────────────────────

ALL_TOOLS: list[ToolDef] = [BashTool, ReadTool, EditTool, WriteTool, GlobTool, GrepTool]


def get_openai_tools() -> list[dict]:
    """Convert our tools to OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in ALL_TOOLS
    ]


def find_tool(name: str) -> ToolDef | None:
    for t in ALL_TOOLS:
        if t.name == name:
            return t
    return None
