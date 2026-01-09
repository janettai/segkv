import json
import os
import threading
import time
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path
from typing import Any


@dataclass
class IndexEntry:
    """Represents an entry in the index"""

    file_id: int  # segment file
    offset: int  # byte offset
    timestamp: float  # time it was written


class LSDB:
    """
    A log-structured storage engine with compaction

    Architecture:

    - Writes go to active segment file
    - When segment reaches max_size, creates a new one
    - Background job periodically compacts old segments
    - In-memory index maps keys to file positions
    """

    def __init__(
        self,
        base_dir: str = "./data",
        segment_size: int = 1024 * 1024,
        auto_compact: bool = True,
        compact_threshold: int = 5,
    ) -> None:
        """
        Init storage engine.

        Args:
            base_dir: Where to store the data
            segment_size: Max size of each segment file (bytes)
            compact_threshold: Number of segments before compaction
            auto_compact: To auto compact or not
        """

        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.segment_size = segment_size
        self.compact_threshold = compact_threshold

        self.index: dict[str, IndexEntry] = {}

        # Segment management
        self.segments: list[int] = []  # list of segment ids
        self.active_segment_id: int = 0
        self.active_segment_file: TextIOWrapper | None = None
        self.active_segment_size: int = 0

        # Thread safety
        self._lock = threading.RLock()  # Protects index and segment state
        self.compaction_lock = threading.Lock()
        self.compaction_thread: threading.Thread | None = None
        self._shutdown_event = threading.Event()
        self.auto_compact = auto_compact
        self._closed = False

        # Load existing data and open active segment
        self._load_existing_segments()
        self._open_active_segment()

        if auto_compact:
            self._start_compaction_thread()

    def _segment_filename(self, segment_id: int) -> Path:
        """Get filename of segment"""
        return self.base_dir / f"segment_{segment_id:06d}.log"

    def _load_existing_segments(self) -> None:
        """Load existing segment files and rebuild index"""
        segment_files = sorted(self.base_dir.glob("segment_*.log"))

        if not segment_files:
            return

        # Extract segment IDs
        for filepath in segment_files:
            segment_id = int(filepath.stem.split("_")[1])
            self.segments.append(segment_id)

        # Set next segment ID
        self.active_segment_id = max(self.segments) + 1 if self.segments else 0

        # Rebuild index from all segments
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        """
        Rebuild the in-memory index by scanning all segment files.
        Called on startup for crash recovery.
        """

        for segment_id in self.segments:
            filepath = self._segment_filename(segment_id)

            with open(filepath) as f:
                offset = 0
                for line in f:
                    if not line.strip():
                        offset = f.tell()
                        continue

                    try:
                        record = json.loads(line)
                        key = record["key"]
                        timestamp = record["timestamp"]

                        # Update index (later entries override earlier ones)

                        self.index[key] = IndexEntry(
                            file_id=segment_id, offset=offset, timestamp=timestamp
                        )

                        offset = f.tell()
                    except (json.JSONDecodeError, KeyError):
                        # Skip corrupted lines
                        offset = f.tell()
                        continue

    def _open_active_segment(self) -> None:
        """Open a new active segment for writing."""
        filepath = self._segment_filename(self.active_segment_id)
        self.active_segment_file = open(filepath, "a")  # noqa: SIM115
        self.active_segment_size = filepath.stat().st_size if filepath.exists() else 0

        if self.active_segment_id not in self.segments:
            self.segments.append(self.active_segment_id)

    def _rotate_segment(self) -> None:
        """Close current segment and open a new one"""
        if self.active_segment_file:
            self.active_segment_file.close()

        self.active_segment_id += 1
        self._open_active_segment()

    def set(self, key: str, value: str) -> None:
        """
        Write a key-value pair.

        Appends a record to the active segment and updates the index.
        If the segment is full, it rotates to a new segment

        Args:
            key: The key to write
            value: The value to write
        """
        with self._lock:
            if self.active_segment_file is None:
                raise RuntimeError("Database not initialized or already closed")

            # Create record
            record: dict[str, Any] = {
                "key": key,
                "value": value,
                "timestamp": time.time(),
            }

            # serialize to JSON
            line = json.dumps(record) + "\n"

            # Get offset before write
            offset = self.active_segment_file.tell()

            # Write to file
            self.active_segment_file.write(line)
            self.active_segment_file.flush()  # Ensure durable
            os.fsync(self.active_segment_file.fileno())  # force to disk

            # Update the index
            self.index[key] = IndexEntry(
                file_id=self.active_segment_id,
                offset=offset,
                timestamp=record["timestamp"],
            )

            # Update segment size
            self.active_segment_size += len(line.encode("utf-8"))

            # Rotate segment if needed
            if self.active_segment_size >= self.segment_size:
                self._rotate_segment()

                # Trigger compaction if needed
                if self.auto_compact and len(self.segments) >= self.compact_threshold:
                    self._trigger_compaction()

    def get(self, key: str) -> str | None:
        """
        Read a value by key.

        This uses hash index for O(1) lookup, then seeks to the
        file position to read the value.

        Args:
            key: The key to read

        Returns:
            The value or None if not found or deleted
        """
        with self._lock:
            if key not in self.index:
                return None

            entry = self.index[key]
            filepath = self._segment_filename(entry.file_id)

        # File read outside lock to reduce contention
        try:
            with open(filepath) as f:
                f.seek(entry.offset)
                line = f.readline()

            record = json.loads(line)
            value = record["value"]
            return value if value else None
        except (json.JSONDecodeError, KeyError, FileNotFoundError):
            return None

    def delete(self, key: str) -> None:
        """
        Delete a key by writing a tombstone


        No need to remove key from index or file.
        Just write an empty value that is removed during compaction.

        """

        self.set(key, "")

    def compact(self) -> None:
        """
        Compact all segments by merging them and removing deleted/old entries.

        Algorithm:
        1. Collect all live key-value pairs from all segments
        2. Write them to new segment files
        3. Atomically replace old segments with new ones
        4. Rebuild the index
        """
        with self.compaction_lock:
            # Snapshot current state under lock
            with self._lock:
                if not self.segments:
                    return
                index_snapshot = dict(self.index)
                segments_snapshot = self.segments.copy()

            print(f"Starting compaction of {len(segments_snapshot)} segments...")
            start_time = time.time()

            # Collect all live entries (most recent value for each key)
            live_data: dict[str, tuple[str, float]] = {}

            for key, entry in index_snapshot.items():
                filepath = self._segment_filename(entry.file_id)

                try:
                    with open(filepath) as f:
                        f.seek(entry.offset)
                        line = f.readline()

                    record = json.loads(line)
                    value = record["value"]
                    timestamp = record["timestamp"]

                    # Skip tombstones (deleted keys)
                    if value:
                        live_data[key] = (value, timestamp)
                except (json.JSONDecodeError, KeyError, FileNotFoundError):
                    continue

            # Write to new compacted segment
            compacted_id = max(segments_snapshot) + 1
            compacted_path = self._segment_filename(compacted_id)
            new_index: dict[str, IndexEntry] = {}

            with open(compacted_path, "w") as f:
                for key, (value, timestamp) in sorted(live_data.items()):
                    offset = f.tell()

                    record = {
                        "key": key,
                        "value": value,
                        "timestamp": timestamp,
                    }
                    line = json.dumps(record) + "\n"
                    f.write(line)

                    new_index[key] = IndexEntry(
                        file_id=compacted_id, offset=offset, timestamp=timestamp
                    )

            # Atomically update state under lock
            with self._lock:
                # Close active segment
                if self.active_segment_file:
                    self.active_segment_file.close()

                # Remove old segments
                for segment_id in segments_snapshot:
                    filepath = self._segment_filename(segment_id)
                    if filepath.exists():
                        filepath.unlink()

                # Update state
                self.segments = [compacted_id]
                self.index = new_index
                self.active_segment_id = compacted_id + 1
                self._open_active_segment()

            elapsed_time = time.time() - start_time
            print(f"Compaction completed in {elapsed_time:.2f}s")
            print(f"Reduced to 1 segment with {len(live_data)} live keys")

    def _trigger_compaction(self) -> None:
        """Trigger compaction in background thread."""
        if self.compaction_thread and self.compaction_thread.is_alive():
            return  # Already compacting

        self.compaction_thread = threading.Thread(target=self.compact)
        self.compaction_thread.start()

    def _start_compaction_thread(self) -> None:
        """Start background compaction thread."""

        def compact_periodically() -> None:
            while not self._shutdown_event.is_set():
                # Wait with timeout so we can check shutdown event
                if self._shutdown_event.wait(timeout=10):
                    break  # Shutdown requested
                if self.auto_compact and len(self.segments) >= self.compact_threshold:
                    self.compact()

        self._periodic_compaction_thread = threading.Thread(
            target=compact_periodically, daemon=True
        )
        self._periodic_compaction_thread.start()

    def keys(self) -> list[str]:
        """Return all keys in the index."""
        with self._lock:
            return list(self.index.keys())

    def stats(self) -> dict[str, Any]:
        """Return statistics about the database."""
        with self._lock:
            segments_copy = self.segments.copy()
            num_keys = len(self.index)
            active_size = self.active_segment_size

        total_size = sum(
            self._segment_filename(sid).stat().st_size
            for sid in segments_copy
            if self._segment_filename(sid).exists()
        )

        return {
            "num_segments": len(segments_copy),
            "num_keys": num_keys,
            "total_size_bytes": total_size,
            "active_segment_size": active_size,
        }

    def close(self) -> None:
        """Close the database gracefully."""
        if self._closed:
            return

        with self._lock:
            self._closed = True
            self.auto_compact = False

            # Signal shutdown to background threads
            self._shutdown_event.set()

            # Close active segment file
            if self.active_segment_file:
                self.active_segment_file.close()
                self.active_segment_file = None

        # Wait for any running compaction to finish
        if self.compaction_thread and self.compaction_thread.is_alive():
            self.compaction_thread.join(timeout=5)


if __name__ == "__main__":
    # Demo usage
    print("Log-Structured Storage Engine Demo\n")

    # Create database
    db = LSDB(base_dir="./demo_data", segment_size=1024)

    # Write some data
    print("Writing data...")
    for i in range(100):
        db.set(f"user:{i}", f'{{"name": "User{i}", "age": {20 + i}}}')

    # Read some data
    print("\nReading data...")
    print(f"user:0 = {db.get('user:0')}")
    print(f"user:50 = {db.get('user:50')}")

    # Update a key
    print("\nUpdating user:0...")
    db.set("user:0", '{"name": "Alice", "age": 30}')
    print(f"user:0 = {db.get('user:0')}")

    # Delete a key
    print("\nDeleting user:50...")
    db.delete("user:50")
    print(f"user:50 = {db.get('user:50')}")

    # Show stats
    print("\nDatabase stats:")
    for key, value in db.stats().items():
        print(f"  {key}: {value}")

    # Compact
    print("\nTriggering compaction...")
    db.compact()

    print("\nStats after compaction:")
    for key, value in db.stats().items():
        print(f"  {key}: {value}")

    db.close()
