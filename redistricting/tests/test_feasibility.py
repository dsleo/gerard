"""Component feasibility: a department's connected pieces must hold whole districts within tolerance."""

from __future__ import annotations

from redistrict.graph.feasibility import component_seat_range, department_feasible


def test_single_component_at_target_needs_one_seat():
    r = component_seat_range(100, target=100, tol=0.2)
    assert (r.k_min, r.k_max) == (1, 1)


def test_small_component_cannot_form_a_district():
    # 50 people vs target 100 with tolerance 20%: no whole number of districts fits
    r = component_seat_range(50, target=100, tol=0.2)
    assert r.k_min > r.k_max


def test_two_districts_worth_of_population():
    r = component_seat_range(200, target=100, tol=0.2)
    assert r.k_min <= 2 <= r.k_max


def test_department_feasible_when_components_fit_the_seats():
    ok, reason = department_feasible([100, 200], target=100, tol=0.2, seats=3)
    assert ok, reason


def test_department_infeasible_when_a_piece_is_too_small():
    ok, reason = department_feasible([100, 50], target=100, tol=0.2, seats=2)
    assert not ok
    assert "cannot be split" in reason


def test_department_infeasible_when_seat_count_is_outside_range():
    ok, reason = department_feasible([100, 100], target=100, tol=0.2, seats=5)
    assert not ok
    assert "outside feasible range" in reason
