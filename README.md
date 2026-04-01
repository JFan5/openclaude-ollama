# OpenClaude

**Language**: **English** | [中文](README_CN.md)

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
git clone https://github.com/JFan5/openclaude-ollama.git
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

## Feature Status

### Implemented

| Feature | Claude Code Source | Our Implementation | Description |
|---------|-------------------|-------------------|-------------|
| Agent loop | `query.ts` | `src/agent.py` | Multi-turn observe → act → correct loop |
| Bash tool | `tools/BashTool/` | `src/tools.py` | Execute shell commands with timeout and safety checks |
| File Read | `tools/FileReadTool/` | `src/tools.py` | Read files with line numbers, offset, and limit |
| File Edit | `tools/FileEditTool/` | `src/tools.py` | Exact string replacement with diff output |
| File Write | `tools/FileWriteTool/` | `src/tools.py` | Create or overwrite files |
| Grep search | `tools/GrepTool/` | `src/tools.py` | Regex search across files |
| Glob search | `tools/GlobTool/` | `src/tools.py` | Find files by glob pattern |
| Dynamic system prompt | `context.ts` | `src/context.py` | Inject OS, cwd, git status, project memory at runtime |
| Project memory | `utils/claudemd.ts` | `src/context.py` | Load `AGENT.md` / `CLAUDE.md` into system prompt |
| Auto-compact | `services/compact/` | `src/compact.py` | Summarize old messages when context window is near limit |
| Output budgeting | `Tool.ts:maxResultSizeChars` | `src/tools.py` | Truncate large tool outputs to prevent context blowout |
| Error recovery | `toolExecution.ts` | `src/agent.py` | Return errors as strings, let model self-correct |
| Tool read-only flag | `Tool.ts:isConcurrencySafe` | `src/tools.py` | Tools declare whether they are read-only |
| Max turns guard | `QueryEngine.ts:maxTurns` | `src/agent.py` | Prevent infinite loops (default: 30) |
| One-shot mode | `entrypoints/cli.tsx` | `src/__main__.py` | Run a single prompt from command line |
| Interactive REPL | `replLauncher.tsx` | `src/__main__.py` | Interactive prompt with readline support |
| Multi-provider support | `services/api/client.ts` | `src/__main__.py` | Ollama, vLLM, OpenAI, DeepSeek, Together AI, etc. |
| Dangerous command filter | `bashPermissions.ts` | `src/tools.py` | Block obviously destructive shell commands |
| API retry | `services/api/withRetry.ts` | `src/agent.py` | Retry once on API failure |

### Not Yet Implemented

| Feature | Claude Code Source | Priority | Description |
|---------|-------------------|----------|-------------|
| Streaming responses | `services/api/claude.ts` | High | Show model output token-by-token |
| Concurrent tool execution | `toolOrchestration.ts` | High | Run read-only tools in parallel |
| Permission system | `useCanUseTool.tsx` | High | Ask user before destructive operations |
| Session persistence | `utils/sessionStorage.ts` | Medium | Save/resume conversations across sessions |
| Sub-agents | `tools/AgentTool/` | Medium | Spawn child agents for subtask decomposition |
| Notebook support | `tools/NotebookEditTool/` | Medium | Edit Jupyter notebooks |
| Web fetch | `tools/WebFetchTool/` | Medium | Fetch URLs and extract content |
| Web search | `tools/WebSearchTool/` | Medium | Search the web for information |
| LSP integration | `services/lsp/` | Medium | Language Server Protocol for code intelligence |
| Task system | `Task.ts`, `tasks/` | Medium | Background tasks with status tracking |
| TUI with Rich/Textual | `ink/`, `components/` | Low | Terminal UI with spinners, diffs, panels |
| MCP support | `services/mcp/` | Low | Connect external tool servers via Model Context Protocol |
| Hook system | `hooks/`, `utils/hooks.ts` | Low | Pre/post tool execution middleware |
| Vim mode | `vim/` | Low | Vim keybindings for input |
| Voice input | `voice/` | Low | Push-to-talk voice mode |
| Auto-memory extraction | `services/extractMemories/` | Low | Auto-save learnings to project memory |
| Coordinator mode | `coordinator/` | Low | Multi-agent orchestration with coordinator + workers |
| Skill system | `skills/` | Low | Reusable prompt templates (slash commands) |
| Cost tracking | `cost-tracker.ts` | Low | Track token usage and API costs |
| Git attribution | `utils/commitAttribution.ts` | Low | Add AI co-author to git commits |

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
