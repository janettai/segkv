import threading
import time
import json
import os
from dataclasses import dataclass
from pathlib import Path


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
            compact_threshold: Number of segmenets before compaction
            auto_compact: To auto compact or not
        """

        self.directory = Path(base_dir)
        self.directory.mkdir(parents=True, exist_ok=True)

        self.segment_size = segment_size
        self.compact_threshold = compact_threshold

        self.index: dict[str, IndexEntry] = {}

        # Segment management
        self.segments: list[int] = []  # list of segment ids
        self.active_segment_id: int = 0
        self.active_segment_file = None
        self.active_segment_size: int = 0

        # Compaction
        self.compaction_lock = threading.lock()
        self.compaction_thread = None
        self.auto_compact = auto_compact

        if auto_compact:
            self._start_compaction()

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

                with open(filepath, "r") as f:
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
            self.active_segment_file = open(filepath, "a")
            self.active_segment_size = (
                filepath.stat().st_size if filepath.exists() else 0
            )

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

            # Create record
            record = {"key": key, "value": value, "timestamp": time.time()}

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
            if self._active_segment_size >= self.segment_size:
                self._rotate_segment()

                # Trigger compaction if needed
                if self.auto_compact and len(self.segments) >= self.compact_threshold:
                    self._trigger_compaction()
