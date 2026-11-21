"""Smoke-check that valid official plans enter sampling as the optimizer's first start.

Run from redistricting/:
  .venv/bin/python scripts/run_blind.py audit_official_seed_integration.py

This uses one ReCom proposal per random candidate and writes no plan files.
"""

from __future__ import annotations

import importlib.util
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redistrict.allocate.policy import D53_FIXED_SEATS  # noqa: E402
from redistrict.ingest.generation import install_generation_guard  # noqa: E402
from redistrict.sample.official import build_official_seed  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
install_generation_guard(ROOT, "audit_official_seed_integration.py")
STATE_PATH = ROOT / "data/processed/gate1/sampler_state.pkl"
CORRESPONDENCE_PATH = ROOT / "data/raw/constituencies/insee_commune_circonscription_2026.xlsx"
COG_COMMUNES_PATH = ROOT / "data/raw/insee_cog2024/v_commune_2024.csv"
COG_MOVEMENTS_PATH = ROOT / "data/raw/insee_cog2024/v_mvt_commune_2024.csv"
SAMPLE_SCRIPT = ROOT / "scripts/sample_departments.py"


def main() -> int:
    state = pickle.loads(STATE_PATH.read_bytes())
    spec = importlib.util.spec_from_file_location("sample_departments", SAMPLE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load sampler entry point")
    sampler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sampler)

    checked = []
    for dept in sorted(set(state["dept_pop"]) - set(D53_FIXED_SEATS)):
        official = build_official_seed(
            dept, state, CORRESPONDENCE_PATH, COG_COMMUNES_PATH, COG_MOVEMENTS_PATH
        )
        if official["status"] != "VALID_PROJECT_START":
            continue
        sampled = sampler.job(dept, seed=42, replicates=1, steps=1)
        first = sampled["plans"][0]
        if first.get("source") != "official_current" or not first.get("valid"):
            raise AssertionError(f"{dept}: valid official plan was not inserted first")
        expected_units = {u for u in state["units"] if state["unit_dept"][u] == dept}
        if set(first["assignment"]) != expected_units:
            raise AssertionError(f"{dept}: official starting plan does not cover all model units")
        checked.append(dept)
    print(f"official seed integration: PASS for {len(checked)} departments: {checked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
