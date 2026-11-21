"""Seat allocation (Module 1). Checks the two hard rules and the D'Hondt / Webster difference."""

from __future__ import annotations

import pytest

from redistrict.allocate.apportion import apportion


def test_seats_sum_to_total_and_floor_holds():
    pops = {"01": 600_000, "02": 500_000, "03": 40_000}
    seats = apportion(pops, total_seats=10, method="dhondt", min_seats=1)
    assert sum(seats.values()) == 10
    assert all(k >= 1 for k in seats.values())


@pytest.mark.parametrize("method", ["dhondt", "webster"])
def test_more_population_never_gets_fewer_seats(method):
    pops = {"a": 900, "b": 500, "c": 100}
    seats = apportion(pops, total_seats=12, method=method, min_seats=1)
    assert seats["a"] >= seats["b"] >= seats["c"]


def test_dhondt_and_webster_can_differ():
    # Worked by hand. Start (1,1). Extra seat 1 goes to a under both methods (16 > 10).
    # Extra seat 2: D'Hondt compares 16/3=5.33 vs 10/2=5    -> a
    #               Webster compares 16/2.5=6.40 vs 10/1.5=6.67 -> b
    pops = {"a": 16, "b": 10}
    assert apportion(pops, total_seats=4, method="dhondt") == {"a": 3, "b": 1}
    assert apportion(pops, total_seats=4, method="webster") == {"a": 2, "b": 2}


def test_ties_are_broken_by_code():
    pops = {"02": 100, "01": 100}
    seats = apportion(pops, total_seats=3, method="dhondt")
    assert seats == {"01": 2, "02": 1}


def test_rejects_total_below_floor():
    with pytest.raises(ValueError):
        apportion({"a": 1, "b": 1, "c": 1}, total_seats=2, method="dhondt", min_seats=1)
