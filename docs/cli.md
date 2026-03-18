# CLI Reference

The `memory` command provides a command-line interface to the [MemoryStore](api/memory-store.md).

**Source:** `memory_cli.py`

## Global options

| Option | Default | Description |
|--------|---------|-------------|
| `--db-path` | `~/.claude/memory.db` | Path to the database directory |

## Commands

### `set`

Create or update a memory record.

```bash
memory set <name> --type <type> --description <desc> [--content <text>] [--content-file <path>]
```

| Argument/Flag | Required | Description |
|---------------|----------|-------------|
| `name` | Yes | Name of the memory |
| `--type` | Yes | One of: `user`, `feedback`, `project`, `reference` |
| `--description` | Yes | One-line description |
| `--content` | No | Memory content as a string (default: empty) |
| `--content-file` | No | Read content from a file. Use `-` for stdin. |

```bash
memory set api-redesign \
  --type project \
  --description "API redesign notes" \
  --content "Switching to GraphQL in Q2"
```

Reading content from a file:

```bash
memory set meeting-notes \
  --type project \
  --description "Q1 planning notes" \
  --content-file ./notes.txt
```

Reading from stdin:

```bash
echo "Some content" | memory set my-note \
  --type reference \
  --description "A quick note" \
  --content-file -
```

---

### `get`

Retrieve a memory by name.

```bash
memory get <name>
```

Prints the record as JSON. Exits with code 1 if not found.

```bash
memory get api-redesign
```

```json
{
  "name": "api-redesign",
  "description": "API redesign notes",
  "type": "project",
  "content": "Switching to GraphQL in Q2",
  "created_at": 1704825600.0,
  "updated_at": 1704825600.0
}
```

---

### `delete`

Delete a memory by name.

```bash
memory delete <name>
```

Prints a JSON result with `"deleted": true` or `"deleted": false`. Exits with code 1 if the memory was not found.

```bash
memory delete api-redesign
```

---

### `list`

List all memories, optionally filtered by type.

```bash
memory list [--type <type>]
```

| Flag | Required | Description |
|------|----------|-------------|
| `--type` | No | Filter by type: `user`, `feedback`, `project`, `reference` |

```bash
# List all memories
memory list

# List only project memories
memory list --type project
```

---

### `search`

Search memories by keyword (case-insensitive substring match across name, description, and content).

```bash
memory search <query>
```

```bash
memory search GraphQL
```

---

### `stats`

Show database statistics.

```bash
memory stats
```

```json
{
  "num_segments": 1,
  "num_keys": 5,
  "total_size_bytes": 2048,
  "active_segment_size": 2048
}
```

---

### `compact`

Trigger manual compaction of the database.

```bash
memory compact
```

---

### `import-md`

Import `.md` memory files from a directory.

```bash
memory import-md <directory>
```

Parses YAML frontmatter for `name`, `type`, and `description`. Skips `MEMORY.md`. See [Migration Utilities](api/migration.md) for the expected file format.

```bash
memory import-md ~/.claude/projects/my-project/memory/
```

```json
{
  "imported": ["api-redesign", "team-prefs"],
  "count": 2
}
```
