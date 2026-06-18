# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`segkv` (published to PyPI as `segkv`) is a log-structured key-value storage engine for Python. It is a single-module library (`segkv/core.py`) that implements append-only segment files, an in-memory hash index, segment rotation, and background compaction.

The package name in pyproject.toml is `segkv`; the README references `lsdb` (an older name). The public class is `LSDB`, imported from `segkv`.

## Toolchain

This project uses [uv](https://docs.astral.sh/uv/) for dependency management and task running.

```bash
uv sync --dev          # install all dependencies including dev
uv run pytest          # run all tests
uv run pytest tests/test_core.py::TestCompaction::test_compact_removes_deleted_keys  # single test
uv run ruff check .    # lint
uv run ruff format .   # format
uv run mypy segkv      # type check (only the segkv package, not tests)
uv build               # build wheel + sdist
```

## Architecture

All logic lives in `segkv/core.py`. There are two public types:

- **`IndexEntry`** — dataclass holding `file_id`, `offset`, and `timestamp` for a record's location on disk.
- **`LSDB`** — the storage engine.

### Write path
`set()` acquires `_lock`, appends a JSON line to the active segment file (`fsync` on every write), updates `self.index`, and rotates to a new segment file when `active_segment_size >= segment_size`. Delete is a tombstone write (`set(key, "")`).

### Read path
`get()` acquires `_lock` only to look up the `IndexEntry`, then releases it before seeking into the segment file to reduce contention.

### Segment files
Named `segment_NNNNNN.log` under `base_dir`. Each line is a JSON object `{"key", "value", "timestamp"}`. An empty `"value"` is a tombstone.

### Compaction
`compact()` reads the live index snapshot, collects the latest non-tombstone value for every key, writes a single new segment file, then under `_lock` deletes all old segment files and rebuilds `self.index`. Two locks: `_lock` (RLock) guards index and segment state; `compaction_lock` prevents concurrent compaction runs.

Auto-compaction runs two ways: triggered inline after segment rotation (if segment count ≥ `compact_threshold`), and by a periodic daemon thread (checks every 10 s).

### Crash recovery
On startup, `_load_existing_segments` scans `segment_*.log` files in sorted order and calls `_rebuild_index`, which replays every line; later entries overwrite earlier ones in `self.index`.

### Known bug
`TestPersistence.test_data_persists_after_restart` is skipped — `f.tell()` returns unreliable offsets when iterating line-by-line in text mode inside `_rebuild_index`. The offset stored in `IndexEntry` may be wrong after a restart.

## CI

Three workflows in `.github/workflows/`:
- **ci.yml** — lint (ruff), typecheck (mypy), test (pytest on 3.10–3.13), build; runs on push/PR to `main`.
- **docs.yml** — builds and deploys MkDocs to GitHub Pages on pushes that touch `docs/` or `mkdocs.yml`.
- **publish.yml** — publishes to PyPI on GitHub release (uses trusted publishing, no token needed).
