"""
CLI entry point — run with `python -m src` or `python -m src "your prompt"`.
"""

import os
import sys
import argparse
import readline  # enables backspace, arrow keys, and history in input()
from openai import OpenAI
from .agent import agent_loop


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
        default=int(os.environ.get("CONTEXT_WINDOW", "32000")),
        help="Context window size in tokens (default: 32000)",
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

    client = OpenAI(base_url=args.base_url, api_key=args.api_key)
    verbose = not args.quiet

    print(f"openclaude (model: {args.model}, cwd: {os.getcwd()})", file=sys.stderr)

    if args.prompt:
        # One-shot mode
        agent_loop(
            client, args.model, args.prompt,
            context_window=args.context_window,
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
                    context_window=args.context_window,
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
