import tempfile

import pytest

from segkv import LSDB, DatabaseLockedError
from segkv.core import fcntl


@pytest.fixture
def db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = LSDB(base_dir=tmpdir, segment_size=1024, auto_compact=False)
        yield db
        db.close()


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

    def test_keys_excludes_deleted(self, db):
        db.set("a", "1")
        db.set("b", "2")
        db.delete("a")
        keys = db.keys()
        assert "a" not in keys
        assert "b" in keys


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
            db = LSDB(base_dir=tmpdir, segment_size=100, auto_compact=False)

            # Write enough data to trigger rotation
            for i in range(10):
                db.set(f"key{i}", f"value{i}" * 10)

            # Should have multiple segments
            assert len(db.segments) > 1

            # Data should still be retrievable
            assert db.get("key0") == "value0" * 10
            assert db.get("key9") == "value9" * 10

            db.close()


class TestCompaction:
    """Test compaction functionality."""

    def test_compact_removes_deleted_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = LSDB(base_dir=tmpdir, segment_size=100, auto_compact=False)

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

            db.close()

    def test_compact_keeps_latest_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = LSDB(base_dir=tmpdir, segment_size=100, auto_compact=False)

            # Update same key multiple times
            db.set("key1", "old")
            db.set("key1", "newer")
            db.set("key1", "newest")

            db.compact()

            assert db.get("key1") == "newest"
            db.close()


class TestPersistence:
    """Test data persistence across database restarts."""

    def test_data_persists_after_restart(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write data
            db1 = LSDB(base_dir=tmpdir, auto_compact=False)
            db1.set("persistent", "data")
            db1.close()

            # Reopen and verify
            db2 = LSDB(base_dir=tmpdir, auto_compact=False)
            assert db2.get("persistent") == "data"
            db2.close()


@pytest.mark.skipif(fcntl is None, reason="cross-process lock needs fcntl (POSIX)")
class TestProcessLock:
    """Test the cross-process advisory lock."""

    def test_second_open_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db1 = LSDB(base_dir=tmpdir, auto_compact=False)
            try:
                with pytest.raises(DatabaseLockedError):
                    LSDB(base_dir=tmpdir, auto_compact=False)
            finally:
                db1.close()

    def test_reopen_after_close(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db1 = LSDB(base_dir=tmpdir, auto_compact=False)
            db1.close()
            # Lock released on close, so reopening succeeds
            db2 = LSDB(base_dir=tmpdir, auto_compact=False)
            db2.close()

    def test_process_lock_disabled_allows_second_open(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db1 = LSDB(base_dir=tmpdir, auto_compact=False, process_lock=False)
            db2 = LSDB(base_dir=tmpdir, auto_compact=False, process_lock=False)
            db1.close()
            db2.close()
