"""Prototype: a MemoryStore that keeps records in memory for O(1)-scan search.

The stock `MemoryStore.search_memories` / `list_memories` iterate every key and
re-read each record from disk (one file open + seek + readline + JSON parse per
record), making them O(N) in *disk seeks*. For a large corpus that is the dominant
cost.

`CachedMemoryStore` keeps a parsed `name -> record` dict in memory. Search and list
become an in-memory scan with no disk I/O. The trade-offs, made explicit so the
benchmark can measure them:

  * Startup loads every record once to build the cache, so cold start costs more
    than the stock store (which only rebuilds the on-disk-offset index).
  * The cache roughly doubles resident memory (records are held both as the LSDB
    value bytes are NOT retained — only the parsed dicts are kept here).

Durability is unchanged: every write still goes through LSDB (append + fsync). The
cache is a read-side accelerator rebuilt from disk on open, so a crash loses nothing.
"""

from __future__ import annotations

import json
from typing import Any

from memory.store import _KEY_PREFIX, MemoryStore


class CachedMemoryStore(MemoryStore):
    def __init__(self, db_path: str = "./memory_data") -> None:
        super().__init__(db_path=db_path)
        self._records: dict[str, dict[str, Any]] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        for key in self._db.keys():  # noqa: SIM118
            if not key.startswith(_KEY_PREFIX):
                continue
            raw = self._db.get(key)
            if raw is None:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            name = record.get("name")
            if isinstance(name, str):
                self._records[name] = record

    def set_memory(
        self, name: str, type_: str, description: str, content: str
    ) -> dict[str, Any]:
        record = super().set_memory(name, type_, description, content)
        self._records[name] = record
        return record

    def delete_memory(self, name: str) -> bool:
        deleted = super().delete_memory(name)
        if deleted:
            self._records.pop(name, None)
        return deleted

    def list_memories(self, type_filter: str | None = None) -> list[dict[str, Any]]:
        results = [
            r
            for r in self._records.values()
            if type_filter is None or r.get("type") == type_filter
        ]
        return sorted(results, key=lambda r: r.get("name", ""))

    def search_memories(self, query: str) -> list[dict[str, Any]]:
        q = query.lower()
        results: list[dict[str, Any]] = []
        for r in self._records.values():
            haystack = " ".join(
                [r.get("name", ""), r.get("description", ""), r.get("content", "")]
            ).lower()
            if q in haystack:
                results.append(r)
        return sorted(results, key=lambda r: r.get("name", ""))
