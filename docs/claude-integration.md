# Claude Integration

segkv can serve as the memory layer for Claude in three ways:

1. **MCP server** — register the bundled stdio server and Claude Code gets five persistent memory tools, no code required. See the dedicated [MCP Server](mcp-server.md) page.
2. **Claude Code memory import** — import Claude Code's file-based memories into segkv for querying, backup, and compaction
3. **Custom Claude agents** — use segkv as the persistent memory backend for agents built with the Claude Agent SDK or the raw Anthropic SDK

This page covers (2) and (3); for (1) see [MCP Server](mcp-server.md).

## With Claude Code

Claude Code stores memories as markdown files on disk:

```
~/.claude/projects/<project-slug>/memory/
├── MEMORY.md              # Index file (loaded at session start)
├── user_role.md           # Individual memory files
├── feedback_testing.md
└── project_goals.md
```

Each memory file has YAML frontmatter:

```markdown
---
name: No mocks in integration tests
description: Use real database connections in integration tests
type: feedback
---

Integration tests must hit a real database, not mocks.
Reason: prior incident where mock/prod divergence masked a broken migration.
```

segkv's `import-md` command bridges these two systems.

### Importing memories

Import all memories from a Claude Code project into segkv:

```bash
memory import-md ~/.claude/projects/-Users-me-myproject/memory/
```

This parses each `.md` file's frontmatter (skipping `MEMORY.md`) and stores the records in the segkv database. You can then query, search, and manage them with the full CLI.

### Querying imported memories

```bash
# Search across all imported memories
memory search "database"

# List by type
memory list --type feedback

# Get a specific memory
memory get "No mocks in integration tests"
```

### Python usage

```python
from memory.store import MemoryStore
from memory.migrate import import_md_files

store = MemoryStore(db_path="~/.claude/memory.db")

# Bulk import from Claude Code's memory directory
imported = import_md_files(
    "~/.claude/projects/-Users-me-myproject/memory/",
    store,
)
print(f"Imported {len(imported)} memories")

# Now query with the full API
results = store.search_memories("database")
for r in results:
    print(f"[{r['type']}] {r['name']}: {r['description']}")

store.close()
```

### Syncing across projects

Claude Code scopes memories per project. segkv can unify them:

```python
from pathlib import Path
from memory.store import MemoryStore
from memory.migrate import import_md_files

store = MemoryStore(db_path="./unified_memories")

# Import from all Claude Code projects
claude_projects = Path("~/.claude/projects").expanduser()
for project_dir in claude_projects.iterdir():
    memory_dir = project_dir / "memory"
    if memory_dir.is_dir():
        imported = import_md_files(str(memory_dir), store)
        print(f"{project_dir.name}: {len(imported)} memories")

store.compact()
store.close()
```

---

## With custom Claude agents

Use the Claude Agent SDK to build agents that read and write memories through segkv as tool calls.

### Install dependencies

```bash
pip install claude-agent-sdk segkv
```

### Define memory tools

Wrap each `MemoryStore` method as a tool the agent can call:

```python
from claude_agent_sdk import tool, create_sdk_mcp_server
from memory.store import MemoryStore

store = MemoryStore(db_path="./agent_memory")


@tool(
    "save_memory",
    "Save information to persistent memory for future conversations. "
    "Use type 'user' for user info, 'feedback' for approach guidance, "
    "'project' for ongoing work context, 'reference' for external resource pointers.",
    {
        "name": str,
        "type": str,
        "description": str,
        "content": str,
    },
)
async def save_memory(args: dict) -> dict:
    record = store.set_memory(
        name=args["name"],
        type_=args["type"],
        description=args["description"],
        content=args["content"],
    )
    return {
        "content": [{"type": "text", "text": f"Saved memory: {record['name']}"}]
    }


@tool(
    "recall_memory",
    "Retrieve a specific memory by its exact name.",
    {"name": str},
)
async def recall_memory(args: dict) -> dict:
    record = store.get_memory(args["name"])
    if record is None:
        return {"content": [{"type": "text", "text": "Memory not found."}]}
    import json
    return {"content": [{"type": "text", "text": json.dumps(record, indent=2)}]}


@tool(
    "search_memory",
    "Search memories by keyword. Returns all memories whose name, "
    "description, or content contains the query string.",
    {"query": str},
)
async def search_memory(args: dict) -> dict:
    results = store.search_memories(args["query"])
    import json
    return {"content": [{"type": "text", "text": json.dumps(results, indent=2)}]}


@tool(
    "list_memories",
    "List all stored memories, optionally filtered by type.",
    {"type_filter": str},
)
async def list_memories(args: dict) -> dict:
    type_filter = args.get("type_filter") or None
    results = store.list_memories(type_filter=type_filter)
    import json
    summary = [{"name": r["name"], "type": r["type"], "description": r["description"]} for r in results]
    return {"content": [{"type": "text", "text": json.dumps(summary, indent=2)}]}


@tool(
    "delete_memory",
    "Delete a memory by name.",
    {"name": str},
)
async def delete_memory(args: dict) -> dict:
    deleted = store.delete_memory(args["name"])
    status = "deleted" if deleted else "not found"
    return {"content": [{"type": "text", "text": f"Memory '{args['name']}': {status}"}]}
```

