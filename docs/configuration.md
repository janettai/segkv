# Configuration

## LSDB parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `base_dir` | `str` | `"./data"` | Directory for segment files |
| `segment_size` | `int` | `1048576` (1 MB) | Max segment file size in bytes |
| `auto_compact` | `bool` | `True` | Enable background compaction |
| `compact_threshold` | `int` | `5` | Segment count that triggers compaction |

## Segment size trade-offs

| Smaller segments | Larger segments |
|-----------------|-----------------|
| More frequent rotation | Fewer files on disk |
| More compaction runs | Less compaction overhead |
| Faster crash recovery (less to replay) | Slower recovery (more data per file) |
| Higher I/O overhead from many small files | Better sequential I/O |

**Recommendation:** Start with the 1 MB default. Decrease to 64-256 KB for workloads with frequent updates and where fast recovery matters. Increase to 4-16 MB for write-heavy workloads with mostly unique keys.

## Compaction threshold

The `compact_threshold` controls how many segments accumulate before automatic compaction kicks in.

| Lower threshold (e.g., 3) | Higher threshold (e.g., 10) |
|---------------------------|----------------------------|
| Compacts more often | Compacts less often |
| Less disk space used | More disk space used |
| More CPU time spent compacting | Less CPU overhead |
| Fewer segments to scan on recovery | More segments to scan on recovery |

## Auto-compact vs. manual compact

**Auto-compact (`auto_compact=True`)** — a background thread checks every 10 seconds whether the segment count has reached `compact_threshold`. Best for long-running applications where you want hands-off maintenance.

**Manual compact (`auto_compact=False`)** — you call `db.compact()` when convenient. Best for batch jobs, scripts, or when you need precise control over when I/O-intensive compaction happens.

```python
# Manual compaction after a batch import
db = LSDB(base_dir="./data", auto_compact=False)
for key, value in batch:
    db.set(key, value)
db.compact()
db.close()
```

## MemoryStore defaults

`MemoryStore` creates an LSDB instance with:

- `segment_size=65536` (64 KB) — appropriate for small, structured records
- `auto_compact=False` — compact manually or via the CLI `compact` command
