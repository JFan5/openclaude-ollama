"""
Status bar — persistent bottom bar showing session stats.

Inspired by Claude Code's StatusLine.tsx and PromptInputFooter.tsx,
which display model name, token usage, context window, cost, and
session duration at the bottom of the terminal.
"""

import sys
import shutil


# ANSI escape codes
RESET = "\033[0m"
BG_BAR = "\033[48;5;236m"  # dark gray background
FG_WHITE = "\033[38;5;252m"
FG_GREEN = "\033[38;5;114m"
FG_YELLOW = "\033[38;5;221m"
FG_RED = "\033[38;5;203m"
FG_CYAN = "\033[38;5;117m"
FG_DIM = "\033[38;5;245m"
FG_BLUE = "\033[38;5;111m"


def _usage_color(ratio: float) -> str:
    """Color based on context window usage: green < 50% < yellow < 80% < red."""
    if ratio < 0.5:
        return FG_GREEN
    elif ratio < 0.8:
        return FG_YELLOW
    else:
        return FG_RED


def _format_tokens(n: int) -> str:
    """Format token count: 1234 → '1.2k', 56789 → '56.8k', 1000000 → '1000k'."""
    if n < 1000:
        return str(n)
    elif n < 100_000:
        return f"{n / 1000:.1f}k"
    else:
        return f"{n / 1000:.0f}k"


def _bar_chart(ratio: float, width: int = 12) -> str:
    """Render a small progress bar: [████░░░░░░░░]"""
    filled = min(int(ratio * width), width)
    empty = width - filled
    color = _usage_color(ratio)
    return f"{FG_DIM}[{color}{'█' * filled}{FG_DIM}{'░' * empty}]{RESET}"


def format_duration(seconds: float) -> str:
    """Format duration: 65 → '1m 5s', 3661 → '1h 1m'."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s}s"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"


def render_status_bar(
    model: str,
    context_tokens: int,
    total_input: int,
    total_output: int,
    context_window: int,
    turns: int,
    api_calls: int,
    duration: float,
    compact_count: int = 0,
) -> str:
    """
    Render a one-line status bar showing real API token usage.

    Example:
      minimax-m2.5:cloud │ context: 2.4k / 1000k [░░░░░░░░░░░░] 0% │ used: ↑3.1k ↓820 │ turns: 3 │ 5s
    """
    ratio = context_tokens / context_window if context_window > 0 else 0
    pct = min(int(ratio * 100), 100)
    color = _usage_color(ratio)

    # Segments
    model_seg = f"{FG_CYAN}{model}{RESET}"

    # Context usage: current prompt tokens vs context window
    ctx_seg = (
        f"context: {color}{_format_tokens(context_tokens)}{FG_DIM} / "
        f"{_format_tokens(context_window)} "
        f"{_bar_chart(ratio, width=12)} {color}{pct}%{RESET}"
    )

    # Cumulative usage: total input ↑ and output ↓
    used_seg = (
        f"used: {FG_BLUE}↑{_format_tokens(total_input)}{RESET} "
        f"{FG_GREEN}↓{_format_tokens(total_output)}{RESET}"
    )

    turns_seg = f"turns: {FG_WHITE}{turns}{RESET}"
    time_seg = f"{FG_DIM}{format_duration(duration)}{RESET}"

    segments = [model_seg, ctx_seg, used_seg, turns_seg]
    if compact_count > 0:
        segments.append(f"compacted: {FG_YELLOW}{compact_count}x{RESET}")
    segments.append(time_seg)

    bar_content = f" {FG_DIM}│{RESET} ".join(segments)
    return f"{BG_BAR} {bar_content} {RESET}"


def print_status_bar(**kwargs):
    """Print the status bar to stderr."""
    bar = render_status_bar(**kwargs)
    sys.stderr.write(f"{bar}\n")
    sys.stderr.flush()
