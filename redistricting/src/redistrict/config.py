"""Load and validate config.yaml.

Strict by design: unknown sections and unknown keys are errors, so a typo can
never silently change a result. Only sections the code currently uses are
typed here; add others here when a module starts reading them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

KNOWN_SECTIONS = frozenset(
    {"global", "allocation", "constraints", "inputs", "graph", "optimization",
     "sampler", "audit", "gates", "viz", "manual_overrides"}
)


class ConfigError(ValueError):
    """Raised for any invalid or unknown configuration entry."""


@dataclass(frozen=True)
class GlobalConfig:
    scenario: str
    total_seats: int
    overseas_seats_mode: str  # fixed | proportional  (D3)
    fixed_seats_overseas: int
    census_year: int
    random_seed: int
    output_dir: str


@dataclass(frozen=True)
class AllocationConfig:
    method: str  # dhondt | webster  (D8)
    min_seats_per_dept: int
    compare_methods: bool


@dataclass(frozen=True)
class ConstraintsConfig:
    population_basis: str  # only legal_residents (D1)
    hard_pop_tolerance: float  # D5
    target_pop_tolerance: float
    subdivision_factor: float  # D4-r
    whole_commune_below_population: int  # D4-r, [VERIFY L.125]
    exceptions: tuple  # D5: justified departments allowed above the hard tolerance


@dataclass(frozen=True)
class Config:
    global_: GlobalConfig
    allocation: AllocationConfig
    constraints: ConstraintsConfig
    raw: dict[str, Any]  # full parsed document, for snapshotting into run folders

    @property
    def content_hash(self) -> str:
        """Stable hash of the config, stored in every run manifest."""
        canonical = yaml.safe_dump(self.raw, sort_keys=True).encode()
        return hashlib.sha256(canonical).hexdigest()


def _section(
    doc: dict[str, Any],
    name: str,
    allowed: dict[str, type],
    optional: dict[str, type] | None = None,
) -> dict[str, Any]:
    """Return one section, checking that every key is known and well-typed."""
    optional = optional or {}
    if name not in doc:
        raise ConfigError(f"missing section '{name}'")
    body = doc[name]
    if not isinstance(body, dict):
        raise ConfigError(f"section '{name}' must be a mapping")
    unknown = set(body) - set(allowed) - set(optional)
    if unknown:
        raise ConfigError(f"unknown keys in '{name}': {sorted(unknown)}")
    missing = set(allowed) - set(body)
    if missing:
        raise ConfigError(f"missing keys in '{name}': {sorted(missing)}")
    for key, expected in {**allowed, **optional}.items():
        if key not in body:
            continue
        value = body[key]
        # bool is a subclass of int in Python; reject it where an int is meant
        if expected is int and isinstance(value, bool):
            raise ConfigError(f"'{name}.{key}' must be an integer, got bool")
        if expected is float and isinstance(value, int) and not isinstance(value, bool):
            body[key] = float(value)
            continue
        if not isinstance(value, expected):
            raise ConfigError(f"'{name}.{key}' must be {expected.__name__}")
    return body


def parse_config(doc: dict[str, Any]) -> Config:
    """Validate a parsed YAML document and return typed config objects."""
    unknown_top = set(doc) - KNOWN_SECTIONS
    if unknown_top:
        raise ConfigError(f"unknown top-level sections: {sorted(unknown_top)}")

    g = _section(doc, "global", {
        "scenario": str, "total_seats": int, "overseas_seats_mode": str,
        "fixed_seats_overseas": int, "census_year": int, "random_seed": int,
        "output_dir": str,
    })
    if g["overseas_seats_mode"] not in {"fixed", "proportional"}:
        raise ConfigError("global.overseas_seats_mode must be 'fixed' or 'proportional'")
    if g["total_seats"] <= g["fixed_seats_overseas"]:
        raise ConfigError("global.total_seats must exceed fixed_seats_overseas")

    a = _section(doc, "allocation", {
        "method": str, "min_seats_per_dept": int, "compare_methods": bool,
    })
    if a["method"] not in {"dhondt", "webster"}:
        raise ConfigError("allocation.method must be 'dhondt' or 'webster'")
    if a["min_seats_per_dept"] < 1:
        raise ConfigError("allocation.min_seats_per_dept must be at least 1 (constitutional floor)")

    c = _section(doc, "constraints", {
        "population_basis": str, "hard_pop_tolerance": float,
        "target_pop_tolerance": float, "subdivision_factor": float,
        "whole_commune_below_population": int,
    }, optional={"exceptions": list})  # D5: [] or a list of justified exceptions
    if c["population_basis"] != "legal_residents":
        raise ConfigError("constraints.population_basis must be 'legal_residents' (D1)")
    if not 0 < c["target_pop_tolerance"] <= c["hard_pop_tolerance"] < 1:
        raise ConfigError("need 0 < target_pop_tolerance <= hard_pop_tolerance < 1")
    if c["subdivision_factor"] < 1 + c["hard_pop_tolerance"]:
        raise ConfigError("subdivision_factor must be at least 1 + hard_pop_tolerance (D4-r)")

    exceptions = tuple(c.get("exceptions", ()))
    for exc in exceptions:
        if not isinstance(exc, dict) or not {"dept", "max_tolerance", "justification"} <= set(exc):
            raise ConfigError("each constraints.exceptions entry needs dept, max_tolerance, justification")
        if not exc["justification"]:
            raise ConfigError(f"exception for {exc['dept']} has an empty justification (D5)")

    constraints = {k: v for k, v in c.items() if k != "exceptions"}
    return Config(
        global_=GlobalConfig(**g),
        allocation=AllocationConfig(**a),
        constraints=ConstraintsConfig(**constraints, exceptions=exceptions),
        raw=doc,
    )


def load_config(path: str | Path) -> Config:
    """Read a YAML file from disk and validate it."""
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    if not isinstance(doc, dict):
        raise ConfigError("config root must be a mapping")
    return parse_config(doc)
