"""
Status bar — two-line display showing context window and token usage.

Inspired by Claude Code's StatusLine.tsx and PromptInputFooter.tsx.

Line 1: Context window — how full is the model's memory (triggers compression)
Line 2: Token usage   — cumulative input/output tokens consumed this session
"""

import sys
import shutil


# ANSI escape codes
RESET = "\033[0m"
BOLD = "\033[1m"
BG_BAR = "\033[48;5;236m"  # dark gray background
FG_WHITE = "\033[38;5;252m"
FG_GREEN = "\033[38;5;114m"
FG_YELLOW = "\033[38;5;221m"
FG_RED = "\033[38;5;203m"
FG_CYAN = "\033[38;5;117m"
FG_DIM = "\033[38;5;245m"
FG_BLUE = "\033[38;5;111m"
FG_MAGENTA = "\033[38;5;176m"


def _usage_color(ratio: float) -> str:
    if ratio < 0.5:
        return FG_GREEN
    elif ratio < 0.8:
        return FG_YELLOW
    else:
        return FG_RED


def _format_tokens(n: int) -> str:
    if n < 1000:
        return str(n)
    elif n < 100_000:
        return f"{n / 1000:.1f}k"
    else:
        return f"{n / 1000:.0f}k"


def _bar_chart(ratio: float, width: int = 20) -> str:
    filled = min(int(ratio * width), width)
    empty = width - filled
    color = _usage_color(ratio)
    return f"{FG_DIM}[{color}{'█' * filled}{FG_DIM}{'░' * empty}]{RESET}"


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s}s"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"


def print_status_bar(
    model: str,
    context_tokens: int,
    total_input: int,
    total_output: int,
    context_window: int,
    turns: int,
    api_calls: int,
    duration: float,
    compact_count: int = 0,
):
    """
    Print a two-line status bar to stderr.

    Line 1 — Context Window (how full is the model's "memory"):
      ┃ Context   1.1k / 1000k [░░░░░░░░░░░░░░░░░░░░] 0%

    Line 2 — Token Usage (cumulative cost tracking):
      ┃ Tokens    ↑input: 2.2k  ↓output: 123  │ model: minimax  │ turns: 2 │ 1s
    """
    cols = shutil.get_terminal_size().columns
    ratio = context_tokens / context_window if context_window > 0 else 0
    pct = min(int(ratio * 100), 100)
    color = _usage_color(ratio)

    # ── Line 1: Context Window ──
    bar_width = min(20, cols - 50)
    if bar_width < 5:
        bar_width = 5
    bar = _bar_chart(ratio, width=bar_width)

    compact_note = ""
    if compact_count > 0:
        compact_note = f"  {FG_YELLOW}⟳ compressed {compact_count}x{RESET}"

    line1 = (
        f"{BG_BAR} {FG_DIM}┃{RESET}{BG_BAR} "
        f"{FG_DIM}Context   "
        f"{color}{BOLD}{_format_tokens(context_tokens)}{RESET}{BG_BAR}"
        f"{FG_DIM} / {_format_tokens(context_window)}{RESET}{BG_BAR} "
        f"{bar}"
        f" {color}{pct}%{RESET}{BG_BAR}"
        f"{compact_note}"
        f" {RESET}"
    )

    # ── Line 2: Token Usage ──
    total = total_input + total_output

    line2 = (
        f"{BG_BAR} {FG_DIM}┃{RESET}{BG_BAR} "
        f"{FG_DIM}Tokens    "
        f"{FG_BLUE}↑in: {BOLD}{_format_tokens(total_input)}{RESET}{BG_BAR}  "
        f"{FG_GREEN}↓out: {BOLD}{_format_tokens(total_output)}{RESET}{BG_BAR}  "
        f"{FG_DIM}Σ {FG_WHITE}{_format_tokens(total)}{RESET}{BG_BAR}"
        f" {FG_DIM}│{RESET}{BG_BAR} "
        f"{FG_CYAN}{model}{RESET}{BG_BAR}"
        f" {FG_DIM}│{RESET}{BG_BAR} "
        f"turns: {FG_WHITE}{turns}{RESET}{BG_BAR}"
        f" {FG_DIM}│{RESET}{BG_BAR} "
        f"{FG_DIM}{format_duration(duration)}{RESET}{BG_BAR}"
        f" {RESET}"
    )

    # ── Separator ──
    sep = f"{BG_BAR}{FG_DIM} {'─' * min(60, cols - 4)} {RESET}"

    sys.stderr.write(f"{sep}\n{line1}\n{line2}\n{sep}\n")
    sys.stderr.flush()
