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
    process_lock: bool = True,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `base_dir` | `str` | `"./data"` | Directory where segment files are stored. Created automatically if it doesn't exist. |
| `segment_size` | `int` | `1048576` (1 MB) | Maximum size in bytes for each segment file before rotation. |
| `auto_compact` | `bool` | `True` | Whether to run background compaction automatically. |
| `compact_threshold` | `int` | `5` | Number of segments that triggers automatic compaction. |
| `process_lock` | `bool` | `True` | Take an exclusive cross-process advisory lock on `base_dir`. See [`DatabaseLockedError`](#databaselockederror). |

On initialization, the engine acquires the process lock, loads existing segments, rebuilds the in-memory index, and (if `auto_compact` is enabled) starts a background compaction thread.

**Raises:** [`DatabaseLockedError`](#databaselockederror) if `process_lock` is enabled and another process already holds `base_dir`.

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

Delete a key by writing a tombstone (empty value). The key is removed from the in-memory index immediately; the tombstone record on disk is discarded during compaction.

```python
db.delete("user:1")
db.get("user:1")  # None
```

---

### `keys()`

```python
def keys(self) -> list[str]
```

Return all keys currently in the index. Deleted keys are excluded — a tombstone removes the key from the index immediately.

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

Gracefully shut down the database. Signals the background compaction thread to stop, waits for any in-progress compaction to finish (up to 5 seconds), closes the active segment file, and releases the cross-process lock.

Safe to call multiple times.

```python
db.close()
```

## DatabaseLockedError

```python
class DatabaseLockedError(RuntimeError): ...
```

Raised by the constructor when `process_lock=True` and another process already holds
the data directory. The in-memory index is per-process, so concurrent writers would
corrupt the data; the lock turns that into a clear error instead. A database has one
owning process at a time — see
[Performance — cross-process access](../performance.md#concurrency-and-cross-process-access)
for the recommended sharing patterns.

```python
from segkv import LSDB, DatabaseLockedError

try:
    db = LSDB(base_dir="./data")
except DatabaseLockedError:
    print("Another process already owns ./data")
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
