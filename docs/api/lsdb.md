# LSDB

::: segkv.core

The core log-structured storage engine.

**Source:** `segkv/core.py`

## Constructor

```python
LSDB(
    base_dir: str = "./data",
    segment_size: int = 1_048_576,
    auto_compact: bool = True,
    compact_threshold: int = 5,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `base_dir` | `str` | `"./data"` | Directory where segment files are stored. Created automatically if it doesn't exist. |
| `segment_size` | `int` | `1048576` (1 MB) | Maximum size in bytes for each segment file before rotation. |
| `auto_compact` | `bool` | `True` | Whether to run background compaction automatically. |
| `compact_threshold` | `int` | `5` | Number of segments that triggers automatic compaction. |

On initialization, the engine loads existing segments, rebuilds the in-memory index, and (if `auto_compact` is enabled) starts a background compaction thread.

## Methods

### `set(key, value)`

```python
def set(self, key: str, value: str) -> None
```

Write a key-value pair. The record is appended to the active segment and the index is updated. If the segment exceeds `segment_size`, it rotates to a new segment.

**Raises:** `RuntimeError` if the database is closed.

```python
db.set("user:1", '{"name": "Alice"}')
```

---

### `get(key)`

```python
def get(self, key: str) -> str | None
```

Read a value by key. Uses the hash index for O(1) lookup, then seeks to the file position.

Returns `None` if the key doesn't exist or has been deleted.

```python
value = db.get("user:1")  # '{"name": "Alice"}' or None
```

---

### `delete(key)`

```python
def delete(self, key: str) -> None
```

Delete a key by writing a tombstone (empty value). The tombstone is removed during compaction.

```python
db.delete("user:1")
db.get("user:1")  # None
```

---

### `keys()`

```python
def keys(self) -> list[str]
```

Return all keys currently in the index. This includes keys with tombstones that haven't been compacted yet.

```python
all_keys = db.keys()  # ["user:1", "user:2", ...]
```

---

### `compact()`

```python
def compact(self) -> None
```

Manually trigger compaction. Merges all segments into a single new segment, removing deleted entries and keeping only the latest value for each key.

This method blocks until compaction is complete.

```python
db.compact()
```

---

### `stats()`

```python
def stats(self) -> dict[str, Any]
```

Return statistics about the database.

**Returns:** A dictionary with:

| Key | Type | Description |
|-----|------|-------------|
| `num_segments` | `int` | Number of segment files |
| `num_keys` | `int` | Number of keys in the index |
| `total_size_bytes` | `int` | Total size of all segment files in bytes |
| `active_segment_size` | `int` | Size of the current active segment in bytes |

```python
stats = db.stats()
# {
#     "num_segments": 3,
#     "num_keys": 150,
#     "total_size_bytes": 24576,
#     "active_segment_size": 8192,
# }
```

---

### `close()`

```python
def close(self) -> None
```

Gracefully shut down the database. Signals the background compaction thread to stop, waits for any in-progress compaction to finish (up to 5 seconds), and closes the active segment file.

Safe to call multiple times.

```python
db.close()
```

## IndexEntry

```python
@dataclass
class IndexEntry:
    file_id: int      # segment file ID
    offset: int       # byte offset within the segment
    timestamp: float  # time the record was written
```

Internal dataclass representing a pointer from the hash index to a record on disk.
