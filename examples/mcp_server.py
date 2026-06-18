"""MCP server — exposes segkv MemoryStore as Claude Code tools.

Claude Code will have five persistent memory tools in every session once
this server is registered. Memories survive across conversations because
they are stored in a segkv log-structured database on disk.

─── Quick setup ────────────────────────────────────────────────────────────

1. Add to ~/.claude/settings.json  (user-wide, all projects):

    {
      "mcpServers": {
        "segkv-memory": {
          "command": "uv",
          "args": [
            "--directory", "/absolute/path/to/segkv",
            "run", "python", "examples/mcp_server.py"
          ]
        }
      }
    }

   Or add to .claude/settings.json in the project root (this project only).

2. Restart Claude Code — it will launch the server automatically.

─── Override the database path ─────────────────────────────────────────────

    "args": [..., "--db-path", "/custom/path/memory.db"]

or set SEGKV_DB_PATH in the "env" block of the mcpServers entry.

Default: ~/.claude/memory.db  (same path as the `memory` CLI, so the CLI
and Claude Code share the same memories).

─── Available tools ─────────────────────────────────────────────────────────

  save_memory(name, type, description, content)
  recall_memory(name)
  search_memories(query)
  list_memories([type_filter])
  delete_memory(name)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

sys.path.insert(0, str(Path(__file__).parent.parent))
from memory.store import MemoryStore

_SERVER_NAME = "segkv-memory"
_DEFAULT_DB = Path.home() / ".claude" / "memory.db"

_TOOLS: list[types.Tool] = [
    types.Tool(
        name="save_memory",
        description=(
            "Persist a piece of information so it survives across conversations. "
            "Call this when you learn something worth remembering — user preferences, "
            "project context, corrections, or external references. "
            "Re-saving an existing name updates it and preserves the original created_at."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short kebab-case slug, e.g. 'user-preferred-language'",
                },
                "type": {
                    "type": "string",
                    "enum": ["user", "feedback", "project", "reference"],
                    "description": (
                        "user — facts about the user; "
                        "feedback — corrections / style preferences; "
                        "project — work context, goals, deadlines; "
                        "reference — pointers to docs, URLs, systems"
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "One-line summary shown in the memory index",
                },
                "content": {
                    "type": "string",
                    "description": "Full memory body — be detailed enough to be useful later",
                },
            },
            "required": ["name", "type", "description", "content"],
        },
    ),
    types.Tool(
        name="recall_memory",
        description="Retrieve a specific memory by its exact name/slug.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Exact slug of the memory to fetch",
                },
            },
            "required": ["name"],
        },
    ),
    types.Tool(
        name="search_memories",
        description=(
            "Case-insensitive substring search across all memory names, "
            "descriptions, and content. Use this before answering questions "
            "that might benefit from prior context."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term"},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="list_memories",
        description="List all saved memories, optionally filtered to one type.",
        inputSchema={
            "type": "object",
            "properties": {
                "type_filter": {
                    "type": "string",
                    "enum": ["user", "feedback", "project", "reference"],
                    "description": "If provided, only return memories of this type",
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="delete_memory",
        description="Permanently delete a memory by name.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Slug of the memory to delete",
                },
            },
            "required": ["name"],
        },
    ),
]


def _dispatch(store: MemoryStore, name: str, args: dict[str, Any]) -> Any:
    if name == "save_memory":
        return store.set_memory(
            name=args["name"],
            type_=args["type"],
            description=args["description"],
            content=args["content"],
        )
    if name == "recall_memory":
        record = store.get_memory(args["name"])
        if record is None:
            return {"error": f"No memory named '{args['name']}'"}
        return record
    if name == "search_memories":
        hits = store.search_memories(args["query"])
        return {"count": len(hits), "results": hits}
    if name == "list_memories":
        records = store.list_memories(type_filter=args.get("type_filter"))
        return {"count": len(records), "memories": records}
    if name == "delete_memory":
        deleted = store.delete_memory(args["name"])
        return {"deleted": deleted}
    return {"error": f"Unknown tool: {name}"}


def _build_server(store: MemoryStore) -> Server:
    server = Server(_SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return _TOOLS

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent]:
        try:
            result = _dispatch(store, name, arguments or {})
        except ValueError as exc:
            result = {"error": str(exc)}
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


async def _serve(db_path: str) -> None:
    store = MemoryStore(db_path=db_path)
    try:
        server = _build_server(store)
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="segkv MCP memory server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db-path",
        default=os.environ.get("SEGKV_DB_PATH", str(_DEFAULT_DB)),
        help=f"segkv database directory (default: {_DEFAULT_DB})",
    )
    args = parser.parse_args()
    Path(args.db_path).parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_serve(db_path=args.db_path))


if __name__ == "__main__":
    main()
