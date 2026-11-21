"""Build and validate an official-plan seed where the INSEE correspondence is exact.

The INSEE commune/circonscription table identifies whole-commune membership and
marks split communes, but does not assign the pieces within a split commune. This
module uses only whole-commune rows; it never guesses a split from simplified maps.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from redistrict.validate.constraints import validate_plan
from redistrict.metrics.population import epci_split_term


@lru_cache(maxsize=1)
def _official_rows_by_department(path: str) -> dict[str, pd.DataFrame]:
    frame = pd.read_excel(path, sheet_name="table", dtype={
        "DEP": str, "COMMUNE_RESID": str, "circo": str, "type_com": str,
    })
    frame["DEP"] = frame["DEP"].astype(str).str.strip()
    frame["DEP"] = frame["DEP"].map(lambda value: value.zfill(2) if value.isdigit() and len(value) < 2 else value)
    frame["COMMUNE_RESID"] = frame["COMMUNE_RESID"].astype(str).str.strip().str.zfill(5)
    def normalize_circle(row: pd.Series) -> str:
        department = str(row["DEP"])
        if pd.isna(row["circo"]):
            return ""
        raw = str(row["circo"]).strip()
        if not raw or raw.casefold() in {"nan", "none"}:
            return ""
        if raw.startswith(department):
            return raw
        if department.isdigit():
            return raw.zfill(5)
        return department + raw[-2:].zfill(2)

    frame["circo"] = frame.apply(normalize_circle, axis=1)
    frame["type_com"] = frame["type_com"].astype(str).str.strip().str.casefold()
    return {str(department): group for department, group in frame.groupby("DEP", sort=False)}


@lru_cache(maxsize=2)
def _source_to_current(cog_path: str, movements_path: str) -> dict[str, set[str]]:
    """Translate 2021 COG commune codes to current 2024 model units.

    The population mapping is not the correct source for this join: it converts
    2021-reference population values to 2024 geography, so it omits 2021 COG
    component codes that were merged into a current commune. Use the official
    COG 2024 inventory and its complete movement history instead.
    """
    cog = pd.read_csv(cog_path, dtype=str, keep_default_na=False)
    movements = pd.read_csv(movements_path, dtype=str, keep_default_na=False)
    current: dict[str, set[str]] = {}
    for row in cog.itertuples(index=False):
        code = str(row.COM).strip()
        kind = str(row.TYPECOM).strip()
        if kind in {"COM", "ARM"}:
            current.setdefault(code, set()).add(code)
        elif kind in {"COMD", "COMA"}:
            parent = str(row.COMPARENT).strip()
            if parent:
                current.setdefault(code, set()).add(parent)

    outgoing: dict[str, list[str]] = {}
    later = movements[movements["DATE_EFF"].astype(str) > "2021-01-01"]
    for old, new in zip(later["COM_AV"], later["COM_AP"]):
        old, new = str(old).strip(), str(new).strip()
        if old and new and old != new:
            outgoing.setdefault(old, []).append(new)

    def resolve(code: str, seen: frozenset[str] = frozenset()) -> set[str]:
        if code in seen:
            return set()
        if code in current:
            return set(current[code])
        targets: set[str] = set()
        for successor in outgoing.get(code, []):
            targets.update(resolve(successor, seen | {code}))
        return targets

    mapping: dict[str, set[str]] = {}
    # The INSEE correspondence explicitly documents that its commune codes are
    # in COG geography 2021. Mapping every source code through COG's movements
    # handles communes that became delegated/associated communes by COG 2024.
    for code in set(movements["COM_AV"].astype(str)) | set(current):
        resolved = resolve(code)
        if resolved:
            mapping[code] = resolved
    return mapping


def _parent_code(unit: str) -> str:
    # IRIS pieces inherit a commune-level assignment only when that whole
    # commune is assigned to one constituency by the official correspondence.
    return unit[:5] if len(unit) >= 9 else unit


def build_official_seed(
    department: str,
    state: dict,
    correspondence_path: Path,
    cog_communes_path: Path,
    cog_movements_path: Path,
    tolerance: float = 0.20,
    model_units: list[str] | None = None,
) -> dict:
    """Return a diagnostic and, when representable, the official unit assignment.

    The official assignment is a valid optimizer candidate only when the INSEE
    table assigns every current model unit exactly, the constituency count matches
    the project's seats, and the shared plan validator passes.
    """
    department = str(department)
    dept_units = sorted(model_units if model_units is not None else
                        (u for u in state["units"] if state["unit_dept"][u] == department))
    unit_set = set(dept_units)
    by_parent: dict[str, list[str]] = {}
    for unit in dept_units:
        by_parent.setdefault(_parent_code(unit), []).append(unit)

    official_by_department = _official_rows_by_department(str(correspondence_path.resolve()))
    rows = official_by_department.get(department)
    if rows is None or rows.empty:
        return {"status": "NO_OFFICIAL_ROWS", "candidate": None,
                "detail": "INSEE correspondence has no rows for this department."}

    source_to_current = _source_to_current(
        str(cog_communes_path.resolve()), str(cog_movements_path.resolve())
    )

    assigned: dict[str, str] = {}
    partial_communes: set[str] = set()
    unmapped_communes: set[str] = set()
    no_constituency_communes: set[str] = set()
    conflicts: set[str] = set()

    for row in rows.itertuples(index=False):
        source_code, circle, kind = str(row.COMMUNE_RESID), str(row.circo), str(row.type_com)
        if not circle:
            no_constituency_communes.add(source_code)
            continue
        targets = source_to_current.get(source_code, set())
        if not targets:
            unmapped_communes.add(source_code)
            continue
        if kind == "partiel":
            partial_communes.add(source_code)
            continue
        if kind != "entière":
            unmapped_communes.add(source_code)
            continue
        for target in targets:
            for unit in by_parent.get(target, []):
                previous = assigned.get(unit)
                if previous is not None and previous != circle:
                    conflicts.add(unit)
                else:
                    assigned[unit] = circle

    missing_units = sorted(unit_set - assigned.keys())
    extra_units = sorted(assigned.keys() - unit_set)
    official_ids = sorted(value for value in set(rows["circo"]) if value)
    project_seats = int(state["seats"][department])
    diagnostic = {
        "department": department,
        "status": "INCOMPLETE_CROSSWALK",
        "candidate": None,
        "units": len(unit_set),
        "assigned_units": len(assigned),
        "missing_units": len(missing_units),
        "extra_units": len(extra_units),
        "partial_communes": len(partial_communes),
        "unmapped_communes": len(unmapped_communes),
        "no_constituency_communes": len(no_constituency_communes),
        "conflicting_units": len(conflicts),
        "official_constituencies": len(official_ids),
        "project_seats": project_seats,
        "examples": {
            "partial_communes": sorted(partial_communes)[:8],
            "unmapped_communes": sorted(unmapped_communes)[:8],
            "no_constituency_communes": sorted(no_constituency_communes)[:8],
            "missing_units": missing_units[:8],
            "conflicting_units": sorted(conflicts)[:8],
        },
        "source": "INSEE commune–circonscription correspondence, June 2026; only `entière` rows used",
    }
    if missing_units or extra_units or conflicts or unmapped_communes or partial_communes:
        return diagnostic

    official_seats = len(official_ids)
    id_to_label = {circle: idx for idx, circle in enumerate(official_ids)}
    assignment = {unit: id_to_label[circle] for unit, circle in assigned.items()}
    adjacency = {
        unit: set(v for v in state["certification_edges"].get(unit, ()) if v in unit_set)
        for unit in unit_set
    }
    checked = validate_plan(
        assignment,
        unit_set,
        state["pops"],
        adjacency,
        int(state["dept_pop"][department]) / official_seats,
        tolerance,
    )
    violations = [{"rule": v.rule, "detail": v.detail} for v in checked.violations]
    status = "VALID_PROJECT_START" if not violations and official_seats == project_seats else (
        "VALID_OFFICIAL_SEAT_COUNT_MISMATCH" if not violations else "FAILS_PROJECT_CURRENT_RULES"
    )
    diagnostic.update({
        "status": status,
        "candidate": assignment if status == "VALID_PROJECT_START" else None,
        "official_assignment_checked": True,
        "official_seats": official_seats,
        "official_id_to_label": id_to_label,
        "max_population_deviation": checked.max_deviation,
        "l_epci": epci_split_term(assignment, state["epci_of"]),
        "violations": violations,
    })
    if official_seats != project_seats:
        diagnostic["detail"] = (
            f"The official plan was checked with {official_seats} constituencies and passes/fails its constraints; "
            f"the current project allocation requires {project_seats} seats, so it cannot seed this run unchanged."
        )
    return diagnostic
