"""
Dynamic system prompt assembly.

In Claude Code, the system prompt is NOT static — it is dynamically assembled
from multiple sources every conversation. This is one of the biggest reasons
Claude Code works better than a naive "you are a helpful assistant" prompt.

Key insight from Claude Code's context.ts and QueryEngine.ts:
  - Environment info (OS, shell, cwd) is injected fresh each session
  - Git state (branch, status, recent commits) gives the model project awareness
  - Project memory (CLAUDE.md / AGENT.md) persists knowledge across sessions
  - Tool descriptions are part of the context, filtered by permissions
  - User context and system context are separate injection points
"""

import os
import subprocess
import platform
from datetime import datetime


def _run(cmd: list[str], default: str = "") -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5, cwd=os.getcwd())
        return r.stdout.strip() if r.returncode == 0 else default
    except Exception:
        return default


def get_git_context() -> str:
    """Mirrors Claude Code's getGitStatus() in context.ts"""
    is_git = _run(["git", "rev-parse", "--is-inside-work-tree"]) == "true"
    if not is_git:
        return ""

    branch = _run(["git", "branch", "--show-current"])
    default_branch = _run(["git", "config", "init.defaultBranch"], "main")
    status = _run(["git", "status", "--short"])
    log = _run(["git", "--no-pager", "log", "--oneline", "-n", "5"])

    parts = [f"Current branch: {branch}"]
    if default_branch:
        parts.append(f"Main branch: {default_branch}")
    parts.append(f"Status:\n{status or '(clean)'}")
    if log:
        parts.append(f"Recent commits:\n{log}")

    return "\n".join(parts)


def get_project_memory() -> str:
    """
    Load project-level memory files.

    In Claude Code, CLAUDE.md files are loaded from:
      1. ~/.claude/CLAUDE.md          (user-level)
      2. <project-root>/CLAUDE.md     (project-level)
      3. <cwd>/CLAUDE.md              (directory-level)

    We support AGENT.md as the open-source equivalent.
    """
    memory_files = ["AGENT.md", "CLAUDE.md"]
    memory_parts = []

    for name in memory_files:
        # Check cwd
        path = os.path.join(os.getcwd(), name)
        if os.path.isfile(path):
            try:
                with open(path, "r") as f:
                    content = f.read(4000)  # Budget: ~1k tokens
                memory_parts.append(f"# Project instructions ({name}):\n{content}")
            except Exception:
                pass

        # Check home directory
        home_path = os.path.join(os.path.expanduser("~"), ".agent", name)
        if os.path.isfile(home_path):
            try:
                with open(home_path, "r") as f:
                    content = f.read(2000)
                memory_parts.append(f"# User instructions ({name}):\n{content}")
            except Exception:
                pass

    return "\n\n".join(memory_parts)


def build_system_prompt(tools_description: str = "") -> str:
    """
    Assemble the full system prompt from multiple sources.

    This mirrors Claude Code's architecture where fetchSystemPromptParts()
    in QueryEngine.ts combines:
      - defaultSystemPrompt (role + behavior rules)
      - userContext (environment, git, etc.)
      - systemContext (tool instructions, memory)
    """
    cwd = os.getcwd()
    git_context = get_git_context()
    project_memory = get_project_memory()

    # ── Role definition ──
    role = """You are an expert software engineer working as an interactive CLI assistant.
You help users with coding tasks by reading, writing, and editing files, running commands,
and searching codebases. You have direct access to the user's filesystem and shell."""

    # ── Behavior rules (distilled from Claude Code's system prompt) ──
    rules = """# Rules
- Always read a file before editing it. Never guess file contents.
- Prefer editing existing files over creating new ones.
- When a command fails, analyze the error and try a different approach instead of repeating.
- Keep responses concise. Lead with the action, not the reasoning.
- After writing code, run tests or linters if available to verify correctness.
- Do not add unnecessary comments, docstrings, or type annotations to code you didn't change.
- When searching for code, use Grep for content and Glob for filenames. Avoid shell equivalents.
- For file edits, make the smallest change necessary. Don't refactor surrounding code.
- If you're unsure about something, search the codebase first rather than guessing."""

    # ── Environment context ──
    env = f"""# Environment
- Working directory: {cwd}
- Platform: {platform.system()} {platform.machine()}
- Date: {datetime.now().strftime("%Y-%m-%d")}"""

    if git_context:
        env += f"\n\n# Git\n{git_context}"

    # ── Assembly ──
    parts = [role, rules, env]

    if project_memory:
        parts.append(project_memory)

    if tools_description:
        parts.append(tools_description)

    return "\n\n".join(parts)
