"""
Context window management — auto-compaction.

When a conversation grows too long, the model loses coherence or hits the
context limit. Claude Code solves this with multiple layers of compression
(see services/compact/ in the source):

  1. Tool result budget — truncate individual tool outputs (see tools.py MAX_OUTPUT_CHARS)
  2. Auto-compact — when total tokens approach the limit, summarize older messages
  3. Snip — drop the oldest messages entirely (aggressive, last resort)

This module implements a simplified version of auto-compact.
"""

import json
from openai import OpenAI

# Rough estimate: 1 token ≈ 3.5 chars for English, 2 chars for code
CHARS_PER_TOKEN = 3


def estimate_tokens(messages: list[dict]) -> int:
    """Cheap token estimation without a tokenizer."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            total += sum(len(json.dumps(block)) for block in content)
        # tool_calls contribute to token count
        if "tool_calls" in msg:
            total += len(json.dumps(msg["tool_calls"]))
    return total // CHARS_PER_TOKEN


def needs_compaction(messages: list[dict], context_window: int) -> bool:
    """
    Check if we should compact. Claude Code triggers at ~80% of context window.
    We use 70% to leave headroom for the model's response.
    """
    threshold = int(context_window * 0.70)
    return estimate_tokens(messages) > threshold


def compact_messages(
    client: OpenAI,
    model: str,
    messages: list[dict],
    context_window: int,
) -> list[dict]:
    """
    Compress conversation history by summarizing old messages.

    Strategy (from Claude Code's compact/compact.ts):
      - Keep the system prompt (messages[0])
      - Summarize everything except the last few messages
      - Preserve recent messages verbatim (the model needs exact context for current work)
      - The summary includes: key decisions, files modified, errors encountered, current state
    """
    if len(messages) <= 4:
        return messages  # Nothing worth compacting

    system = messages[0]

    # Keep the last N messages intact (at least the last user + assistant exchange)
    keep_recent = min(6, len(messages) - 1)
    to_summarize = messages[1:-keep_recent]
    recent = messages[-keep_recent:]

    if not to_summarize:
        return messages

    # Build a condensed representation of the history
    history_text = _format_history_for_summary(to_summarize)

    # Use the model to summarize
    try:
        summary_response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a conversation summarizer. Produce a concise summary of the "
                        "following conversation history. Focus on:\n"
                        "1. What task the user asked for\n"
                        "2. Key decisions made and why\n"
                        "3. Files that were read, created, or modified (with paths)\n"
                        "4. Commands that were run and their outcomes\n"
                        "5. Errors encountered and how they were resolved\n"
                        "6. Current state of the work\n\n"
                        "Be factual and specific. Include file paths and command outputs that "
                        "are still relevant. Omit tool call IDs and internal metadata."
                    ),
                },
                {"role": "user", "content": history_text},
            ],
            max_tokens=1500,
            temperature=0,
        )
        summary = summary_response.choices[0].message.content
    except Exception as e:
        # If summarization fails, fall back to aggressive truncation
        summary = _fallback_summary(to_summarize)

    # Reconstruct: system + summary + recent
    return [
        system,
        {
            "role": "user",
            "content": f"[Previous conversation summary]\n{summary}",
        },
        {
            "role": "assistant",
            "content": "I have the context from our previous conversation. Let me continue.",
        },
        *recent,
    ]


def _format_history_for_summary(messages: list[dict]) -> str:
    """Convert messages to a readable format for the summarizer."""
    parts = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if role == "tool":
            # Summarize tool results compactly
            result = content if isinstance(content, str) else json.dumps(content)
            if len(result) > 500:
                result = result[:500] + "..."
            parts.append(f"[Tool result]: {result}")
        elif role == "assistant" and "tool_calls" in msg:
            # Show what tools were called
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                name = fn.get("name", "?")
                args = fn.get("arguments", "{}")
                if len(args) > 200:
                    args = args[:200] + "..."
                parts.append(f"[Assistant called {name}]: {args}")
            if content:
                parts.append(f"[Assistant]: {content}")
        elif isinstance(content, str) and content:
            parts.append(f"[{role.title()}]: {content[:1000]}")

    return "\n".join(parts)


def _fallback_summary(messages: list[dict]) -> str:
    """If the LLM summary fails, create a mechanical summary."""
    files_mentioned = set()
    commands_run = []

    for msg in messages:
        content = str(msg.get("content", ""))
        # Extract file paths (simple heuristic)
        for word in content.split():
            if "/" in word and not word.startswith("http"):
                clean = word.strip("'\"(),;:")
                if any(clean.endswith(ext) for ext in [".py", ".ts", ".js", ".md", ".json", ".yaml", ".toml"]):
                    files_mentioned.add(clean)
        # Extract commands
        if msg.get("role") == "assistant" and "tool_calls" in msg:
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                if fn.get("name") == "Bash":
                    try:
                        cmd = json.loads(fn.get("arguments", "{}")).get("command", "")
                        if cmd:
                            commands_run.append(cmd[:100])
                    except Exception:
                        pass

    parts = ["(Auto-generated summary — LLM summarization failed)"]
    if files_mentioned:
        parts.append(f"Files involved: {', '.join(sorted(files_mentioned)[:20])}")
    if commands_run:
        parts.append(f"Commands run: {'; '.join(commands_run[:10])}")

    return "\n".join(parts)
