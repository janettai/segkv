# Architecture

## Overview

segkv is a **log-structured storage engine**. Every write is appended to the end of a log file (called a **segment**), and an in-memory **hash index** maps each key to its location on disk. This design gives durable, sequential writes and O(1) reads.

```
┌──────────┐     ┌─────────────────┐     ┌──────────────────┐
│  Client   │────▶│   Hash Index    │────▶│  Segment Files   │
│           │     │ dict[str, Entry]│     │  (append-only)   │
└──────────┘     └─────────────────┘     └──────────────────┘
```

## Segments

Segment files are the on-disk storage format. Each segment is a sequence of JSON-encoded records, one per line:

```json
{"key": "user:1", "value": "{\"name\": \"Alice\"}", "timestamp": 1704825600.0}
{"key": "user:2", "value": "{\"name\": \"Bob\"}", "timestamp": 1704825601.0}
```

Segments are named sequentially: `segment_000000.log`, `segment_000001.log`, etc.

When the active segment reaches the configured `segment_size` (default 1 MB), it is closed and a new segment is opened. This is called **segment rotation**.

## Hash Index

The index is a Python `dict[str, IndexEntry]` held entirely in memory. Each entry stores:

```python
@dataclass
class IndexEntry:
    file_id: int      # which segment file
    offset: int       # byte offset within the file
    timestamp: float  # when the record was written
```

Because the index is a hash map, key lookups are **O(1)** regardless of how much data is stored.

## Write path

1. Serialize the key, value, and current timestamp as a JSON line
2. Append the line to the active segment file
3. `flush()` and `fsync()` to ensure durability
4. Update the in-memory index with the new file position
5. If the segment exceeds `segment_size`, rotate to a new segment

All writes are performed under a reentrant lock (`threading.RLock`).

## Read path

1. Look up the key in the hash index — **O(1)**
2. Open the segment file and `seek()` to the stored offset
3. Read the JSON line and parse the value

The index lookup is performed under the lock, but the file read happens outside the lock to reduce contention.

## Deletes

Deletes use a **tombstone** approach. Deleting a key writes a record with an empty value (`""`):

```python
def delete(self, key: str) -> None:
    self.set(key, "")
```

On read, an empty value is treated as `None` (not found). Tombstones are cleaned up during compaction.

## Compaction

Over time, segments accumulate stale data — old values for updated keys and tombstones for deleted keys. Compaction reclaims this space.

**Algorithm:**

1. **Snapshot** the current index and segment list under the lock
2. **Collect live data** — for each key in the index, read its current value from disk, skipping tombstones
3. **Write a new segment** containing only the live key-value pairs, sorted by key
4. **Atomic swap** — under the lock, close the active segment, delete old segment files, update the index to point to the new segment, and open a fresh active segment

Compaction runs either:

- **Automatically** — a background thread checks every 10 seconds and compacts when the number of segments reaches `compact_threshold`
- **Manually** — by calling `db.compact()`

Compaction holds a separate `compaction_lock` to prevent concurrent compactions.

## Crash recovery

On startup, `_rebuild_index()` replays **all** segment files from oldest to newest:

1. For each segment, read every JSON line
2. Update the index with each record's key, file position, and timestamp
3. Later records for the same key naturally overwrite earlier ones

Because segments are append-only and flushed with `fsync`, any complete line on disk represents a durable write. Partially written lines (from a crash mid-write) are skipped via `json.JSONDecodeError` handling.

## Thread safety

segkv uses two locks:

| Lock | Type | Protects |
|------|------|----------|
| `_lock` | `threading.RLock` | Index, segment state, active file handle |
| `compaction_lock` | `threading.Lock` | Prevents concurrent compactions |

A `threading.Event` (`_shutdown_event`) signals the background compaction thread to stop during `close()`.