### Create the MCP server and agent

```python
from claude_agent_sdk import create_sdk_mcp_server, ClaudeSDKClient, ClaudeAgentOptions

# Bundle tools into an MCP server
memory_server = create_sdk_mcp_server(
    name="memory-store",
    version="1.0.0",
    tools=[save_memory, recall_memory, search_memory, list_memories, delete_memory],
)

# Configure the agent
options = ClaudeAgentOptions(
    mcp_servers={"memory-store": memory_server},
    allowed_tools=[
        "mcp__memory-store__save_memory",
        "mcp__memory-store__recall_memory",
        "mcp__memory-store__search_memory",
        "mcp__memory-store__list_memories",
        "mcp__memory-store__delete_memory",
    ],
    system_prompt=(
        "You have access to a persistent memory store. "
        "Use it to remember important context across conversations. "
        "Before starting a task, search your memories for relevant context. "
        "After learning something important, save it as a memory."
    ),
)
```

### Run the agent

```python
import asyncio

async def main():
    async with ClaudeSDKClient(options=options) as client:
        # The agent can now save and recall memories across sessions
        await client.query(
            "Remember that the user prefers dark mode and uses vim keybindings."
        )
        async for msg in client.receive_response():
            print(msg)

        # In a later conversation, the agent can recall this
        await client.query(
            "What do you know about the user's preferences?"
        )
        async for msg in client.receive_response():
            print(msg)

asyncio.run(main())

# Clean up
store.close()
```

### Using the Anthropic SDK directly

If you're not using the Agent SDK, you can integrate segkv with the standard Anthropic API by handling tool calls yourself:

```python
import anthropic
import json
from memory.store import MemoryStore

client = anthropic.Anthropic()
store = MemoryStore(db_path="./agent_memory")

tools = [
    {
        "name": "save_memory",
        "description": "Save information to persistent memory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Unique name for this memory"},
                "type": {
                    "type": "string",
                    "enum": ["user", "feedback", "project", "reference"],
                },
                "description": {"type": "string", "description": "One-line summary"},
                "content": {"type": "string", "description": "Full memory content"},
            },
            "required": ["name", "type", "description", "content"],
        },
    },
    {
        "name": "search_memory",
        "description": "Search memories by keyword.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term"},
            },
            "required": ["query"],
        },
    },
]


def handle_tool_call(name: str, input: dict) -> str:
    if name == "save_memory":
        record = store.set_memory(
            name=input["name"],
            type_=input["type"],
            description=input["description"],
            content=input["content"],
        )
        return json.dumps({"saved": record["name"]})

    if name == "search_memory":
        results = store.search_memories(input["query"])
        return json.dumps(results)

    return json.dumps({"error": f"Unknown tool: {name}"})


def chat(user_message: str, messages: list | None = None) -> str:
    if messages is None:
        messages = []

    messages.append({"role": "user", "content": user_message})

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6-20250514",
            max_tokens=1024,
            system=(
                "You have persistent memory tools. Search memory before tasks. "
                "Save important context for future conversations."
            ),
            tools=tools,
            messages=messages,
        )

        # If no tool use, return the text response
        if response.stop_reason == "end_turn":
            return "".join(
                block.text for block in response.content if block.type == "text"
            )

        # Process tool calls
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = handle_tool_call(block.name, block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                )
        messages.append({"role": "user", "content": tool_results})


# Usage
print(chat("Remember that our API uses GraphQL, not REST."))
print(chat("What technology does our API use?"))

store.close()
```

### Bootstrapping from Claude Code memories

Combine both approaches — import existing Claude Code memories, then let the agent build on them:

```python
from memory.store import MemoryStore
from memory.migrate import import_md_files

store = MemoryStore(db_path="./agent_memory")

# Import existing memories from Claude Code
import_md_files("~/.claude/projects/-Users-me-myproject/memory/", store)

# Now pass `store` to your agent setup (examples above)
# The agent starts with full context from prior Claude Code sessions
```
