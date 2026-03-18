# Migration Utilities

Utilities for importing existing markdown memory files into a [MemoryStore](memory-store.md).

**Source:** `memory/migrate.py`

## Functions

### `parse_frontmatter(text)`

```python
def parse_frontmatter(text: str) -> tuple[dict[str, str], str]
```

Parse YAML frontmatter from markdown text. Frontmatter is delimited by `---` lines at the start of the file.

**Returns:** A tuple of `(metadata_dict, body_content)`. If no frontmatter is found, returns an empty dict and the original text.

```python
from memory.migrate import parse_frontmatter

text = """---
name: api-redesign
type: project
description: API redesign notes
---

We're switching to GraphQL in Q2.
"""

metadata, body = parse_frontmatter(text)
# metadata = {"name": "api-redesign", "type": "project", "description": "API redesign notes"}
# body = "We're switching to GraphQL in Q2."
```

---

### `import_md_files(directory, store)`

```python
def import_md_files(directory: str, store: MemoryStore) -> list[str]
```

Bulk import `.md` files from a directory into a `MemoryStore`.

**Behavior:**

- Scans the directory for `*.md` files (sorted alphabetically)
- Skips `MEMORY.md` (the index file)
- Parses YAML frontmatter for `name`, `type`, and `description`
- Falls back to the filename stem for `name` if not in frontmatter
- Falls back to `"project"` for `type` if not in frontmatter
- Uses the body (after frontmatter) as `content`

**Raises:** `FileNotFoundError` if the directory doesn't exist.

**Returns:** List of imported memory names.

### Expected file format

```markdown
---
name: my-memory
type: user
description: A short description
---

The memory content goes here.
```

### Example usage

```python
from memory.store import MemoryStore
from memory.migrate import import_md_files

store = MemoryStore(db_path="./my_db")
imported = import_md_files("./old_memories", store)
print(f"Imported {len(imported)} memories: {imported}")
store.close()
```

From the CLI:

```bash
memory import-md ./old_memories
```
