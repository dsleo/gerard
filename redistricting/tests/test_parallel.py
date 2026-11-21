"""Department fan-out: same results regardless of worker count; seeds are stable."""

from __future__ import annotations

from redistrict.parallel import dept_seed, run_per_department


def _job(dept: str, seed: int) -> tuple[str, int]:
    # stand-in for a real per-department job: deterministic in (dept, seed)
    return dept, seed % 1000


DEPTS = ["75", "2A", "2B", "13", "971"]


def test_seed_is_stable_and_department_specific():
    assert dept_seed(42, "75") == dept_seed(42, "75")
    assert dept_seed(42, "75") != dept_seed(42, "13")
    assert dept_seed(42, "75") != dept_seed(43, "75")


def test_sequential_run_is_sorted_and_complete():
    out = run_per_department(_job, DEPTS, global_seed=42, workers=1)
    assert list(out) == sorted(DEPTS)


def test_parallel_matches_sequential():
    seq = run_per_department(_job, DEPTS, global_seed=42, workers=1)
    par = run_per_department(_job, DEPTS, global_seed=42, workers=2)
    assert seq == par
