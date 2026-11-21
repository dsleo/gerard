"""Fan-out over departments.

Every department is an independent job: its graph, its seats, its optimizer and
its sampler never need another department's result. Jobs run in a process pool.

Determinism: each department gets its own seed derived from (global seed,
department code). The result does not depend on worker count or scheduling order.

Debugging: `workers=1` runs everything in-process, in order, with no pool.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any


def dept_seed(global_seed: int, dept: str) -> int:
    """Stable 64-bit seed for one department."""
    digest = hashlib.sha256(f"{global_seed}:{dept}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def run_per_department(
    job: Callable[[str, int], Any],
    departments: Iterable[str],
    global_seed: int,
    workers: int | None = None,
) -> dict[str, Any]:
    """Run `job(dept, seed)` for every department and return results sorted by code.

    `job` must be a top-level (picklable) function when workers != 1.
    """
    depts = sorted(set(departments))
    if workers == 1:
        return {d: job(d, dept_seed(global_seed, d)) for d in depts}

    results: dict[str, Any] = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(job, d, dept_seed(global_seed, d)): d for d in depts}
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
            print(f"completed {len(results)}/{len(depts)} departments", flush=True)
    return dict(sorted(results.items()))
