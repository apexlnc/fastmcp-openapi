"""Minimal DeepAgents demo using the stdio MCP server.

Prereqs:
  uv sync --extra agents
  export OPENAI_API_KEY=... (or another provider supported by LangChain)

Run:
  uv run python examples/deepagents_demo.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient

PROMPTS = [
    "Create a pet",
    "List all orders",
    "Rotate an API key",
]

SYSTEM_PROMPT = """
You are a developer assistant. Use MCP tools to:
1) search for the best operation
2) fetch the operation contract
3) generate a deterministic request skeleton
4) return curl snippet
Never execute real APIs.
""".strip()


def _server_config(root: Path) -> dict[str, Any]:
    return {
        "api_catalog": {
            "command": "uv",
            "args": ["run", "python", "-m", "api_catalog_mcp.server"],
            "transport": "stdio",
            "cwd": str(root),
            "env": {
                "OPENAPI_DIR": str(root / "specs"),
                "OPENAPI_INDEX_PATH": str(root / ".cache" / "api_catalog.sqlite"),
                "OPENAPI_DEREF_MODE": "lazy",
                "OPENAPI_WATCH": "1",
            },
        }
    }


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    client = MultiServerMCPClient(_server_config(repo_root))
    tools = await client.get_tools()

    model_name = os.getenv("MODEL", "openai:gpt-4o-mini")
    model = init_chat_model(model_name)

    agent = create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
    )

    for prompt in PROMPTS:
        print("\nPROMPT:", prompt)
        async for chunk in agent.astream({"messages": [("user", prompt)]}, stream_mode="values"):
            if "messages" in chunk and chunk["messages"]:
                chunk["messages"][-1].pretty_print()

    if hasattr(client, "aclose"):
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
