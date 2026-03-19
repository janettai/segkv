"""CLI entry point for the memory store."""

import argparse
import json
import os
import sys

from memory.store import MemoryStore


def cmd_set(store: MemoryStore, args: argparse.Namespace) -> None:
    content = args.content or ""
    if args.content_file:
        if args.content_file == "-":
            content = sys.stdin.read()
        else:
            with open(args.content_file, encoding="utf-8") as f:
                content = f.read()
    record = store.set_memory(args.name, args.type, args.description, content)
    print(json.dumps(record, indent=2))


def cmd_get(store: MemoryStore, args: argparse.Namespace) -> None:
    record = store.get_memory(args.name)
    if record is None:
        print(json.dumps({"error": "not found", "name": args.name}))
        sys.exit(1)
    print(json.dumps(record, indent=2))


def cmd_delete(store: MemoryStore, args: argparse.Namespace) -> None:
    deleted = store.delete_memory(args.name)
    print(json.dumps({"deleted": deleted, "name": args.name}))
    if not deleted:
        sys.exit(1)


def cmd_list(store: MemoryStore, args: argparse.Namespace) -> None:
    memories = store.list_memories(type_filter=args.type)
    print(json.dumps(memories, indent=2))


def cmd_search(store: MemoryStore, args: argparse.Namespace) -> None:
    results = store.search_memories(args.query)
    print(json.dumps(results, indent=2))


def cmd_stats(store: MemoryStore, args: argparse.Namespace) -> None:
    print(json.dumps(store.stats(), indent=2))


def cmd_compact(store: MemoryStore, args: argparse.Namespace) -> None:
    store.compact()
    print(json.dumps({"status": "compacted"}))


def cmd_import_md(store: MemoryStore, args: argparse.Namespace) -> None:
    from memory.migrate import import_md_files

    imported = import_md_files(args.directory, store)
    print(json.dumps({"imported": imported, "count": len(imported)}))


def main() -> None:
    parser = argparse.ArgumentParser(description="Memory store CLI")
    parser.add_argument(
        "--db-path",
        default="~/.claude/memory.db",
        help="Path to the database directory",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # set
    p_set = subparsers.add_parser("set", help="Create or update a memory")
    p_set.add_argument("name")
    p_set.add_argument(
        "--type", required=True, choices=["user", "feedback", "project", "reference"]
    )
    p_set.add_argument("--description", required=True)
    p_set.add_argument("--content", default="")
    p_set.add_argument(
        "--content-file", help="Read content from file (use - for stdin)"
    )

    # get
    p_get = subparsers.add_parser("get", help="Get a memory by name")
    p_get.add_argument("name")

    # delete
    p_del = subparsers.add_parser("delete", help="Delete a memory by name")
    p_del.add_argument("name")

    # list
    p_list = subparsers.add_parser("list", help="List memories")
    p_list.add_argument("--type", choices=["user", "feedback", "project", "reference"])

    # search
    p_search = subparsers.add_parser("search", help="Search memories")
    p_search.add_argument("query")

    # stats
    subparsers.add_parser("stats", help="Show database stats")

    # compact
    subparsers.add_parser("compact", help="Trigger compaction")

    # import-md
    p_import = subparsers.add_parser("import-md", help="Import .md memory files")
    p_import.add_argument("directory")

    args = parser.parse_args()

    db_path = os.path.expanduser(args.db_path)
    store = MemoryStore(db_path=db_path)

    commands = {
        "set": cmd_set,
        "get": cmd_get,
        "delete": cmd_delete,
        "list": cmd_list,
        "search": cmd_search,
        "stats": cmd_stats,
        "compact": cmd_compact,
        "import-md": cmd_import_md,
    }

    try:
        commands[args.command](store, args)
    finally:
        store.close()


if __name__ == "__main__":
    main()
