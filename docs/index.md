# segkv

A log-structured key-value store for Python.

## Features

- **Append-only writes** — all writes are appended to log files for maximum durability
- **O(1) lookups** — in-memory hash index maps keys directly to file positions
- **Automatic compaction** — background thread merges segments and removes deleted entries
- **Crash recovery** — index is rebuilt from segment files on startup
- **Thread-safe** — safe for concurrent access from multiple threads
- **Simple API** — just `set`, `get`, `delete`, and `close`

## Quick start

```python
from segkv import LSDB

db = LSDB(base_dir="./data")
db.set("user:1", '{"name": "Alice", "age": 30}')
print(db.get("user:1"))
db.close()
```

## Components

segkv ships with three layers:

| Component | Description |
|-----------|-------------|
| [LSDB](api/lsdb.md) | Core log-structured storage engine |
| [MemoryStore](api/memory-store.md) | Typed record adapter for structured memory storage |
| [CLI](cli.md) | Command-line interface for the memory store |

## Requirements

- Python 3.10+
- No external dependencies

## License

MIT — see [LICENSE](https://github.com/janettai/segkv/blob/main/LICENSE) for details.
