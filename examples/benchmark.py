"""Benchmark the segkv MemoryStore for the shared / large-corpus use case.

Three suites:

  core         per-operation cost vs corpus size N, for the stock MemoryStore and
               the CachedMemoryStore prototype side by side:
                 * bulk write throughput        (fsync-bound)
                 * point recall latency         (~O(1))
                 * search / list latency        (stock: O(N) disk seeks; cached: in-mem)
                 * cold-start / index rebuild   (replays segments; cached also loads records)
                 * compaction time

  churn        rewrite the same keys repeatedly, then compact — shows on-disk bloat
               from the append-only log and how much compaction reclaims.

  concurrency  N threads hammering the store — shows how reads scale (brief lock) vs
               writes (serialized on the write lock + fsync).

Usage:
    uv run python examples/benchmark.py
    uv run python examples/benchmark.py --sizes 1000 10000 50000
    uv run python examples/benchmark.py --only churn --churn-rounds 10
    uv run python examples/benchmark.py --only concurrency --threads 1 2 4 8
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import statistics
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from cached_memory_store import CachedMemoryStore  # noqa: E402

from memory.store import MemoryStore  # noqa: E402

StoreFactory = Callable[[str], MemoryStore]

_TYPES = ["user", "feedback", "project", "reference"]
_WORDS = [
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "zeta",
    "eta",
    "theta",
    "iota",
    "kappa",
    "lambda",
    "mu",
    "nu",
    "xi",
    "omicron",
    "pi",
    "rho",
    "sigma",
    "tau",
    "upsilon",
    "phi",
    "chi",
    "psi",
    "omega",
    "vector",
    "matrix",
    "kernel",
    "latency",
    "throughput",
    "segment",
    "compaction",
    "tombstone",
    "index",
    "offset",
    "recovery",
]


def _dir_size_bytes(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            total += os.path.getsize(os.path.join(root, name))
    return total


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def _gen_content(rng: random.Random, nbytes: int) -> str:
    out: list[str] = []
    size = 0
    while size < nbytes:
        w = rng.choice(_WORDS)
        out.append(w)
        size += len(w) + 1
    return " ".join(out)


def _percentiles(samples_s: list[float]) -> tuple[float, float, float]:
    """Return (p50, p95, p99) in microseconds."""
    ordered = sorted(samples_s)

    def q(p: float) -> float:
        idx = min(len(ordered) - 1, int(p * len(ordered)))
        return ordered[idx] * 1e6

    return q(0.50), q(0.95), q(0.99)


def _populate(
    store: MemoryStore, names: list[str], rng: random.Random, nbytes: int
) -> None:
    for i, name in enumerate(names):
        store.set_memory(
            name=name,
            type_=_TYPES[i % len(_TYPES)],
            description=f"record {i} {rng.choice(_WORDS)}",
            content=_gen_content(rng, nbytes),
        )


# --------------------------------------------------------------------------- core


def bench_core(
    factory: StoreFactory,
    label: str,
    n: int,
    content_bytes: int,
    read_samples: int,
    seed: int,
) -> dict:
    rng = random.Random(seed)
    tmp = tempfile.mkdtemp(prefix="segkv_bench_")
    db_path = os.path.join(tmp, "memory.db")
    result: dict = {"store": label, "n": n}
    try:
        store = factory(db_path)
        names = [f"mem-{i:08d}" for i in range(n)]
        t0 = time.perf_counter()
        _populate(store, names, rng, content_bytes)
        result["writes_per_s"] = n / (time.perf_counter() - t0)

        sample_names = [rng.choice(names) for _ in range(min(read_samples, n))]
        lat = []
        for name in sample_names:
            t = time.perf_counter()
            store.get_memory(name)
            lat.append(time.perf_counter() - t)
        result["recall_p50_us"], _, result["recall_p99_us"] = _percentiles(lat)

        s_lat = []
        for qword in [rng.choice(_WORDS) for _ in range(5)]:
            t = time.perf_counter()
            store.search_memories(qword)
            s_lat.append(time.perf_counter() - t)
        result["search_ms"] = statistics.mean(s_lat) * 1e3

        t = time.perf_counter()
        store.list_memories()
        result["list_ms"] = (time.perf_counter() - t) * 1e3

        t = time.perf_counter()
        store.compact()
        result["compact_ms"] = (time.perf_counter() - t) * 1e3
        store.close()

        t = time.perf_counter()
        store2 = factory(db_path)
        result["cold_start_ms"] = (time.perf_counter() - t) * 1e3
        store2.close()
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _print_core(rows: list[dict]) -> None:
    cols = [
        ("store", lambda r: r["store"]),
        ("N", lambda r: f"{r['n']:,}"),
        ("write/s", lambda r: f"{r['writes_per_s']:,.0f}"),
        ("recall p50", lambda r: f"{r['recall_p50_us']:.0f}us"),
        ("recall p99", lambda r: f"{r['recall_p99_us']:.0f}us"),
        ("search", lambda r: f"{r['search_ms']:.1f}ms"),
        ("list", lambda r: f"{r['list_ms']:.1f}ms"),
        ("cold start", lambda r: f"{r['cold_start_ms']:.1f}ms"),
        ("compact", lambda r: f"{r['compact_ms']:.1f}ms"),
    ]
    header = "  ".join(f"{name:>12s}" for name, _ in cols)
    print(header)
    print("-" * len(header))
    for r in rows:
        print("  ".join(f"{fn(r):>12s}" for _, fn in cols))


# -------------------------------------------------------------------------- churn


def bench_churn(n: int, rounds: int, content_bytes: int, seed: int) -> dict:
    rng = random.Random(seed)
    tmp = tempfile.mkdtemp(prefix="segkv_churn_")
    db_path = os.path.join(tmp, "memory.db")
    try:
        store = MemoryStore(db_path=db_path)
        names = [f"mem-{i:08d}" for i in range(n)]
        for _ in range(rounds):
            _populate(store, names, rng, content_bytes)
        disk_before = _dir_size_bytes(db_path)
        segs_before = store.stats().get("num_segments")
        store.compact()
        disk_after = _dir_size_bytes(db_path)
        store.close()
        return {
            "n": n,
            "rounds": rounds,
            "disk_before": disk_before,
            "disk_after": disk_after,
            "segs_before": segs_before,
            "bloat_x": disk_before / max(disk_after, 1),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# -------------------------------------------------------------------- concurrency


def _run_threads(worker: Callable[[int], None], nthreads: int) -> float:
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(nthreads)]
    t0 = time.perf_counter()
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    return time.perf_counter() - t0


def _make_reader(
    store: MemoryStore, names: list[str], ops: int, seed: int
) -> Callable[[int], None]:
    rng = random.Random(seed)

    def reader(_tid: int) -> None:
        for _ in range(ops):
            store.get_memory(rng.choice(names))

    return reader


def _make_writer(store: MemoryStore, ops: int) -> Callable[[int], None]:
    counter = {"i": 0}
    clock = threading.Lock()

    def writer(tid: int) -> None:
        for _ in range(ops):
            with clock:
                counter["i"] += 1
                idx = counter["i"]
            store.set_memory(
                name=f"w-{tid}-{idx}",
                type_="project",
                description="concurrent write",
                content="x" * 32,
            )

    return writer


def bench_concurrency(
    n: int, thread_counts: list[int], ops: int, content_bytes: int, seed: int
) -> list[dict]:
    rng = random.Random(seed)
    tmp = tempfile.mkdtemp(prefix="segkv_conc_")
    db_path = os.path.join(tmp, "memory.db")
    rows: list[dict] = []
    try:
        store = MemoryStore(db_path=db_path)
        names = [f"mem-{i:08d}" for i in range(n)]
        _populate(store, names, rng, content_bytes)

        for t in thread_counts:
            read_s = (t * ops) / _run_threads(_make_reader(store, names, ops, seed), t)
            write_s = (t * ops) / _run_threads(_make_writer(store, ops), t)
            rows.append({"threads": t, "read_ops_s": read_s, "write_ops_s": write_s})
        store.close()
        return rows
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- main


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 50000])
    parser.add_argument("--content-bytes", type=int, default=512)
    parser.add_argument("--read-samples", type=int, default=1000)
    parser.add_argument("--churn-rounds", type=int, default=5)
    parser.add_argument("--threads", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--conc-ops", type=int, default=5000)
    parser.add_argument(
        "--only",
        choices=["core", "churn", "concurrency"],
        nargs="+",
        default=["core", "churn", "concurrency"],
    )
    parser.add_argument("--seed", type=int, default=1234)
    args = parser.parse_args()

    stores: list[tuple[str, StoreFactory]] = [
        ("stock", lambda p: MemoryStore(db_path=p)),
        ("cached", lambda p: CachedMemoryStore(db_path=p)),
    ]

    if "core" in args.only:
        print("=== core: stock vs cached ===")
        rows = []
        for n in sorted(args.sizes):
            for label, factory in stores:
                print(f"  running {label} N={n:,} ...", flush=True)
                rows.append(
                    bench_core(
                        factory,
                        label,
                        n,
                        args.content_bytes,
                        args.read_samples,
                        args.seed,
                    )
                )
        print()
        _print_core(rows)
        print()

    if "churn" in args.only:
        print(f"=== churn: rewrite all keys x{args.churn_rounds}, then compact ===")
        for n in sorted(args.sizes):
            r = bench_churn(n, args.churn_rounds, args.content_bytes, args.seed)
            print(
                f"  N={n:,}: {r['segs_before']} segments, "
                f"disk {_human(r['disk_before'])} -> {_human(r['disk_after'])} "
                f"after compaction ({r['bloat_x']:.1f}x bloat reclaimed)"
            )
        print()

    if "concurrency" in args.only:
        n = max(args.sizes)
        print(
            f"=== concurrency: {args.conc_ops} ops/thread over N={n:,} (stock store) ==="
        )
        rows = bench_concurrency(
            n, sorted(args.threads), args.conc_ops, args.content_bytes, args.seed
        )
        print(f"  {'threads':>8s}  {'reads/s':>12s}  {'writes/s':>12s}")
        print("  " + "-" * 36)
        for r in rows:
            print(
                f"  {r['threads']:>8d}  {r['read_ops_s']:>12,.0f}  {r['write_ops_s']:>12,.0f}"
            )
        print()


if __name__ == "__main__":
    main()
