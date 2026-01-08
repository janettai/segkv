# lsdb

A log-structured storage engine with compaction for Python.

## Installation

```bash
pip install lsdb
```

## Quick Start

```python
from lsdb import LSDB

# Create a database
db = LSDB(base_dir="./data")

# Write data
db.set("user:1", '{"name": "Alice", "age": 30}')

# Read data
value = db.get("user:1")

# Delete data
db.delete("user:1")

# Get statistics
stats = db.stats()

# Close when done
db.close()
```

## Features

- **Append-only writes**: All writes are appended to log files for durability
- **Hash index**: In-memory index for O(1) key lookups
- **Automatic compaction**: Background thread merges segments and removes deleted entries
- **Crash recovery**: Index rebuilt from segments on startup
- **Simple API**: Just `set`, `get`, `delete`, and `close`

## Configuration

```python
db = LSDB(
    base_dir="./data",        # Directory for data files
    segment_size=1024*1024,   # Max segment size in bytes (default: 1MB)
    auto_compact=True,        # Enable automatic compaction
    compact_threshold=5,      # Number of segments before compaction triggers
)
```

## License

MIT
