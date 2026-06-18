from __future__ import annotations

import json
import time
from typing import Any

from segkv import LSDB

VALID_TYPES: frozenset[str] = frozenset({"user", "feedback", "project", "reference"})
_KEY_PREFIX = "mem:"


class MemoryStore:
    """Typed record adapter over LSDB for Claude memory storage."""

    def __init__(self, db_path: str = "./memory_data") -> None:
        self._db = LSDB(
            base_dir=db_path,
            segment_size=64 * 1024,
            auto_compact=False,
        )

    def set_memory(
        self, name: str, type_: str, description: str, content: str
    ) -> dict[str, Any]:
        """Create or update a memory record. Preserves created_at on updates."""
        if type_ not in VALID_TYPES:
            raise ValueError(
                f"type_ must be one of {sorted(VALID_TYPES)!r}, got {type_!r}"
            )

        key = _KEY_PREFIX + name
        now = time.time()

        created_at = now
        existing_raw = self._db.get(key)
        if existing_raw is not None:
            try:
                existing = json.loads(existing_raw)
                created_at = existing.get("created_at", now)
            except json.JSONDecodeError:
                pass

        record: dict[str, Any] = {
            "name": name,
            "type": type_,
            "description": description,
            "content": content,
            "created_at": created_at,
            "updated_at": now,
        }
        self._db.set(key, json.dumps(record))
        return record

    def get_memory(self, name: str) -> dict[str, Any] | None:
        """Retrieve a memory record by name, or None if not found."""
        raw = self._db.get(_KEY_PREFIX + name)
        if raw is None:
            return None
        try:
            return json.loads(raw)  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            return None

    def delete_memory(self, name: str) -> bool:
        """Delete a memory record. Returns True if deleted, False if not found."""
        key = _KEY_PREFIX + name
        if self._db.get(key) is None:
            return False
        self._db.delete(key)
        return True

    def list_memories(self, type_filter: str | None = None) -> list[dict[str, Any]]:
        """List all memory records, optionally filtered by type, sorted by name."""
        results: list[dict[str, Any]] = []
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
            if type_filter is not None and record.get("type") != type_filter:
                continue
            results.append(record)
        return sorted(results, key=lambda r: r.get("name", ""))

    def search_memories(self, query: str) -> list[dict[str, Any]]:
        """Search memories by case-insensitive substring across name, description, content."""
        q = query.lower()
        results: list[dict[str, Any]] = []
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
            haystack = " ".join(
                [
                    record.get("name", ""),
                    record.get("description", ""),
                    record.get("content", ""),
                ]
            ).lower()
            if q in haystack:
                results.append(record)
        return sorted(results, key=lambda r: r.get("name", ""))

    def compact(self) -> None:
        """Trigger compaction on the underlying LSDB instance."""
        self._db.compact()

    def stats(self) -> dict[str, Any]:
        """Return statistics from the underlying LSDB instance."""
        return self._db.stats()

    def close(self) -> None:
        """Close the underlying LSDB instance."""
        self._db.close()
