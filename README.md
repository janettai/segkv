# segkv

A log-structured key-value store for Python — plus a persistent **memory layer** for
Claude Code and AI agents, built on top of it.

- **`LSDB`** — an append-only storage engine with an in-memory hash index, segment
  rotation, background compaction, and crash recovery.
- **`MemoryStore`** — a typed record layer over `LSDB` for storing structured
  memories, with a CLI and a drop-in [MCP](https://modelcontextprotocol.io) server
  that gives Claude Code persistent memory across sessions.

📖 **Full documentation:** https://janettai.github.io/segkv/

## Installation

```bash
pip install segkv
# or
uv add segkv
```

Requires Python 3.10+. The core engine has no runtime dependencies.

## Quick start — the storage engine

```python
from segkv import LSDB

db = LSDB(base_dir="./data")

db.set("user:1", '{"name": "Alice", "age": 30}')
print(db.get("user:1"))   # '{"name": "Alice", "age": 30}'

db.delete("user:1")
print(db.get("user:1"))   # None

print(db.stats())
db.close()
```

## Quick start — persistent memory

`MemoryStore` stores typed, named records (`user` / `feedback` / `project` /
`reference`) as JSON, with `created_at` / `updated_at` timestamps and substring search.

```python
from memory import MemoryStore

store = MemoryStore(db_path="~/.claude/memory.db")

store.set_memory(
    name="api-redesign",
    type_="project",
    description="API redesign notes",
    content="Switching from REST to GraphQL in Q2.",
)

for r in store.search_memories("GraphQL"):
    print(r["name"], "—", r["description"])

store.close()
```

The same database is reachable from the command line:

```bash
uv run python memory_cli.py set api-redesign --type project \
  --description "API redesign notes" --content "Switching to GraphQL in Q2"
uv run python memory_cli.py search GraphQL
uv run python memory_cli.py import-md ~/.claude/projects/my-project/memory/
```

## Persistent memory for Claude Code (MCP)

Register the bundled MCP server and Claude Code gains five persistent memory tools
(`save_memory`, `recall_memory`, `search_memories`, `list_memories`,
`delete_memory`) that survive across conversations. A `.mcp.json` in the repo root
wires it up for this project:

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

See the [MCP Server guide](https://janettai.github.io/segkv/mcp-server/) for user-wide
setup and the [Claude Integration guide](https://janettai.github.io/segkv/claude-integration/)
for building your own agents with the Agent SDK or raw Anthropic SDK.

## Features

- **Append-only writes** — every write is appended and `fsync`-ed for durability
- **O(1) lookups** — an in-memory hash index maps keys directly to file offsets
- **Automatic compaction** — a background thread merges segments and drops deleted entries
- **Crash recovery** — the index is rebuilt from segment files on startup
- **Single-owner safety** — an exclusive cross-process lock on the data directory
  raises `DatabaseLockedError` rather than letting two processes corrupt it
- **Memory layer** — typed records, a CLI, and an MCP server for Claude/agent memory

## Configuration

```python
db = LSDB(
    base_dir="./data",        # Directory for data files
    segment_size=1024 * 1024, # Max segment size in bytes before rotation (default: 1MB)
    auto_compact=True,        # Run background compaction automatically
    compact_threshold=5,      # Segment count that triggers compaction
    process_lock=True,        # Exclusive cross-process lock on base_dir
)
```

For performance characteristics (search/cold-start scaling, compaction, and
concurrency guidance for shared corpora), see the
[Performance guide](https://janettai.github.io/segkv/performance/).

## License

MIT — see [LICENSE](LICENSE).
