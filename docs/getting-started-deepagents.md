# Getting Started with DeepAgents (LangChain)

This demo runs a DeepAgents workflow on top of the MCP tools.

## 1) Install optional deps

```bash
uv sync --extra agents
```

## 2) Export a model API key

Example for OpenAI:

```bash
export OPENAI_API_KEY=...
```

## 3) Run the demo

```bash
uv run python examples/deepagents_demo.py
```

The demo script:
- Starts the stdio MCP server
- Loads MCP tools via LangChain MCP adapters
- Runs a few prompts from `PROMPTS.md`

## Notes

- You can change the model with `MODEL=openai:gpt-4o-mini` (or another provider supported by LangChain).
- The agent never executes APIs by default (execution is opt‑in).
