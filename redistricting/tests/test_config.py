"""Config loading. The real example config must validate; typos and bad values must fail."""

from __future__ import annotations

from pathlib import Path

import pytest

from redistrict.config import ConfigError, load_config, parse_config

EXAMPLE = Path(__file__).resolve().parents[2] / "docs" / "redistricting" / "config.example.yaml"


def test_example_config_validates():
    cfg = load_config(EXAMPLE)
    assert cfg.global_.total_seats == 577
    assert cfg.allocation.method == "dhondt"
    assert cfg.constraints.hard_pop_tolerance == 0.20
    assert len(cfg.content_hash) == 64


def _minimal(**overrides):
    doc = {
        "global": {"scenario": "t", "total_seats": 577, "overseas_seats_mode": "fixed",
                   "fixed_seats_overseas": 19, "census_year": 2024, "random_seed": 1,
                   "output_dir": "runs/"},
        "allocation": {"method": "webster", "min_seats_per_dept": 1, "compare_methods": True},
        "constraints": {"population_basis": "legal_residents", "hard_pop_tolerance": 0.2,
                        "target_pop_tolerance": 0.05, "subdivision_factor": 1.2,
                        "whole_commune_below_population": 5000},
    }
    for section, changes in overrides.items():
        doc[section] = {**doc[section], **changes}
    return doc


def test_minimal_document_is_accepted():
    assert parse_config(_minimal()).allocation.method == "webster"


def test_unknown_key_is_rejected():
    doc = _minimal(allocation={"methd": "webster"})
    with pytest.raises(ConfigError, match="unknown keys in 'allocation'"):
        parse_config(doc)


def test_unknown_section_is_rejected():
    doc = _minimal()
    doc["optimisation"] = {}  # typo for 'optimization'
    with pytest.raises(ConfigError, match="unknown top-level"):
        parse_config(doc)


def test_electoral_population_basis_is_rejected():
    doc = _minimal(constraints={"population_basis": "registered_voters"})
    with pytest.raises(ConfigError, match="legal_residents"):
        parse_config(doc)


def test_subdivision_factor_below_hard_tolerance_is_rejected():
    doc = _minimal(constraints={"subdivision_factor": 1.1})
    with pytest.raises(ConfigError, match="subdivision_factor"):
        parse_config(doc)


def test_bool_is_not_accepted_as_int():
    doc = _minimal(global_={}) if False else _minimal()
    doc["global"]["total_seats"] = True
    with pytest.raises(ConfigError, match="integer"):
        parse_config(doc)
