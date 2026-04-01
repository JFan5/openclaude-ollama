# Architecture: What Makes Claude Code Work

> Lessons extracted from reverse-engineering Claude Code v2.1.88 source code.

## The Core Insight

Strip away the 30,000 lines of TypeScript and you find a simple loop:

```
while True:
    response = LLM(system_prompt + messages + tool_definitions)
    if response has tool_calls:
        execute tools → append results → continue
    else:
        break
```

This loop is implemented in `query.ts` (~800 lines). Everything else — the UI, permissions, streaming, analytics — is infrastructure around this loop. **The loop itself is model-agnostic.**

## The 7 Design Patterns That Matter

### 1. Dynamic System Prompt (context.ts, QueryEngine.ts)

Claude Code's system prompt is **not** a static string. It is assembled fresh each session from:

| Source | Content | Why |
|--------|---------|-----|
| Role definition | Behavior rules, coding style | Consistent personality |
| Environment | OS, shell, cwd, platform | Model knows where it is |
| Git state | Branch, status, recent commits | Project awareness |
| CLAUDE.md | Project-specific instructions | Cross-session memory |
| Tool descriptions | Available tools + usage rules | Model knows what it can do |
| User context | Name, preferences, history | Personalization |

**Takeaway**: Invest in your system prompt. Dynamic context injection is the single highest-leverage improvement you can make.

### 2. Tool Abstraction (Tool.ts)

Every capability is a `Tool` with a standardized interface:

```typescript
type Tool = {
    name: string
    description: string          // For the model
    inputSchema: ZodSchema       // JSON Schema for parameters
    call(): ToolResult            // Execute the tool
    checkPermissions(): boolean   // Security gate
    isConcurrencySafe(): boolean  // Can run in parallel?
    isReadOnly(): boolean         // Does it modify state?
    maxResultSizeChars: number    // Output budget
}
```

Claude Code ships with 40+ tools. The essential ones:
- **Bash** — run shell commands
- **Read/Edit/Write** — file operations
- **Grep/Glob** — search operations
- **Agent** — spawn sub-agents (recursive!)

**Takeaway**: Tools should be self-describing (the model reads the description), safe (validate inputs, catch errors), and budget-aware (truncate large outputs).

### 3. Error Recovery (toolExecution.ts)

This is **the #1 reason** agents outperform single LLM calls.

When a tool fails, Claude Code does NOT crash. Instead:
1. The error message is wrapped in `<tool_use_error>` tags
2. It's sent back to the model as a `tool_result`
3. The model sees the error and tries a different approach

```
Model: Edit("src/foo.py", old="class Foo:", new="class Bar:")
Tool:  Error: old_string not found in src/foo.py
Model: Read("src/foo.py")  ← model self-corrects by reading first
Tool:  1: class FooHandler:  ...
Model: Edit("src/foo.py", old="class FooHandler:", new="class Bar:")
Tool:  Success
```

**Takeaway**: Never raise exceptions from tools. Return error strings and let the model adapt.

### 4. Concurrent Tool Execution (toolOrchestration.ts)

Claude Code partitions tool calls into batches:
- **Read-only tools** (Grep, Glob, Read) → run in parallel
- **Write tools** (Edit, Write, Bash) → run sequentially

This is why Claude Code can search 5 files simultaneously — it's not the model doing it, it's the harness.

```
Tool calls from model: [Read(a.py), Read(b.py), Grep("TODO"), Edit(c.py)]

Batch 1 (parallel):  Read(a.py), Read(b.py), Grep("TODO")
Batch 2 (sequential): Edit(c.py)
```

**Takeaway**: Classify your tools as read-only or not. Run read-only tools concurrently.

### 5. Context Window Management (services/compact/)

Long conversations inevitably hit the context limit. Claude Code has 3 layers:

| Layer | Trigger | Action |
|-------|---------|--------|
| Tool result budget | Output > `maxResultSizeChars` | Truncate, save full output to disk |
| Auto-compact | Context > 80% of window | Summarize old messages with the model |
| Snip | Context still too long | Drop oldest messages entirely |

The auto-compact summarizer is itself an LLM call that produces a condensed version of the conversation history, preserving key decisions and file changes.

**Takeaway**: Implement at least tool output truncation and auto-compact. Without them, long sessions will fail.

### 6. Sub-Agents (AgentTool/)

Claude Code can spawn child agents that:
- Have their own conversation history
- Get a restricted set of tools
- Run independently (even in background)
- Report results back to the parent

This enables task decomposition: the main agent plans, sub-agents execute specific subtasks.

**Takeaway**: For complex tasks, recursive agent spawning is powerful but requires careful scoping (limited tools, separate context, abort controls).

### 7. Permission System (useCanUseTool.tsx)

Three-layer security model:

1. **Static rules** — config file says "always allow Read", "always deny rm -rf"
2. **Classifier** — ML model evaluates whether a tool call is safe
3. **User confirmation** — prompt the user for dangerous operations

**Takeaway**: At minimum, implement a blocklist for dangerous commands. Ideally, ask the user before any file write or destructive shell command.

## Data Flow

```
User input
    │
    ▼
processUserInput()          ← Parse slash commands, attachments
    │
    ▼
build_system_prompt()       ← Assemble dynamic context
    │
    ▼
┌─────────────────────────────────────────┐
│             Agent Loop                   │
│                                          │
│   LLM call (streaming)                   │
│       │                                  │
│       ├── text response → yield to user  │
│       │                                  │
│       └── tool_use blocks                │
│               │                          │
│         validate input                   │
│         check permissions                │
│         execute tool                     │
│         append tool_result               │
│               │                          │
│         ┌─────▼──────┐                   │
│         │ Need more   │── yes ──→ loop   │
│         │ tool calls? │                  │
│         └─────┬──────┘                   │
│               │ no                       │
│               ▼                          │
│         return final response            │
└─────────────────────────────────────────┘
    │
    ▼
Auto-compact if context too long
    │
    ▼
Save to session history
```

## File Map: Claude Code Source → This Project

| Claude Code | Purpose | Our equivalent |
|-------------|---------|---------------|
| `query.ts` | Agent loop | `src/agent.py` |
| `Tool.ts` | Tool interface | `src/tools.py:ToolDef` |
| `tools.ts` | Tool registry | `src/tools.py:ALL_TOOLS` |
| `context.ts` | System prompt | `src/context.py` |
| `services/compact/` | Context compression | `src/compact.py` |
| `services/api/claude.ts` | API client | `openai` library |
| `toolOrchestration.ts` | Concurrent execution | (simplified in agent.py) |
| `toolExecution.ts` | Tool runner + error handling | `src/tools.py:execute` |
| `QueryEngine.ts` | Session lifecycle | `src/agent.py:agent_loop` |
