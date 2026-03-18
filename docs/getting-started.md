# Getting Started

## Installation

=== "pip"

    ```bash
    pip install segkv
    ```

=== "uv"

    ```bash
    uv add segkv
    ```

## Development install

```bash
git clone https://github.com/janettai/segkv.git
cd segkv
uv sync
uv run pytest
```

## Your first database

```python
from segkv import LSDB

# Create a database in the ./data directory
db = LSDB(base_dir="./data")

# Write some data
db.set("user:1", '{"name": "Alice", "age": 30}')
db.set("user:2", '{"name": "Bob", "age": 25}')

# Read it back
print(db.get("user:1"))  # '{"name": "Alice", "age": 30}'

# Delete a key
db.delete("user:2")
print(db.get("user:2"))  # None

# Check database stats
print(db.stats())
# {'num_segments': 1, 'num_keys': 1, 'total_size_bytes': 72, 'active_segment_size': 144}

# Always close when done
db.close()
```

## Using MemoryStore

`MemoryStore` is a higher-level adapter that stores typed, structured records on top of LSDB.

```python
from memory.store import MemoryStore

store = MemoryStore(db_path="./my_memories")

# Create a memory record
store.set_memory(
    name="api-redesign",
    type_="project",
    description="Notes on the API redesign initiative",
    content="We're switching from REST to GraphQL in Q2.",
)

# Retrieve it
record = store.get_memory("api-redesign")
print(record["content"])

# Search across all memories
results = store.search_memories("GraphQL")

store.close()
```

## Using the CLI

The `memory` command provides quick access to the memory store from your terminal.

```bash
# Store a memory
memory set api-redesign --type project --description "API redesign notes" --content "Switching to GraphQL"

# Retrieve it
memory get api-redesign

# List all project memories
memory list --type project

# Search
memory search GraphQL
```

See the [CLI Reference](cli.md) for the full list of commands.
