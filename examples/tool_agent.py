"""Pattern 1: Tool-augmented agent.

Claude calls save_memory / recall_memory / search_memories / list_memories /
delete_memory as tools mid-conversation. Every memory survives across runs
because segkv is a persistent key-value store.

Usage:
    uv run python examples/tool_agent.py
    uv run python examples/tool_agent.py --db-path /tmp/demo.db

Type "memories" at the prompt to list what Claude has saved.
Type "quit" to exit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import anthropic

sys.path.insert(0, str(Path(__file__).parent.parent))
from memory.store import MemoryStore

MODEL = "claude-opus-4-8"
DEFAULT_DB = Path.home() / ".claude" / "segkv_agent_demo.db"

SYSTEM = """\
You are a helpful assistant with persistent memory backed by segkv,
a log-structured key-value store.

You have five memory tools. Use them proactively:
- When you learn something important about the user, save it.
- Before answering a question that might benefit from prior context, search first.
- Tell the user when you save or recall something so the interaction feels natural.

Memory types:
  user       — facts about the user (name, role, preferences)
  feedback   — corrections and style guidance the user has given you
  project    — context about ongoing work, goals, deadlines
  reference  — pointers to external resources (URLs, systems, docs)
"""

TOOLS: list[dict[str, Any]] = [
    {
        "name": "save_memory",
        "description": (
            "Persist a piece of information so it survives across conversations. "
            "Call this whenever you learn something worth remembering — user preferences, "
            "project context, corrections, or external references."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short kebab-case slug, e.g. 'user-preferred-language'",
                },
                "type": {
                    "type": "string",
                    "enum": ["user", "feedback", "project", "reference"],
                    "description": "Category of memory",
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
    },
    {
        "name": "recall_memory",
        "description": "Retrieve a specific memory by its exact name/slug.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Exact slug of the memory to fetch",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "search_memories",
        "description": (
            "Full-text search across all memory names, descriptions, and content. "
            "Case-insensitive substring match. Use this before answering questions "
            "that might benefit from past context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_memories",
        "description": "List all saved memories, optionally filtered to one type.",
        "input_schema": {
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
    },
    {
        "name": "delete_memory",
        "description": "Permanently delete a memory by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Slug of the memory to delete",
                },
            },
            "required": ["name"],
        },
    },
]


def _dispatch(store: MemoryStore, name: str, inputs: dict[str, Any]) -> str:
    """Run one tool call and return a JSON string result."""
    try:
        if name == "save_memory":
            record = store.set_memory(
                name=inputs["name"],
                type_=inputs["type"],
                description=inputs["description"],
                content=inputs["content"],
            )
            return json.dumps({"ok": True, "record": record})

        if name == "recall_memory":
            record = store.get_memory(inputs["name"])
            if record is None:
                return json.dumps(
                    {"ok": False, "error": f"No memory named '{inputs['name']}'"}
                )
            return json.dumps({"ok": True, "record": record})

        if name == "search_memories":
            hits = store.search_memories(inputs["query"])
            return json.dumps({"ok": True, "count": len(hits), "results": hits})

        if name == "list_memories":
            type_filter = inputs.get("type_filter")
            records = store.list_memories(type_filter=type_filter)
            return json.dumps({"ok": True, "count": len(records), "memories": records})

        if name == "delete_memory":
            deleted = store.delete_memory(inputs["name"])
            return json.dumps({"ok": deleted, "deleted": deleted})

        return json.dumps({"ok": False, "error": f"Unknown tool: {name}"})

    except ValueError as exc:
        return json.dumps({"ok": False, "error": str(exc)})


def _print_memories(store: MemoryStore) -> None:
    records = store.list_memories()
    if not records:
        print("[no memories saved yet]")
        return
    print(f"[{len(records)} saved memories]")
    for r in records:
        print(f"  [{r['type']:9s}] {r['name']}: {r['description']}")


def run(db_path: str) -> None:
    client = anthropic.Anthropic()
    store = MemoryStore(db_path=db_path)
    messages: list[dict[str, Any]] = []

    print(f"Memory agent — db: {db_path}")
    print("Commands: 'memories' to list saved memories, 'quit' to exit.\n")

    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break

            if not user_input:
                continue
            if user_input.lower() == "quit":
                print("Goodbye!")
                break
            if user_input.lower() == "memories":
                _print_memories(store)
                print()
                continue

            messages.append({"role": "user", "content": user_input})

            # Agentic loop — continues until end_turn or an unexpected stop reason
            while True:
                response = client.messages.create(
                    model=MODEL,
                    max_tokens=4096,
                    system=SYSTEM,
                    tools=TOOLS,  # type: ignore[arg-type]
                    messages=messages,
                    thinking={"type": "adaptive"},  # type: ignore[arg-type]
                )

                # Preserve the full content array (includes thinking + tool_use blocks)
                messages.append({"role": "assistant", "content": response.content})  # type: ignore[arg-type]

                if response.stop_reason == "end_turn":
                    for block in response.content:
                        if block.type == "text":
                            print(f"\nAssistant: {block.text}\n")
                    break

                if response.stop_reason == "tool_use":
                    results = []
                    for block in response.content:
                        if block.type == "tool_use":
                            print(f"  [tool] {block.name}({json.dumps(block.input)})")
                            result = _dispatch(store, block.name, block.input)
                            results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": result,
                                }
                            )
                    messages.append({"role": "user", "content": results})
                    continue

                print(f"[unexpected stop_reason: {response.stop_reason}]")
                break

    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB),
        help=f"segkv database directory (default: {DEFAULT_DB})",
    )
    args = parser.parse_args()
    Path(args.db_path).parent.mkdir(parents=True, exist_ok=True)
    run(db_path=args.db_path)


if __name__ == "__main__":
    main()
