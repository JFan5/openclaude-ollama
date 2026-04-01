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
from openai import OpenAI
from .tools import ALL_TOOLS, get_openai_tools, find_tool
from .context import build_system_prompt
from .compact import estimate_tokens, needs_compaction, compact_messages


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
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
        except Exception as e:
            _log(f"[error] API call failed: {e}")
            # Retry once after a pause
            import time
            time.sleep(2)
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                )
            except Exception as e2:
                _log(f"[error] Retry failed: {e2}")
                break

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

            # Print what we're doing
            if verbose:
                summary = _summarize_tool_call(fn_name, fn_args)
                _log(f"  → {summary}")

            # Execute (errors are returned as strings, not raised — this is key!)
            result = tool.execute(fn_args)

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
