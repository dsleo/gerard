"""Shared fixtures. The toy grid is the fixture for every algorithmic test: no real data needed."""

from __future__ import annotations

import pytest


def make_grid(n: int = 4, pop: int = 100) -> tuple[set[str], dict[str, int], dict[str, set[str]]]:
    """n x n grid of unit squares. Rook adjacency; every unit has the same population."""
    units = {f"r{i}c{j}" for i in range(n) for j in range(n)}
    population = {u: pop for u in units}
    adjacency: dict[str, set[str]] = {u: set() for u in units}
    for i in range(n):
        for j in range(n):
            for di, dj in ((1, 0), (0, 1)):
                a, b = f"r{i}c{j}", f"r{i + di}c{j + dj}"
                if i + di < n and j + dj < n:
                    adjacency[a].add(b)
                    adjacency[b].add(a)
    return units, population, adjacency


@pytest.fixture
def grid4():
    return make_grid(4)
