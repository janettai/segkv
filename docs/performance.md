# Performance

This page summarises the measured performance characteristics of the
[MemoryStore](api/memory-store.md) for the **shared, large-corpus** use case, and
the guidance that follows from them.

All numbers come from `examples/benchmark.py`, which has three suites — `core`
(per-operation cost vs corpus size), `churn` (compaction reclamation), and
`concurrency` (multi-threaded throughput):

```bash
uv run python examples/benchmark.py --sizes 1000 10000 50000
```

!!! note
    Numbers below are from one developer machine (macOS, APFS) with ~512-byte
    records. Treat them as **shape, not spec** — re-run on your target hardware.
    Absolute values vary; the scaling behaviour is what matters.

## What scales, and what doesn't

| Operation | Cost | Scales with N? |
|-----------|------|----------------|
| `get_memory` (point recall) | hash-index lookup + one seek | **No** — flat ~17–20µs |
| `set_memory` (write) | append + `fsync` | No — ~25k writes/s, fsync-bound |
| `search_memories` | reads **every** record from disk | **Yes** — O(N) |
| `list_memories` | reads every record from disk | **Yes** — O(N) |
| cold start (open) | replays every segment line | **Yes** — O(total records ever written) |
| `compact` | rewrites all live records | Yes (run occasionally) |

The headline: **point reads and writes are cheap and flat; full-corpus `search` and
`list` are linear and become the bottleneck at scale.** Each scanned record is a
separate file open + seek + readline + JSON parse.

## In-memory search: stock vs cached

`examples/cached_memory_store.py` is a prototype `MemoryStore` that keeps parsed
records in memory, turning search/list into an in-memory scan. Measured at
N=50,000:

| Metric | Stock | Cached | Delta |
|--------|------:|-------:|-------|
| search | 882 ms | 21.8 ms | **~40× faster** |
| list | 862 ms | 1.9 ms | **~450× faster** |
| recall p99 | 79 µs | 26 µs | steadier |
| **cold start** | 147 ms | 996 ms | **~7× slower** |
| write throughput | 25.3k/s | 25.6k/s | ~same |

The cache pays its cost once, at startup (it loads every record). So:

- **Long-lived process** (e.g. the [MCP server](mcp-server.md), open for a whole
  Claude Code session with many searches): caching is a clear win.
- **One-shot CLI call** doing a single search: roughly break-even.
- **One-shot CLI call** doing only a point `get`: caching is a net loss — skip it.

The production-grade version of this optimisation is to fold value caching into
`LSDB._rebuild_index`, which already parses every line on startup and discards the
value; retaining it would make search cheap with little extra cold-start cost.

## Churn and compaction

Because writes are append-only, updating the same key repeatedly bloats the log
until compaction runs. Rewriting every key 5× then compacting:

| N | segments before | disk before | after compaction |
|---|----------------:|------------:|-----------------:|
| 1,000 | 59 | 3.7 MB | 749 KB |
| 10,000 | 582 | 36.6 MB | 7.3 MB |
| 50,000 | 2,907 | 183 MB | 36.6 MB |

Compaction reclaims exactly the churn ratio (5.0×). The risk is **segment count**:
an un-compacted, heavily-churned database accumulates thousands of segments, and
cold start replays *all* of them — so startup degrades until compaction runs.

**Guidance:** for a shared corpus that sees ongoing updates, keep compaction
running — either leave the background daemon enabled (`auto_compact=True`, the LSDB
default) or call `compact()` periodically. `MemoryStore` disables auto-compaction by
default, so call `store.compact()` on a schedule for write-heavy workloads.

## Concurrency and cross-process access

Within one process, throughput does **not** improve with more threads — the GIL plus
the write lock serialise work. Measured (N=50,000, single process):

| threads | reads/s | writes/s |
|--------:|--------:|---------:|
| 1 | 52,395 | 40,607 |
| 2 | 41,173 | 39,261 |
| 4 | 29,033 | 32,151 |
| 8 | 25,623 | 30,510 |

Threads buy **safety, not speed**: concurrent access is correct (writes serialise on
`_lock`, reads briefly take it for the index lookup), but adds contention.

!!! warning "Cross-process access is single-owner"
    segkv's locks are in-process, and **the in-memory index is per-process**. Two
    processes writing the same data directory would corrupt it. To prevent this,
    `LSDB` takes an **exclusive advisory file lock** (`<base_dir>/.lock`) on open: a
    second process opening the same directory raises
    [`DatabaseLockedError`](api/lsdb.md) instead of silently corrupting data.

    This means a database has **one owning process at a time**. If the
    [MCP server](mcp-server.md) holds `~/.claude/memory.db` open for a Claude Code
    session, the `memory` CLI pointed at the same path will fail to open until the
    server exits — by design.

### Recommended architecture for sharing

To share one corpus across tools and projects:

- **Single owner** — have one long-lived process own the database (the MCP server is
  a natural choice) and route all access through it. Other tools talk to that
  process, not to the files directly.
- **Separate databases** — if tools must run concurrently, give each its own
  `--db-path` and merge periodically with [`import-md`](cli.md#import-md) or a batch
  job (run while no owner holds the lock).
- **Opt out only when safe** — `LSDB(..., process_lock=False)` disables the guard for
  read-only or known-exclusive scenarios; don't use it to share a writable DB across
  processes.
