# Choosing a Model for Your Agent

## Requirements

Your model **must** support function calling / tool use natively. Without it, the agent loop cannot work. The model needs to:

1. Accept tool definitions in the request
2. Return structured `tool_calls` in the response (not just text that looks like tool calls)
3. Handle multi-turn conversations with tool results

## Recommended Models

### Tier 1: Best tool-use accuracy (>95%)

| Model | Size | Tool Use | How to Run | Notes |
|-------|------|----------|------------|-------|
| Qwen2.5-72B-Instruct | 72B | Native | Ollama, vLLM, Together | Best open-source option for agentic tasks |
| Qwen3-32B / 235B | 32-235B | Native | Ollama, vLLM | Latest generation, strong reasoning |
| DeepSeek-V3 | 671B (MoE) | Native | DeepSeek API, vLLM | Excellent coding, MoE = fast inference |
| GPT-4o / GPT-5.4 | Proprietary | Native | OpenAI API | Strong but not open-source |

### Tier 2: Good tool-use accuracy (85-95%)

| Model | Size | Tool Use | How to Run | Notes |
|-------|------|----------|------------|-------|
| Qwen2.5-32B-Instruct | 32B | Native | Ollama, vLLM | Good balance of speed and quality |
| Llama-3.3-70B | 70B | Native | Ollama, vLLM, Groq | Needs Hermes tool-call format |
| Mistral-Large-2 | 123B | Native | Mistral API, vLLM | Strong coding abilities |
| Command-R+ | 104B | Native | Cohere API | Good at following instructions |

### Tier 3: Usable but limited (70-85%)

| Model | Size | Tool Use | How to Run | Notes |
|-------|------|----------|------------|-------|
| Qwen2.5-14B-Instruct | 14B | Native | Ollama (runs on 16GB) | Smallest practical size for agents |
| Llama-3.1-8B | 8B | Basic | Ollama | Struggles with complex multi-step tasks |
| Phi-3.5-mini | 3.8B | Limited | Ollama | Too small for reliable tool use |

## Deployment Options

### Option A: Ollama (Easiest)

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model
ollama pull qwen2.5:72b    # Best quality (needs ~48GB RAM)
ollama pull qwen2.5:32b    # Good quality (needs ~24GB RAM)
ollama pull qwen2.5:14b    # Minimum viable (needs ~12GB RAM)

# Ollama auto-starts an OpenAI-compatible server at localhost:11434
```

### Option B: vLLM (Best performance)

```bash
pip install vllm

# Serve with tool-call support
vllm serve Qwen/Qwen2.5-72B-Instruct \
    --tool-call-parser hermes \
    --max-model-len 32768 \
    --tensor-parallel-size 2  # For multi-GPU
```

### Option C: Cloud APIs (No GPU needed)

```bash
# Together AI
export OPENAI_BASE_URL=https://api.together.xyz/v1
export OPENAI_API_KEY=your-key
export MODEL=Qwen/Qwen2.5-72B-Instruct-Turbo

# DeepSeek
export OPENAI_BASE_URL=https://api.deepseek.com/v1
export OPENAI_API_KEY=your-key
export MODEL=deepseek-chat

# Groq (fast inference)
export OPENAI_BASE_URL=https://api.groq.com/openai/v1
export OPENAI_API_KEY=your-key
export MODEL=llama-3.3-70b-versatile

# OpenAI
export OPENAI_API_KEY=your-key
export OPENAI_BASE_URL=https://api.openai.com/v1
export MODEL=gpt-4o
```

## Key Differences from Claude

Honest assessment of what you lose vs. Claude Opus/Sonnet:

| Capability | Claude (in Claude Code) | Open-Source 72B |
|-----------|------------------------|-----------------|
| Tool call accuracy | ~99% | ~90% |
| Multi-step reasoning | 15-20 steps stable | 5-8 steps stable |
| Error self-correction | Almost always | Usually (may need hints) |
| Code generation quality | Excellent | Good |
| Instruction following | Very precise | Good (occasional drift) |
| Context window | 200K tokens | 32-128K tokens |

**However**: A well-designed agent harness + 72B model often outperforms a raw API call to Claude/GPT-4o, because:
- The error recovery loop gives multiple chances to succeed
- Dynamic context injection provides relevant information
- Tool design determines what the model can do
- Auto-compact prevents context window failures
