"""Department codes and departmental populations (input to Module 1).

INSEE commune codes encode the department: the first two characters for metropolitan
departments ("01".."95", "2A", "2B"), the first three for DROM ("971".."976").
"""

from __future__ import annotations

from collections.abc import Iterable


def department_of(unit_code: str) -> str:
    """Department code of a commune, arrondissement or IRIS code.

    IRIS codes (9 characters) start with their 5-character commune code, so the first five are used.
    """
    if len(unit_code) not in (5, 9):
        raise ValueError(f"unexpected INSEE code: {unit_code!r}")
    commune = unit_code[:5]
    return commune[:3] if commune.startswith("97") else commune[:2]


def population_by_department(unit_pops: dict[str, int]) -> dict[str, int]:
    """Sum unit populations per department. Units with no population (None) are skipped and must be reported by the caller."""
    out: dict[str, int] = {}
    for code, pop in unit_pops.items():
        if pop is None:
            continue
        d = department_of(code)
        out[d] = out.get(d, 0) + int(pop)
    return dict(sorted(out.items()))


def departments_in(codes: Iterable[str]) -> set[str]:
    return {department_of(c) for c in codes}
