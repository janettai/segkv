# MCP Server

segkv ships a ready-to-run [Model Context Protocol](https://modelcontextprotocol.io)
server that exposes the [MemoryStore](api/memory-store.md) as a set of tools any MCP
client — most notably **Claude Code** — can call. Once registered, Claude gains five
persistent memory tools that survive across conversations, because every memory is
written to a segkv log-structured database on disk.

**Source:** `examples/mcp_server.py`

## How it works

```
┌──────────────┐   stdio   ┌──────────────────┐        ┌──────────────┐
│  Claude Code  │◀────────▶│  mcp_server.py   │───────▶│  MemoryStore │──▶ segkv DB
│  (MCP client) │  JSON-RPC │  (MCP server)    │        │  (memory/)   │   on disk
└──────────────┘           └──────────────────┘        └──────────────┘
```

The server speaks MCP over **stdio**: the client launches it as a subprocess and
exchanges JSON-RPC messages on stdin/stdout. On startup it opens a single
`MemoryStore` (which in turn opens an `LSDB` instance) and serves tool calls until
the client disconnects, at which point the store is closed cleanly.

The database path defaults to `~/.claude/memory.db` — **the same path used by the
[`memory` CLI](cli.md)** — so the CLI and Claude Code read and write the same
memories.

## Setup

### Project-scoped (this repository only)

A `.mcp.json` file in the repository root registers the server for anyone who opens
the project in Claude Code:

```json
{
  "mcpServers": {
    "segkv-memory": {
      "command": "uv",
      "args": ["run", "python", "examples/mcp_server.py"]
    }
  }
}
```

Claude Code launches the server automatically the next time the project is opened.

### User-wide (all projects)

To make the memory tools available everywhere, add the server to
`~/.claude/settings.json`. Because the working directory varies between projects,
pass an absolute `--directory` so `uv` can find the project:

```json
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
```

Restart Claude Code after editing settings.

### Choosing the database path

The default is `~/.claude/memory.db`. Override it either with a CLI flag or an
environment variable:

```json
"args": ["run", "python", "examples/mcp_server.py", "--db-path", "/custom/path/memory.db"]
```

```json
"env": { "SEGKV_DB_PATH": "/custom/path/memory.db" }
```

The flag takes precedence over the environment variable, which takes precedence over
the default. The parent directory is created automatically if it does not exist.

## Tools

Once registered, the following tools appear in Claude Code as
`mcp__segkv-memory__<tool>`:

| Tool | Signature | Description |
|------|-----------|-------------|
| `save_memory` | `(name, type, description, content)` | Create or update a memory. Re-saving an existing `name` updates it and **preserves the original `created_at`**. |
| `recall_memory` | `(name)` | Fetch one memory by its exact slug. Returns an `error` field if not found. |
| `search_memories` | `(query)` | Case-insensitive substring search across name, description, and content. Returns `{count, results}`. |
| `list_memories` | `(type_filter?)` | List all memories, optionally filtered by type. Returns `{count, memories}`. |
| `delete_memory` | `(name)` | Permanently delete a memory. Returns `{deleted: bool}`. |

The `type` field must be one of `user`, `feedback`, `project`, or `reference` — see
[MemoryStore](api/memory-store.md#valid-types) for the meaning of each. An invalid
type is returned to the client as an `{"error": ...}` payload rather than crashing
the server.

Every tool result is returned as a single JSON `TextContent` block.

## Verifying the server

You can run the server by hand to confirm it starts (it will wait for JSON-RPC input
on stdin — press `Ctrl-C` to exit):

```bash
uv run python examples/mcp_server.py --help     # show options
uv run python examples/mcp_server.py            # start the stdio server
```

To check that memories written through the tools are visible elsewhere, write one
with the CLI and confirm Claude Code can recall it (or vice versa) — both point at
`~/.claude/memory.db` by default:

```bash
uv run python memory_cli.py set hello \
  --type reference --description "smoke test" --content "it works"
uv run python memory_cli.py get hello
```

## Relationship to the other integrations

This server is the **drop-in** integration: no code required, works with any MCP
client. If you are building your own agent instead of using Claude Code, see
[Claude Integration](claude-integration.md) for wiring `MemoryStore` into the Claude
Agent SDK or the raw Anthropic SDK (the `examples/tool_agent.py` script is a complete
runnable example of the latter).
