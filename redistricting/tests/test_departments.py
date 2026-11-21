"""Department codes from INSEE commune codes, and population per department."""

from __future__ import annotations

import pytest

from redistrict.allocate.departments import department_of, population_by_department


@pytest.mark.parametrize("code, dept", [
    ("01001", "01"), ("75101", "75"), ("2A004", "2A"), ("2B033", "2B"),
    ("97101", "971"), ("97411", "974"), ("95282", "95"),
])
def test_department_of(code, dept):
    assert department_of(code) == dept


def test_bad_code_rejected():
    with pytest.raises(ValueError):
        department_of("1234")


def test_population_by_department_skips_unknown_and_sums():
    pops = {"01001": 100, "01002": 50, "97101": 30, "02001": None}
    assert population_by_department(pops) == {"01": 150, "971": 30}
