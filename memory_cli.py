from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from memory.migrate import import_md_files
from memory.store import MemoryStore


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="memory",
        description="CLI for the segkv MemoryStore",
    )
    parser.add_argument(
        "--db-path",
        default=str(Path("~/.claude/memory.db").expanduser()),
        help="Path to the database directory (default: ~/.claude/memory.db)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # set
    set_p = subparsers.add_parser("set", help="Create or update a memory record")
    set_p.add_argument("name", help="Name of the memory")
    set_p.add_argument(
        "--type",
        dest="type_",
        required=True,
        choices=["user", "feedback", "project", "reference"],
        help="Memory type",
    )
    set_p.add_argument("--description", required=True, help="One-line description")
    set_p.add_argument("--content", default="", help="Memory content")
    set_p.add_argument(
        "--content-file",
        help="Read content from a file. Use - for stdin.",
    )

    # get
    get_p = subparsers.add_parser("get", help="Retrieve a memory by name")
    get_p.add_argument("name")

    # delete
    del_p = subparsers.add_parser("delete", help="Delete a memory by name")
    del_p.add_argument("name")

    # list
    list_p = subparsers.add_parser("list", help="List memories")
    list_p.add_argument(
        "--type",
        dest="type_filter",
        choices=["user", "feedback", "project", "reference"],
        default=None,
        help="Filter by type",
    )

    # search
    search_p = subparsers.add_parser("search", help="Search memories by keyword")
    search_p.add_argument("query")

    # stats
    subparsers.add_parser("stats", help="Show database statistics")

    # compact
    subparsers.add_parser("compact", help="Compact the database")

    # import-md
    import_p = subparsers.add_parser(
        "import-md", help="Import .md memory files from a directory"
    )
    import_p.add_argument("directory")

    args = parser.parse_args()
    store = MemoryStore(db_path=args.db_path)

    try:
        if args.command == "set":
            content = args.content
            if args.content_file:
                if args.content_file == "-":
                    content = sys.stdin.read()
                else:
                    try:
                        content = Path(args.content_file).read_text()
                    except FileNotFoundError:
                        print(
                            json.dumps(
                                {"error": f"File not found: {args.content_file}"}
                            ),
                            file=sys.stderr,
                        )
                        sys.exit(1)
            try:
                record = store.set_memory(
                    name=args.name,
                    type_=args.type_,
                    description=args.description,
                    content=content,
                )
            except ValueError as e:
                print(json.dumps({"error": str(e)}), file=sys.stderr)
                sys.exit(1)
            print(json.dumps(record, indent=2))

        elif args.command == "get":
            record = store.get_memory(args.name)
            if record is None:
                print(
                    json.dumps({"error": f"Memory '{args.name}' not found"}),
                    file=sys.stderr,
                )
                sys.exit(1)
            print(json.dumps(record, indent=2))

        elif args.command == "delete":
            deleted = store.delete_memory(args.name)
            print(json.dumps({"deleted": deleted}))
            if not deleted:
                sys.exit(1)

        elif args.command == "list":
            results = store.list_memories(type_filter=args.type_filter)
            print(json.dumps(results, indent=2))

        elif args.command == "search":
            results = store.search_memories(args.query)
            print(json.dumps(results, indent=2))

        elif args.command == "stats":
            print(json.dumps(store.stats(), indent=2))

        elif args.command == "compact":
            store.compact()
            print(json.dumps({"compacted": True}))

        elif args.command == "import-md":
            try:
                imported = import_md_files(args.directory, store)
            except FileNotFoundError as e:
                print(json.dumps({"error": str(e)}), file=sys.stderr)
                sys.exit(1)
            print(json.dumps({"imported": imported, "count": len(imported)}, indent=2))

    finally:
        store.close()


if __name__ == "__main__":
    main()
