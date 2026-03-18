# MemoryStore

A typed record adapter built on top of [LSDB](lsdb.md).

**Source:** `memory/store.py`

## Overview

`MemoryStore` provides structured storage for named memory records with types, descriptions, and timestamps. It serializes records as JSON and stores them in LSDB with a `mem:` key prefix.

### Valid types

| Type | Description |
|------|-------------|
| `user` | Information about the user |
| `feedback` | Guidance on how to approach work |
| `project` | Ongoing work, goals, and context |
| `reference` | Pointers to external resources |

### Record structure

Each memory record contains:

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Unique identifier for the memory |
| `description` | `str` | One-line description |
| `type` | `str` | One of the valid types above |
| `content` | `str` | The memory content |
| `created_at` | `float` | Unix timestamp when first created |
| `updated_at` | `float` | Unix timestamp of last update |

## Constructor

```python
MemoryStore(db_path: str = "./memory_data")
```

Creates a new `MemoryStore` backed by an LSDB instance with 64 KB segments and auto-compaction disabled.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `db_path` | `str` | `"./memory_data"` | Directory for the underlying LSDB database. |

## Methods

### `set_memory(name, type_, description, content)`

```python
def set_memory(self, name: str, type_: str, description: str, content: str) -> dict
```

Create or update a memory record. If the memory already exists, `created_at` is preserved from the original record.

**Raises:** `ValueError` if `type_` is not one of the valid types.

**Returns:** The full record as a dictionary.

```python
record = store.set_memory(
    name="api-redesign",
    type_="project",
    description="Notes on API redesign",
    content="Switching from REST to GraphQL in Q2.",
)
```

---

### `get_memory(name)`

```python
def get_memory(self, name: str) -> dict | None
```

Retrieve a memory record by name. Returns the record as a dictionary, or `None` if not found.

```python
record = store.get_memory("api-redesign")
if record:
    print(record["content"])
```

---

### `delete_memory(name)`

```python
def delete_memory(self, name: str) -> bool
```

Delete a memory record. Returns `True` if the record existed and was deleted, `False` if it was not found.

```python
deleted = store.delete_memory("api-redesign")  # True
```

---

### `list_memories(type_filter=None)`

```python
def list_memories(self, type_filter: str | None = None) -> list[dict]
```

List all memory records, optionally filtered by type. Results are sorted alphabetically by name.

```python
# All memories
all_memories = store.list_memories()

# Only project memories
projects = store.list_memories(type_filter="project")
```

---

### `search_memories(query)`

```python
def search_memories(self, query: str) -> list[dict]
```

Search memories by case-insensitive substring match across `name`, `description`, and `content` fields. Results are sorted by name.

```python
results = store.search_memories("GraphQL")
```

---

### `compact()`

```python
def compact(self) -> None
```

Trigger compaction on the underlying LSDB instance.

---

### `stats()`

```python
def stats(self) -> dict
```

Return statistics from the underlying LSDB instance. See [LSDB.stats()](lsdb.md#stats).

---

### `close()`

```python
def close(self) -> None
```

Close the underlying LSDB instance. Always call this when done.
