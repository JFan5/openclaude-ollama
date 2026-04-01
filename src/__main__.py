"""
CLI entry point — run with `python -m src` or `python -m src "your prompt"`.
"""

import os
import sys
import argparse
import readline  # enables backspace, arrow keys, and history in input()
from urllib.parse import urlparse
from openai import OpenAI
from .agent import agent_loop


# ── Auto-detect context window from Ollama ────────────────────────────────────

# Well-known context window sizes for cloud models / models that don't
# report their context length via the API.
KNOWN_CONTEXT_WINDOWS = {
    "minimax-m2.5": 1_000_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-3.5-turbo": 16_385,
    "deepseek-chat": 64_000,
    "deepseek-reasoner": 64_000,
    "claude-sonnet-4-20250514": 200_000,
    "claude-opus-4-20250514": 200_000,
}

DEFAULT_CONTEXT_WINDOW = 32_000


def detect_context_window(base_url: str, model: str) -> int:
    """
    Try to auto-detect the model's context window size.

    Strategy:
      1. If it's an Ollama server, query /api/show for *.context_length
      2. Fall back to KNOWN_CONTEXT_WINDOWS by prefix match
      3. Fall back to DEFAULT_CONTEXT_WINDOW (32k)
    """
    # 1. Try Ollama native API
    ollama_base = _get_ollama_base(base_url)
    if ollama_base:
        ctx = _query_ollama_context(ollama_base, model)
        if ctx:
            return ctx

    # 2. Try known models by prefix
    for prefix, ctx in KNOWN_CONTEXT_WINDOWS.items():
        if model.startswith(prefix) or model.endswith(prefix):
            return ctx

    # 3. Fall back
    return DEFAULT_CONTEXT_WINDOW


def _get_ollama_base(base_url: str) -> str | None:
    """Extract Ollama base URL (without /v1) if this looks like an Ollama server."""
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    port = parsed.port

    # Common Ollama patterns: localhost:11434, 127.0.0.1:11434
    if port == 11434 or "ollama" in host:
        # Strip /v1 suffix if present
        scheme = parsed.scheme or "http"
        return f"{scheme}://{host}:{port}" if port else f"{scheme}://{host}"

    return None


def _query_ollama_context(ollama_base: str, model: str) -> int | None:
    """Query Ollama's /api/show endpoint for the model's context_length."""
    import json
    from urllib.request import urlopen, Request
    from urllib.error import URLError

    try:
        req = Request(
            f"{ollama_base}/api/show",
            data=json.dumps({"name": model}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())

        # Search model_info for any key ending in .context_length
        model_info = data.get("model_info", {})
        for key, value in model_info.items():
            if key.endswith(".context_length") and isinstance(value, int):
                return value

        # Some Ollama models store it in parameters
        params = data.get("parameters", "")
        if isinstance(params, str):
            for line in params.split("\n"):
                if "num_ctx" in line:
                    try:
                        return int(line.split()[-1])
                    except (ValueError, IndexError):
                        pass

    except (URLError, OSError, json.JSONDecodeError, KeyError):
        pass

    return None


def main():
    parser = argparse.ArgumentParser(
        prog="openclaude",
        description="An open-source agentic coding assistant inspired by Claude Code",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="One-shot prompt (if omitted, starts interactive REPL)",
    )
    parser.add_argument(
        "--model", "-m",
        default=os.environ.get("MODEL", "qwen2.5:latest"),
        help="Model name (default: $MODEL or qwen2.5:latest)",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OPENAI_BASE_URL", "http://localhost:11434/v1"),
        help="API base URL (default: $OPENAI_BASE_URL or http://localhost:11434/v1)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENAI_API_KEY", "ollama"),
        help="API key (default: $OPENAI_API_KEY or 'ollama')",
    )
    parser.add_argument(
        "--context-window", "-c",
        type=int,
        default=None,
        help="Context window size in tokens (auto-detected if omitted)",
    )
    parser.add_argument(
        "--max-turns", "-t",
        type=int,
        default=30,
        help="Max agent loop iterations (default: 30)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress tool call logging",
    )
    args = parser.parse_args()

    # Resolve context window: CLI flag > env var > auto-detect
    if args.context_window is not None:
        context_window = args.context_window
    elif os.environ.get("CONTEXT_WINDOW"):
        context_window = int(os.environ["CONTEXT_WINDOW"])
    else:
        context_window = detect_context_window(args.base_url, args.model)

    client = OpenAI(base_url=args.base_url, api_key=args.api_key)
    verbose = not args.quiet

    from .statusbar import _format_tokens
    print(
        f"openclaude (model: {args.model}, context: {_format_tokens(context_window)}, cwd: {os.getcwd()})",
        file=sys.stderr,
    )

    if args.prompt:
        # One-shot mode
        agent_loop(
            client, args.model, args.prompt,
            context_window=context_window,
            max_turns=args.max_turns,
            verbose=verbose,
        )
    else:
        # Interactive REPL
        print("Type your request. Press Ctrl+C to exit.\n", file=sys.stderr)
        while True:
            try:
                user_input = input("> ")
                if not user_input.strip():
                    continue
                if user_input.strip().lower() in ("exit", "quit"):
                    break
                agent_loop(
                    client, args.model, user_input,
                    context_window=context_window,
                    max_turns=args.max_turns,
                    verbose=verbose,
                )
                print()  # Blank line between turns
            except KeyboardInterrupt:
                print("\nBye!", file=sys.stderr)
                break
            except EOFError:
                break


if __name__ == "__main__":
    main()
