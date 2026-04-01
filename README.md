# OpenClaude

**Build your own agentic coding assistant using open-source models.**

This project extracts the core architectural patterns from [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (Anthropic's AI coding agent) and re-implements them in ~500 lines of Python, runnable with **any model** that supports tool use — Ollama, vLLM, OpenAI, DeepSeek, Together AI, etc.

> **This is not a fork of Claude Code.** It is a clean-room implementation inspired by studying Claude Code's [decompiled source](https://github.com/anthropics/claude-code) (v2.1.88). The goal is education: understand *why* agentic systems work better than raw LLM calls, and build your own.

## Why agents beat single LLM calls

A single LLM call is like asking someone to write code with their eyes closed. An agent loop lets the model **observe → act → observe → correct**:

```
You: "Fix the failing test in src/auth.py"

Agent:
  → Bash(pytest tests/test_auth.py)            # observe: what's failing?
    ← FAILED test_login - AttributeError: 'User' has no attribute 'is_active'
  → Read(src/auth.py)                           # observe: what does the code look like?
    ← 1: class User: ...
  → Grep("is_active", path="src/")              # observe: where is is_active used?
    ← src/models.py:42: is_active = Column(Boolean)
  → Read(src/models.py, offset=38, limit=10)    # observe: check the model definition
    ← 42: active = Column(Boolean)              # found it — renamed to 'active'
  → Edit(src/auth.py, old="user.is_active", new="user.active")  # act: fix it
    ← Edited src/auth.py
  → Bash(pytest tests/test_auth.py)             # verify: does it pass now?
    ← PASSED

"Fixed: `is_active` was renamed to `active` in models.py. Updated auth.py to match."
```

This loop — powered by any capable model — is the core idea behind Claude Code, Cursor, Aider, and every modern coding agent.

## Quick start

### 1. Install

```bash
git clone https://github.com/YOUR_USERNAME/openclaude-ollama.git
cd openclaude-ollama
pip install -r requirements.txt
```

### 2. Start a model

**Option A: Ollama (local, free)**
```bash
ollama pull qwen2.5:32b   # or qwen2.5:72b for best quality
# Ollama serves at localhost:11434 automatically
```

**Option B: Cloud API (no GPU needed)**
```bash
# Together AI
export OPENAI_BASE_URL=https://api.together.xyz/v1
export OPENAI_API_KEY=your-key
export MODEL=Qwen/Qwen2.5-72B-Instruct-Turbo

# DeepSeek
export OPENAI_BASE_URL=https://api.deepseek.com/v1
export OPENAI_API_KEY=your-key
export MODEL=deepseek-chat
```

See [docs/model-comparison.md](docs/model-comparison.md) for all supported models and providers.

### 3. Run

```bash
# Interactive REPL
python -m src

# One-shot
python -m src "find all TODO comments in this project and list them"

# With a specific model
python -m src --model qwen2.5:72b "refactor the database module to use connection pooling"
```

## What's inside

```
src/
├── agent.py      # The agent loop (core pattern from Claude Code's query.ts)
├── tools.py      # Tool definitions (pattern from Tool.ts)
├── context.py    # Dynamic system prompt assembly (pattern from context.ts)
├── compact.py    # Context window management (pattern from services/compact/)
└── __main__.py   # CLI entry point

docs/
├── architecture.md      # Deep dive: the 7 patterns that make Claude Code work
└── model-comparison.md  # Which open-source models work best for agents

examples/
└── AGENT.md             # Example project memory file (like CLAUDE.md)
```

**Total: ~500 lines of Python.** Claude Code is ~30,000 lines of TypeScript — but most of that is UI, streaming, analytics, and Anthropic API specifics. The core agent logic is model-agnostic.

## The 7 patterns from Claude Code

These are the architectural insights that make the difference between a toy demo and a production agent. Each is implemented in this codebase:

### 1. Dynamic system prompt (`src/context.py`)

Don't use a static prompt. Inject real-time context:
- Current working directory, OS, shell
- Git branch, status, recent commits
- Project-specific instructions from `AGENT.md`

### 2. Standardized tool interface (`src/tools.py`)

Every tool has: name, description (for the model), JSON schema (for validation), execute function, and a read-only flag (for concurrency). Tools return error strings instead of raising exceptions.

### 3. Error recovery (the loop in `src/agent.py`)

When a tool fails, the error goes back to the model as a `tool_result`. The model sees the error and tries a different approach. This is the **#1 reason** agents outperform single calls.

### 4. Context window management (`src/compact.py`)

When the conversation grows too long, older messages are summarized by the model. Recent messages are preserved verbatim. This prevents context window crashes in long sessions.

### 5. Output budgeting (`src/tools.py:MAX_OUTPUT_CHARS`)

Tool outputs are truncated to a budget. A single `cat` of a 10MB file won't blow the context — the tool returns a truncated result with a note.

### 6. Project memory (`AGENT.md`)

Drop an `AGENT.md` (or `CLAUDE.md`) file in your project root. It's automatically loaded into the system prompt, giving the agent persistent project-specific knowledge across sessions.

### 7. Concurrency awareness (`src/tools.py:read_only`)

Tools declare whether they're read-only. Read-only tools (Grep, Glob, Read) can safely run in parallel. Write tools (Edit, Write, Bash) must run sequentially. (Parallel execution is not yet implemented in this project — it's an easy extension.)

> For the full deep dive, see [docs/architecture.md](docs/architecture.md).

## CLI options

```
usage: openclaude [-h] [--model MODEL] [--base-url URL] [--api-key KEY]
                  [--context-window N] [--max-turns N] [--quiet]
                  [prompt]

Options:
  prompt                One-shot prompt (omit for interactive REPL)
  --model, -m           Model name (default: $MODEL or qwen2.5:latest)
  --base-url            API base URL (default: $OPENAI_BASE_URL or localhost:11434)
  --api-key             API key (default: $OPENAI_API_KEY or "ollama")
  --context-window, -c  Context window in tokens (default: 32000)
  --max-turns, -t       Max agent loop iterations (default: 30)
  --quiet, -q           Suppress tool call logging
```

## Extending: add your own tools

Adding a tool is simple — define a `ToolDef` and add it to `ALL_TOOLS`:

```python
# In src/tools.py

def _my_tool(args: dict) -> str:
    """Always return a string. Errors too — never raise."""
    try:
        result = do_something(args["input"])
        return str(result)
    except Exception as e:
        return f"Error: {e}"   # Model will see this and adapt

MyTool = ToolDef(
    name="MyTool",
    description="What this tool does (the model reads this!)",
    parameters={
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "What the model should pass"},
        },
        "required": ["input"],
    },
    execute=_my_tool,
    read_only=True,   # True if it doesn't modify state
)

ALL_TOOLS.append(MyTool)
```

## Roadmap

Things from Claude Code that would be valuable to add:

- [ ] **Streaming responses** — show model output token-by-token
- [ ] **Concurrent tool execution** — run read-only tools in parallel
- [ ] **Sub-agents** — spawn child agents for subtask decomposition
- [ ] **Permission system** — ask user before destructive operations
- [ ] **Session persistence** — save/resume conversations
- [ ] **TUI with Textual/Rich** — terminal UI like Claude Code's Ink-based UI
- [ ] **MCP support** — connect external tool servers via Model Context Protocol

PRs welcome for any of the above.

## How this relates to Claude Code

| Aspect | Claude Code | This project |
|--------|-------------|-------------|
| Language | TypeScript + React (Ink) | Python |
| Lines of code | ~30,000 | ~500 |
| Model | Claude only | Any model with tool use |
| API coupling | Deep (Anthropic SDK types everywhere) | Minimal (OpenAI-compatible) |
| UI | Full TUI with Ink | Simple terminal REPL |
| Tool count | 40+ | 6 (the essential ones) |
| Features | Streaming, sub-agents, permissions, MCP, voice, vim mode, ... | Core agent loop + tools |

**The core agent loop is identical in structure.** Everything else is engineering around it.

## Acknowledgements

- Architecture patterns learned from studying [Claude Code](https://docs.anthropic.com/en/docs/claude-code) by Anthropic
- Inspired by the open-source agent community: [Aider](https://github.com/paul-gauthier/aider), [Continue](https://github.com/continuedev/continue), [SWE-agent](https://github.com/princeton-nlp/SWE-agent)

## License

MIT
