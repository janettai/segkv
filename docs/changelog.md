# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **`memory` package** — a typed record adapter (`MemoryStore`) over `LSDB` that
  stores named, typed memory records (`user` / `feedback` / `project` / `reference`)
  as JSON with `created_at` / `updated_at` timestamps, plus `list`, `search`,
  `compact`, and `stats` helpers.
- **Markdown migration utilities** (`memory.migrate`) — `parse_frontmatter` and
  `import_md_files` for bulk-importing Claude Code memory directories (skips
  `MEMORY.md`, falls back to filename/`project`/empty when frontmatter is missing).
- **`memory` CLI** (`memory_cli.py`) — `set`, `get`, `delete`, `list`, `search`,
  `stats`, `compact`, and `import-md` commands over a shared database.
- **MCP server** (`examples/mcp_server.py`) — exposes the store over stdio as five
  Claude Code tools (`save_memory`, `recall_memory`, `search_memories`,
  `list_memories`, `delete_memory`), with `.mcp.json` for project-scoped
  registration and `--db-path` / `SEGKV_DB_PATH` overrides.
- **Tool-augmented agent example** (`examples/tool_agent.py`) — a runnable
  Anthropic-SDK agent that uses segkv as persistent memory.
- **Cross-process safety** — `LSDB` takes an exclusive advisory file lock
  (`<base_dir>/.lock`) on open and raises `DatabaseLockedError` if another process
  already holds the directory, since the in-memory index is per-process. Add a
  `process_lock` constructor flag (default `True`) to opt out. No-op where `fcntl`
  is unavailable.
- Benchmark harness (`examples/benchmark.py`) and an in-memory-search prototype
  (`examples/cached_memory_store.py`).
- Documentation for the memory layer, CLI, MCP server, Claude integration, and
  performance characteristics.
- Ruff and mypy configuration in pyproject.toml
- GitHub Actions CI/CD workflows for linting, type checking, testing, and publishing

### Changed
- Tombstones are now removed from the in-memory index at write time and during index
  rebuild, so `get()` returns `None` and `keys()` excludes deleted keys without a
  per-read empty-value check.

### Fixed
- Crash recovery now stores correct record offsets. `_rebuild_index` captures byte
  offsets with an explicit `f.tell()` / `readline()` loop instead of iterating the
  file object, whose read-ahead buffer reported wrong positions and produced bad
  offsets after a restart. The previously skipped
  `TestPersistence.test_data_persists_after_restart` now passes.

## [0.1.0] - 2025-01-09

### Added
- Initial release of LSDB (Log-Structured Database)
- Core `LSDB` class with key-value storage operations
- Append-only write operations with JSON serialization
- Hash index for O(1) key lookups
- Automatic segment rotation when size threshold is reached
- Background compaction to merge segments and remove deleted entries
- Crash recovery through index rebuilding from segment files
- Thread-safe operations with proper locking mechanisms
- `IndexEntry` dataclass for index management
- Configurable segment size and compaction threshold
- Full type annotations with PEP 561 py.typed marker
- MIT license

[Unreleased]: https://github.com/nanaadjeimanu/lsdb/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nanaadjeimanu/lsdb/releases/tag/v0.1.0
