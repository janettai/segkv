import tempfile
import threading
import time
from unittest.mock import patch

import pytest

from segkv import LSDB


@pytest.fixture
def db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with LSDB(base_dir=tmpdir, segment_size=1024, auto_compact=False) as db:
            yield db


class TestBasicOperations:
    """Test basic CRUD operations."""

    def test_set_and_get(self, db):
        db.set("key1", "value1")
        assert db.get("key1") == "value1"

    def test_get_nonexistent_key(self, db):
        assert db.get("nonexistent") is None

    def test_update_key(self, db):
        db.set("key1", "value1")
        db.set("key1", "value2")
        assert db.get("key1") == "value2"

    def test_delete_key(self, db):
        db.set("key1", "value1")
        db.delete("key1")
        assert db.get("key1") is None

    def test_multiple_keys(self, db):
        db.set("key1", "value1")
        db.set("key2", "value2")
        db.set("key3", "value3")

        assert db.get("key1") == "value1"
        assert db.get("key2") == "value2"
        assert db.get("key3") == "value3"

    def test_get_falsy_values(self, db):
        """C1: Falsy string values like '0', 'false', '[]' must not be treated as None."""
        db.set("zero", "0")
        db.set("false", "false")
        db.set("empty_list", "[]")
        db.set("deleted", "")

        assert db.get("zero") == "0"
        assert db.get("false") == "false"
        assert db.get("empty_list") == "[]"
        assert db.get("deleted") is None


class TestKeys:
    """Test keys() method."""

    def test_keys_empty(self, db):
        assert db.keys() == []

    def test_keys_returns_all(self, db):
        db.set("a", "1")
        db.set("b", "2")
        db.set("c", "3")

        keys = db.keys()
        assert sorted(keys) == ["a", "b", "c"]


class TestStats:
    """Test stats() method."""

    def test_stats_empty(self, db):
        stats = db.stats()
        assert stats["num_keys"] == 0
        assert stats["num_segments"] == 1

    def test_stats_with_data(self, db):
        db.set("key1", "value1")
        db.set("key2", "value2")

        stats = db.stats()
        assert stats["num_keys"] == 2
        assert stats["total_size_bytes"] > 0


class TestSegmentRotation:
    """Test segment rotation when size limit is reached."""

    def test_segment_rotation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Use tiny segment size to trigger rotation
            with LSDB(base_dir=tmpdir, segment_size=100, auto_compact=False) as db:
                # Write enough data to trigger rotation
                for i in range(10):
                    db.set(f"key{i}", f"value{i}" * 10)

                # Should have multiple segments
                assert len(db.segments) > 1

                # Data should still be retrievable
                assert db.get("key0") == "value0" * 10
                assert db.get("key9") == "value9" * 10


class TestCompaction:
    """Test compaction functionality."""

    def test_compact_removes_deleted_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with LSDB(base_dir=tmpdir, segment_size=100, auto_compact=False) as db:
                # Write and delete some keys
                for i in range(5):
                    db.set(f"key{i}", f"value{i}")

                db.delete("key2")
                db.delete("key4")

                db.compact()

                # Deleted keys should be gone
                assert db.get("key2") is None
                assert db.get("key4") is None

                # Other keys should remain
                assert db.get("key0") == "value0"
                assert db.get("key1") == "value1"
                assert db.get("key3") == "value3"

    def test_compact_keeps_latest_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with LSDB(base_dir=tmpdir, segment_size=100, auto_compact=False) as db:
                # Update same key multiple times
                db.set("key1", "old")
                db.set("key1", "newer")
                db.set("key1", "newest")

                db.compact()

                assert db.get("key1") == "newest"

    def test_compact_preserves_falsy_values(self):
        """C1: Compaction must not discard falsy values like '0'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with LSDB(base_dir=tmpdir, segment_size=100, auto_compact=False) as db:
                db.set("zero", "0")
                db.set("false", "false")
                db.set("deleted", "")

                db.compact()

                assert db.get("zero") == "0"
                assert db.get("false") == "false"
                assert db.get("deleted") is None

    def test_concurrent_write_during_compaction(self):
        """C2: New keys, updates, and deletes during compaction must not be lost.

        Injects a pause between _collect_live_data and the final merge so
        that concurrent writes land after the snapshot but before the swap.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            with LSDB(base_dir=tmpdir, segment_size=100, auto_compact=False) as db:
                # Write initial data across multiple segments
                for i in range(20):
                    db.set(f"key{i}", f"value{i}")

                # key to be updated and key to be deleted during compaction
                db.set("will_update", "old")
                db.set("will_delete", "exists")

                barrier = threading.Barrier(2, timeout=5)
                original_collect = db._collect_live_data

                def slow_collect(index_snapshot):
                    """Pause after collecting so the main thread can write."""
                    result = original_collect(index_snapshot)
                    barrier.wait()  # signal main thread to start writing
                    time.sleep(0.2)  # give writes time to land
                    return result

                def run_compact():
                    with patch.object(db, "_collect_live_data", slow_collect):
                        db.compact()

                compact_thread = threading.Thread(target=run_compact)
                compact_thread.start()

                # Wait until snapshot is taken and collection is done
                barrier.wait()

                # Write new keys, update existing, delete existing
                db.set("new_key", "new_val")
                db.set("will_update", "new")
                db.delete("will_delete")

                compact_thread.join(timeout=10)

                # New key must exist
                assert db.get("new_key") == "new_val"
                # Updated key must reflect the post-snapshot value
                assert db.get("will_update") == "new"
                # Deleted key must stay deleted (not resurrected)
                assert db.get("will_delete") is None
                # Original data should still be accessible
                assert db.get("key0") == "value0"


class TestPersistence:
    """Test data persistence across database restarts."""

    def test_data_persists_after_restart(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write data
            with LSDB(base_dir=tmpdir, auto_compact=False) as db1:
                db1.set("persistent", "data")

            # Reopen and verify
            with LSDB(base_dir=tmpdir, auto_compact=False) as db2:
                assert db2.get("persistent") == "data"

    def test_offsets_correct_after_restart(self):
        """C3: Offsets must be correct even after restarting the database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with LSDB(base_dir=tmpdir, auto_compact=False) as db1:
                db1.set("a", "alpha")
                db1.set("b", "bravo")
                db1.set("c", "charlie")

            with LSDB(base_dir=tmpdir, auto_compact=False) as db2:
                assert db2.get("a") == "alpha"
                assert db2.get("b") == "bravo"
                assert db2.get("c") == "charlie"
