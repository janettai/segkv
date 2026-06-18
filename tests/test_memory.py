import tempfile
from pathlib import Path

import pytest

from memory import MemoryStore, import_md_files, parse_frontmatter


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = MemoryStore(db_path=tmpdir)
        yield s
        s.close()


class TestMemoryStoreCRUD:
    def test_set_and_get(self, store):
        record = store.set_memory(
            name="test", type_="project", description="desc", content="body"
        )
        assert record["name"] == "test"
        assert record["type"] == "project"
        assert record["description"] == "desc"
        assert record["content"] == "body"
        assert record["created_at"] > 0
        assert record["updated_at"] > 0

        fetched = store.get_memory("test")
        assert fetched == record

    def test_get_nonexistent(self, store):
        assert store.get_memory("nope") is None

    def test_update_preserves_created_at(self, store):
        r1 = store.set_memory(name="x", type_="user", description="d", content="v1")
        r2 = store.set_memory(name="x", type_="user", description="d", content="v2")
        assert r2["created_at"] == r1["created_at"]
        assert r2["updated_at"] >= r1["updated_at"]
        assert r2["content"] == "v2"

    def test_delete_returns_true(self, store):
        store.set_memory(name="x", type_="user", description="d", content="c")
        assert store.delete_memory("x") is True

    def test_delete_missing_returns_false(self, store):
        assert store.delete_memory("ghost") is False

    def test_delete_then_get_returns_none(self, store):
        store.set_memory(name="x", type_="user", description="d", content="c")
        store.delete_memory("x")
        assert store.get_memory("x") is None


class TestTypeValidation:
    def test_invalid_type_raises_value_error(self, store):
        with pytest.raises(ValueError, match="type_"):
            store.set_memory(name="x", type_="invalid", description="d", content="c")

    def test_all_valid_types(self, store):
        for i, t in enumerate(["user", "feedback", "project", "reference"]):
            record = store.set_memory(
                name=f"mem{i}", type_=t, description="d", content="c"
            )
            assert record["type"] == t


class TestListMemories:
    def test_list_empty(self, store):
        assert store.list_memories() == []

    def test_list_sorted_by_name(self, store):
        store.set_memory(name="b", type_="user", description="d", content="c")
        store.set_memory(name="a", type_="user", description="d", content="c")
        store.set_memory(name="c", type_="user", description="d", content="c")
        names = [r["name"] for r in store.list_memories()]
        assert names == ["a", "b", "c"]

    def test_list_filter_by_type(self, store):
        store.set_memory(name="p1", type_="project", description="d", content="c")
        store.set_memory(name="p2", type_="project", description="d", content="c")
        store.set_memory(name="u1", type_="user", description="d", content="c")
        projects = store.list_memories(type_filter="project")
        assert len(projects) == 2
        assert all(r["type"] == "project" for r in projects)

    def test_list_excludes_deleted(self, store):
        store.set_memory(name="keep", type_="user", description="d", content="c")
        store.set_memory(name="gone", type_="user", description="d", content="c")
        store.delete_memory("gone")
        names = [r["name"] for r in store.list_memories()]
        assert "gone" not in names
        assert "keep" in names


class TestSearchMemories:
    def test_search_by_name(self, store):
        store.set_memory(
            name="graphql-api", type_="project", description="d", content="c"
        )
        results = store.search_memories("graphql")
        assert len(results) == 1
        assert results[0]["name"] == "graphql-api"

    def test_search_by_description(self, store):
        store.set_memory(
            name="x", type_="project", description="GraphQL schema", content="c"
        )
        results = store.search_memories("schema")
        assert len(results) == 1

    def test_search_by_content(self, store):
        store.set_memory(
            name="x", type_="project", description="d", content="uses REST endpoints"
        )
        results = store.search_memories("REST")
        assert len(results) == 1

    def test_search_case_insensitive(self, store):
        store.set_memory(name="x", type_="project", description="GraphQL", content="c")
        assert len(store.search_memories("graphql")) == 1
        assert len(store.search_memories("GRAPHQL")) == 1

    def test_search_no_match(self, store):
        store.set_memory(name="x", type_="project", description="d", content="c")
        assert store.search_memories("zzznomatch") == []

    def test_search_sorted_by_name(self, store):
        store.set_memory(name="b-mem", type_="project", description="foo", content="c")
        store.set_memory(name="a-mem", type_="project", description="foo", content="c")
        results = store.search_memories("foo")
        assert [r["name"] for r in results] == ["a-mem", "b-mem"]


class TestParseFrontmatter:
    def test_with_frontmatter(self):
        text = "---\nname: my-mem\ntype: user\ndescription: A description\n---\n\nThe body."
        meta, body = parse_frontmatter(text)
        assert meta == {
            "name": "my-mem",
            "type": "user",
            "description": "A description",
        }
        assert body == "The body."

    def test_without_frontmatter(self):
        text = "Just plain text."
        meta, body = parse_frontmatter(text)
        assert meta == {}
        assert body == "Just plain text."

    def test_empty_frontmatter_block(self):
        text = "---\n---\n\nBody here."
        meta, body = parse_frontmatter(text)
        assert meta == {}
        assert body == "Body here."

    def test_no_closing_delimiter(self):
        text = "---\nname: x\n\nBody."
        meta, body = parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_body_stripped(self):
        text = "---\nname: x\n---\n\n\n  Body with space.  \n\n"
        _, body = parse_frontmatter(text)
        assert body == "Body with space."


class TestImportMdFiles:
    def test_basic_import(self, store):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "mem.md").write_text(
                "---\nname: my-mem\ntype: project\ndescription: A desc\n---\n\nContent here."
            )
            imported = import_md_files(tmpdir, store)
        assert imported == ["my-mem"]
        record = store.get_memory("my-mem")
        assert record is not None
        assert record["type"] == "project"
        assert record["description"] == "A desc"
        assert record["content"] == "Content here."

    def test_skip_memory_md(self, store):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "MEMORY.md").write_text("# Index\n")
            Path(tmpdir, "real.md").write_text(
                "---\nname: real\ntype: user\ndescription: d\n---\nbody"
            )
            imported = import_md_files(tmpdir, store)
        assert "MEMORY.md" not in imported
        assert "real" in imported

    def test_frontmatter_fallbacks(self, store):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "no-frontmatter.md").write_text("Plain body content.")
            imported = import_md_files(tmpdir, store)
        assert imported == ["no-frontmatter"]
        record = store.get_memory("no-frontmatter")
        assert record is not None
        assert record["type"] == "project"
        assert record["description"] == ""
        assert record["content"] == "Plain body content."

    def test_missing_directory_raises(self, store):
        with pytest.raises(FileNotFoundError):
            import_md_files("/nonexistent/path/xyz", store)

    def test_empty_directory(self, store):
        with tempfile.TemporaryDirectory() as tmpdir:
            imported = import_md_files(tmpdir, store)
        assert imported == []

    def test_returns_sorted_names(self, store):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["c.md", "a.md", "b.md"]:
                Path(tmpdir, name).write_text(f"# {name}")
            imported = import_md_files(tmpdir, store)
        assert imported == ["a", "b", "c"]
