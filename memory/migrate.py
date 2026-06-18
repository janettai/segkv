from __future__ import annotations

from pathlib import Path

from memory.store import MemoryStore


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """
    Parse YAML frontmatter from markdown text.

    Returns (metadata_dict, body). If no valid frontmatter found, returns ({}, text).
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text

    closing = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing = i
            break

    if closing is None:
        return {}, text

    metadata: dict[str, str] = {}
    for line in lines[1:closing]:
        if ": " in line:
            key, _, value = line.partition(": ")
            metadata[key.strip()] = value.strip()
        elif line.strip():
            # key: value with no space after colon (e.g. "key:value")
            if ":" in line:
                key, _, value = line.partition(":")
                metadata[key.strip()] = value.strip()

    body = "\n".join(lines[closing + 1 :]).strip()
    return metadata, body


def import_md_files(directory: str, store: MemoryStore) -> list[str]:
    """
    Import .md files from a directory into a MemoryStore.

    Skips MEMORY.md. Falls back to filename stem for name, "project" for type,
    and "" for description when frontmatter fields are missing.

    Raises FileNotFoundError if the directory does not exist.
    Returns list of imported memory names (alphabetical order).
    """
    path = Path(directory).expanduser()
    if not path.is_dir():
        raise FileNotFoundError(f"Directory not found: {directory}")

    imported: list[str] = []
    for md_file in sorted(path.glob("*.md")):
        if md_file.name == "MEMORY.md":
            continue

        text = md_file.read_text(encoding="utf-8")
        metadata, body = parse_frontmatter(text)

        name = metadata.get("name") or md_file.stem
        type_ = metadata.get("type") or "project"
        description = metadata.get("description") or ""

        store.set_memory(name=name, type_=type_, description=description, content=body)
        imported.append(name)

    return imported
