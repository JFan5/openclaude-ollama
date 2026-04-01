"""
The Agent Loop — the heart of an agentic AI system.

This is the core pattern extracted from Claude Code's query.ts:

    while True:
        response = LLM(messages + tools)
        if response has tool_calls:
            execute tools → append results → continue
        else:
            break (final answer)

What makes this better than a single LLM call:
  1. The model can observe → act → observe → act in a loop
  2. Errors are fed back to the model, enabling self-correction
  3. Context grows with real information (file contents, command outputs)
  4. The model decides when it has enough information to answer

Claude Code's query.ts is ~800 lines because it handles streaming, retries,
auto-compact, thinking blocks, and many edge cases. This is the ~100-line
essential version.
"""

import json
import sys
import threading
import time
import random
from openai import OpenAI
from .tools import ALL_TOOLS, get_openai_tools, find_tool
from .context import build_system_prompt
from .compact import estimate_tokens, needs_compaction, compact_messages


# ── Spinner: activity indicator while waiting for the model ──────────────────

# Verbs inspired by Claude Code's getActivityDescription() in Tool.ts
# and SpinnerMode in components/Spinner.js
THINKING_VERBS = [
    "Thinking",
    "Reasoning",
    "Analyzing",
    "Considering",
    "Planning",
    "Reflecting",
    "Evaluating",
    "Synthesizing",
]

TOOL_VERBS = {
    "Bash":  ["Running command", "Executing", "Running"],
    "Read":  ["Reading", "Examining", "Inspecting"],
    "Edit":  ["Editing", "Modifying", "Updating"],
    "Write": ["Writing", "Creating", "Generating"],
    "Grep":  ["Searching", "Scanning", "Looking for"],
    "Glob":  ["Finding files", "Discovering", "Locating"],
}

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class Spinner:
    """Animated spinner with activity verb, shown while waiting for the model."""

    def __init__(self, message: str = "Thinking"):
        self._message = message
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join()
        # Clear the spinner line
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()

    def update(self, message: str):
        self._message = message

    def _spin(self):
        i = 0
        while not self._stop.is_set():
            frame = SPINNER_FRAMES[i % len(SPINNER_FRAMES)]
            sys.stderr.write(f"\r\033[K  {frame} {self._message}...")
            sys.stderr.flush()
            i += 1
            self._stop.wait(0.08)


def agent_loop(
    client: OpenAI,
    model: str,
    user_message: str,
    context_window: int = 32_000,
    max_turns: int = 30,
    verbose: bool = True,
) -> list[dict]:
    """
    Run the agent loop for a single user request.

    Args:
        client: OpenAI-compatible API client
        model: Model name/ID
        user_message: The user's request
        context_window: Model's context window size in tokens
        max_turns: Safety limit to prevent infinite loops
        verbose: Print tool calls and results to stderr

    Returns:
        The full message history
    """
    system_prompt = build_system_prompt()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    tools = get_openai_tools()

    for turn in range(1, max_turns + 1):
        # ── Context management (from Claude Code's auto-compact) ──
        if needs_compaction(messages, context_window):
            if verbose:
                _log(f"[compact] Context too large ({estimate_tokens(messages)} tokens), summarizing...")
            messages = compact_messages(client, model, messages, context_window)
            if verbose:
                _log(f"[compact] Reduced to {estimate_tokens(messages)} tokens")

        # ── Call the model ──
        spinner = None
        if verbose:
            verb = random.choice(THINKING_VERBS)
            spinner = Spinner(verb)
            spinner.start()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
        except Exception as e:
            if spinner:
                spinner.stop()
            _log(f"[error] API call failed: {e}")
            # Retry once after a pause
            if verbose:
                spinner = Spinner("Retrying")
                spinner.start()
            time.sleep(2)
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                )
            except Exception as e2:
                if spinner:
                    spinner.stop()
                _log(f"[error] Retry failed: {e2}")
                break
        finally:
            if spinner:
                spinner.stop()

        choice = response.choices[0]
        msg = choice.message

        # Append the assistant message to history
        messages.append(_serialize_message(msg))

        # ── No tool calls → final answer ──
        if not msg.tool_calls:
            if msg.content:
                print(msg.content)
            if verbose:
                _log(f"[done] {turn} turn(s), {estimate_tokens(messages)} tokens")
            return messages

        # ── Execute tool calls ──
        # Claude Code's toolOrchestration.ts partitions into concurrent-safe
        # (read-only) and sequential (write) batches. We simplify: just run
        # them in order, which is always correct.
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}
                result = f"Error: invalid JSON in tool arguments: {tc.function.arguments[:200]}"
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                if verbose:
                    _log(f"  {fn_name}() → JSON parse error")
                continue

            tool = find_tool(fn_name)
            if not tool:
                result = f"Error: unknown tool '{fn_name}'. Available tools: {', '.join(t.name for t in ALL_TOOLS)}"
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                if verbose:
                    _log(f"  {fn_name}() → unknown tool")
                continue

            # Print what we're doing, with an activity spinner
            if verbose:
                summary = _summarize_tool_call(fn_name, fn_args)
                _log(f"  → {summary}")

            tool_spinner = None
            if verbose:
                verb = random.choice(TOOL_VERBS.get(fn_name, ["Running"]))
                tool_spinner = Spinner(f"{verb}")
                tool_spinner.start()

            # Execute (errors are returned as strings, not raised — this is key!)
            result = tool.execute(fn_args)

            if tool_spinner:
                tool_spinner.stop()

            if verbose:
                preview = result[:120].replace("\n", "\\n")
                _log(f"    ← {preview}{'...' if len(result) > 120 else ''}")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    _log(f"[warn] Reached max turns ({max_turns})")
    return messages


def _serialize_message(msg) -> dict:
    """Convert an OpenAI message object to a serializable dict."""
    d = {"role": msg.role}
    if msg.content:
        d["content"] = msg.content
    if msg.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    return d


def _summarize_tool_call(name: str, args: dict) -> str:
    """One-line summary for terminal display."""
    if name == "Bash":
        return f"Bash({args.get('command', '?')[:80]})"
    elif name == "Read":
        return f"Read({args.get('path', '?')})"
    elif name == "Edit":
        return f"Edit({args.get('file_path', '?')})"
    elif name == "Write":
        return f"Write({args.get('file_path', '?')})"
    elif name == "Grep":
        return f"Grep('{args.get('pattern', '?')}' in {args.get('path', '.')})"
    elif name == "Glob":
        return f"Glob({args.get('pattern', '?')})"
    else:
        return f"{name}({json.dumps(args)[:60]})"


def _log(msg: str):
    """Log to stderr so it doesn't mix with the model's output."""
    print(msg, file=sys.stderr)
