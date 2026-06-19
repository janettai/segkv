# Design & Internals

This page is the system-level view of segkv: what it is, the technology it is built
on, how the pieces fit together, and why it is shaped the way it is for use as the
**memory substrate of an AI harness**. For the low-level mechanics of the storage
engine itself — segment format, write/read paths, compaction algorithm, locking —
see [Architecture](architecture.md), which this page references rather than repeats.

## What segkv is

segkv is two things stacked on top of each other:

1. **A storage engine** (`LSDB`) — a small, dependency-free, log-structured
   key-value store for Python. Append-only writes, an in-memory hash index, segment
   rotation, background compaction, crash recovery.
2. **A memory layer** (`MemoryStore` and friends) — a typed record model, a CLI, and
   a [Model Context Protocol](https://modelcontextprotocol.io) server that turn the
   engine into **persistent memory for Claude Code and AI agents**.

The first half is a general-purpose database. The second half is what makes the
project interesting: it is a concrete answer to "where does an AI assistant keep
what it learns?"

## The layered architecture

```
        ┌──────────────────────────────────────────────────────────┐
        │                     Access surfaces                        │
        │                                                            │
        │   MCP server        memory CLI        custom agents        │
        │ (examples/          (memory_cli.py)   (Agent SDK /         │
        │  mcp_server.py)                        Anthropic SDK)       │
        └───────┬───────────────────┬───────────────────┬───────────┘
                │                   │                   │
                └───────────────────┼───────────────────┘
                                    ▼
        ┌──────────────────────────────────────────────────────────┐
        │  MemoryStore (memory/store.py)                             │
        │  typed JSON records · mem: key prefix · search / list      │
        │  migrate (memory/migrate.py): import Claude Code .md files  │
        └───────────────────────────┬──────────────────────────────┘
                                    ▼
        ┌──────────────────────────────────────────────────────────┐
        │  LSDB (segkv/core.py)                                      │
        │  append-only segments · hash index · compaction · recovery │
        └───────────────────────────┬──────────────────────────────┘
                                    ▼
                            segment_*.log on disk
```

Each layer is a thin, well-defined boundary:

- **`LSDB`** knows only about opaque `str` keys and values. It has no idea what a
  "memory" is.
- **`MemoryStore`** gives meaning to those bytes: it namespaces keys with a `mem:`
  prefix and serializes a typed record into the value. It is the only layer that
  knows the record schema.
- **The access surfaces** are interchangeable front-ends over the *same*
  `MemoryStore` API. The CLI, the MCP server, and an agent all call `set_memory` /
  `search_memories` / etc. — they differ only in *who* is driving (a human shell, the
  MCP protocol, or a model's tool calls).

This separation is why a memory written by the CLI is visible to the MCP server and
vice versa: they are different doors into one room.

## The technology behind it

### Log-structured storage (the Bitcask lineage)

The engine is a **log-structured** store in the Bitcask tradition: an append-only log
of records plus an in-memory hash index that maps every key to the byte offset of its
most recent record.

```
write  →  append {key, value, timestamp}\n to active segment, fsync
          index[key] = (file_id, offset, timestamp)

read   →  entry = index[key]            (O(1), in memory)
          seek(entry.offset) in segment, read one line, parse value
```

The design choices and their rationale:

| Choice | Why |
|--------|-----|
| **Append-only** | Sequential writes are fast and crash-friendly; an interrupted write can only leave a trailing partial line, which recovery skips. |
| **In-memory hash index** | Point reads are O(1) and never touch disk for the lookup. The cost: the entire keyspace must fit in RAM. |
| **Immutable segments** | Old segments are never mutated, only superseded; this makes compaction a safe copy-then-swap. |
| **JSON-line records** | Human-readable, trivially debuggable, no schema migrations. The cost: parsing and size overhead vs. a binary format. |
| **`fsync` per write** | Durability — a returned `set()` is on disk. The cost: writes are I/O-bound (~tens of thousands/sec, not millions). |
| **Tombstones for deletes** | Deletes are just writes of an empty value; the key is dropped from the index immediately and the dead record is reclaimed at compaction. |
| **Compaction** | Reclaims space from overwritten/deleted keys by rewriting only live data into one fresh segment. Runs inline after rotation and via a background daemon. |
| **Pure standard library** | The core has zero runtime dependencies — just `json`, `os`, `threading`, `fcntl`. Easy to vendor, audit, and trust. |

The full mechanics — segment rotation, the compaction copy-and-swap, index rebuild on
startup, and the concurrency model — are documented in
[Architecture](architecture.md).

### Concurrency and the single-owner model

There are two layers of locking:

- **In-process:** an `RLock` guards the index and segment state; a separate lock
  serializes compaction. Threads sharing one `LSDB` are safe.
- **Cross-process:** because the index lives in each process's memory, two processes
  writing the same directory cannot stay consistent. `LSDB` takes an exclusive
  `fcntl` advisory lock on open and raises `DatabaseLockedError` if another process
  already holds it. A database therefore has **one owning process at a time**.

This is the single most important constraint for the AI-harness use case, discussed
below and in [Performance](performance.md#concurrency-and-cross-process-access).

### The memory record model

`MemoryStore` stores one JSON object per key under a `mem:` prefix:

```json
{
  "name": "api-redesign",
  "type": "project",
  "description": "API redesign notes",
  "content": "Switching from REST to GraphQL in Q2.",
  "created_at": 1704825600.0,
  "updated_at": 1704825600.0
}
```

The four **types** — `user`, `feedback`, `project`, `reference` — are not arbitrary.
They mirror the way an AI harness already reasons about what it remembers: facts about
the *user*, *feedback* on how to work, ongoing *project* context, and *references* to
external resources. This shared vocabulary is what lets segkv ingest a harness's
native memory files directly (see migration, below).

`set_memory` preserves `created_at` across updates, so a record carries its own small
history of "first seen" vs. "last touched." Search and list are deliberately simple:
a case-insensitive substring scan over name/description/content. That is O(N) and
disk-bound at scale — a known trade-off covered in [Performance](performance.md).

## How it sits at the AI-harness intersection

An **AI harness** is the runtime wrapped around a language model — Claude Code, an
agent framework, an MCP client. The harness manages the context window, the available
tools, and the session lifecycle. The model itself is **stateless**: everything it
"knows" in a turn comes from the context it was handed, and when the session ends,
that context is gone.

That creates the **memory problem**: how does an assistant remember something from
last week's session? The context window is finite and per-session; it cannot be the
home for durable knowledge. The answer is *external* memory — a store that lives
outside any single conversation and that the model can write to and read from. segkv
is built to be exactly that store.

### Why a log-structured KV store fits AI memory

The access pattern of "assistant memory" maps cleanly onto this engine:

- **Facts accumulate** → append-only writes are the natural shape.
- **Recall by name is the hot path** → O(1) point reads.
- **Losing a memory is bad** → `fsync` durability matters more than raw throughput.
- **Facts get revised** ("actually, the user moved to Berlin") → updates are just new
  appends; compaction cleans up the old versions.
- **The corpus is large-but-bounded** → it fits in an in-memory index; you are not
  storing billions of rows, you are storing a knowledge base.

### Two integration shapes

segkv plugs into a harness in two ways, differing in *who decides* when to remember:

**1. Model-driven, via MCP.** The [MCP server](mcp-server.md) exposes five tools —
`save_memory`, `recall_memory`, `search_memories`, `list_memories`, `delete_memory` —
over stdio JSON-RPC. The harness (Claude Code) launches the server as a subprocess;
the *model* decides, mid-conversation, when to call them.

```
   Claude Code (harness)                  segkv MCP server            disk
   ─────────────────────                  ────────────────            ────
   model emits tool_use  ──JSON-RPC──▶   _dispatch()
     save_memory(...)                       └─ MemoryStore.set_memory ──▶ LSDB ──▶ fsync
   tool_result  ◀──JSON-RPC──             {record}
   ...next session...
   model emits tool_use  ──JSON-RPC──▶   _dispatch()
     search_memories(q)                     └─ MemoryStore.search ────── reads ◀── disk
   tool_result  ◀──JSON-RPC──             {count, results}
```

This is the "give the model a memory and let it manage it" pattern. The model writes
what it judges worth keeping and searches before answering when prior context might
help.

**2. Programmatic, for custom agents.** When you build your own agent (Agent SDK or
the raw Anthropic SDK — see [Claude Integration](claude-integration.md) and
`examples/tool_agent.py`), you wrap the same `MemoryStore` methods as tools and run
the agentic loop yourself. segkv is just the persistence layer.

### Model-driven memory vs. harness-driven memory

Claude Code already has a *native* memory system: per-project markdown files with an
index (`MEMORY.md`) that is **auto-loaded into context** at session start. segkv via
MCP is a different point on the spectrum:

| | Native (harness-driven) | segkv via MCP (model-driven) |
|---|---|---|
| When recalled | Index auto-loaded into context every session | Model calls `search`/`recall` on demand |
| Context cost | Pays tokens up front for the index | Pays a tool round-trip only when used |
| Scope | Per project | One shared store across tools/projects |
| Backing | One file per fact | Single compacted log + in-memory index |
| Best at | Small, always-relevant fact sets | Large corpora; programmatic/multi-tool access |

Neither is strictly better — they trade context tokens against tool round-trips. The
[`import-md`](cli.md#import-md) migration path exists precisely so the two can
coexist: you can lift a harness's native `.md` memories into segkv to unify, back up,
search, and compact them (`memory/migrate.py` parses the frontmatter and skips
`MEMORY.md`).

### The shared-substrate goal, and its constraint

The reason to choose segkv over the native system is **unification**: one durable
corpus that the MCP server, the CLI, and bespoke agents all read and write — across
projects, not siloed per project.

The cross-process single-owner rule is the hard edge of that goal. The in-memory
index is per-process, so the safe topology is **one long-lived owner** (the MCP
server is the natural candidate) with everything else routed through it, or **separate
databases merged offline**. The advisory lock turns the unsafe case (two writers) into
a loud `DatabaseLockedError` instead of silent corruption. The recommended patterns
are spelled out in
[Performance — cross-process access](performance.md#concurrency-and-cross-process-access).

## Design trade-offs, honestly

- **Search is substring, not semantic.** There are no embeddings or vector index;
  `search_memories` does a literal case-insensitive scan. It will not find "Berlin"
  when you query "Germany." Semantic recall would be the highest-impact future
  addition.
- **Search/list are O(N) and disk-bound.** Each scanned record is re-read from disk.
  The `examples/cached_memory_store.py` prototype keeps records in memory for ~40×
  faster search at the cost of slower startup — see [Performance](performance.md).
- **One writer per database.** True concurrent multi-process sharing would require a
  client/server front-end or shared-memory index; today it is single-owner by design.
- **In-memory index bounds the keyspace.** Every key lives in RAM. Fine for a
  knowledge base, wrong for billions of rows — but that is not the target.

These are deliberate: the project optimizes for a *trustworthy, simple, dependency-free
memory store for an AI assistant*, not for a general-purpose distributed database.

## See also

- [Architecture](architecture.md) — engine internals (segments, compaction, recovery)
- [MCP Server](mcp-server.md) — the model-driven integration
- [Claude Integration](claude-integration.md) — programmatic agent integration
- [Performance](performance.md) — scaling, concurrency, and the cross-process model
- [LSDB API](api/lsdb.md) · [MemoryStore API](api/memory-store.md)
