"""Export symmetric department-level map distances from the official map.

Each commune/model unit is assigned to the constituency with the largest
geometric overlap. The score averages the split in each direction so both
splitting and merging current constituencies contribute to the distance.
"""
from __future__ import annotations

import base64
import gzip
import json
import pickle
import re
from collections import defaultdict
from pathlib import Path

from pyproj import Transformer
from shapely import make_valid, wkb
from shapely.geometry import shape
from shapely.ops import transform

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
OUT = ROOT / "export/browser/department-distances.js"
STATE = ROOT / "data/processed/gate1/sampler_state.pkl"
GEOMETRIES = ROOT / "data/processed/gate1/unit_geometry_wkb.pkl"
SCENARIO_FILES = {
    "lfi": "22_lfi_expected.json",
    "left": "22_left_expected.json",
    "centre": "22_centre_expected.json",
    "right": "22_right_expected.json",
    "far_right": "22_far_right_expected.json",
}
METRO = {f"{n:02d}" for n in range(1, 96)} | {"2A", "2B"}
TO_2154 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True).transform


def read_snapshot(path: Path, key: str) -> dict:
    text = path.read_text(encoding="utf-8")
    marker = f"window.REDISTRICTING_DATA['{key}']="
    payload = text.split(marker, 1)[1].strip().rstrip(";\n")
    match = re.search(r'atob\("([A-Za-z0-9+/=]+)"\)', payload)
    if match:
        return json.loads(gzip.decompress(base64.b64decode(match.group(1))))
    return json.loads(payload)


def map_assignments(features: list[dict], units: list[str], geometries: dict[str, bytes],
                    number_property: str) -> dict[str, dict[str, int]]:
    districts: dict[str, list[tuple[int, object]]] = defaultdict(list)
    for feature in features:
        props = feature["properties"]
        department = str(props.get("department", props.get("dept", "")))
        if department not in METRO:
            continue
        if number_property == "code":
            code = str(props["code"])
            if not code.startswith(department):
                continue
            number = int(code[len(department):])
        else:
            number = int(props[number_property])
        geom = transform(TO_2154, shape(feature["geometry"]))
        if not geom.is_valid:
            geom = make_valid(geom)
        districts[department].append((number, geom))

    result: dict[str, dict[str, int]] = {}
    for department, features in districts.items():
        assigned = {}
        for unit in units:
            unit_department = unit[:3] if unit.startswith(("971", "972", "973", "974", "976")) else unit[:2]
            if unit_department != department:
                continue
            geom = wkb.loads(geometries[unit])
            best_number, best_area = None, 0.0
            for number, district_geom in features:
                area = geom.intersection(district_geom).area
                if area > best_area:
                    best_number, best_area = number, area
            if best_number is not None:
                assigned[unit] = best_number
        result[department] = assigned
    return result


def score_department(old: dict[str, int], new: dict[str, int]) -> dict:
    shared = set(old) & set(new)
    old_totals: dict[int, int] = defaultdict(int)
    new_totals: dict[int, int] = defaultdict(int)
    overlap: dict[tuple[int, int], int] = defaultdict(int)
    for unit in shared:
        source, destination = old[unit], new[unit]
        old_totals[source] += 1
        new_totals[destination] += 1
        overlap[(source, destination)] += 1
    if not shared:
        return {"score": 0.0, "units": 0}
    distance = sum(
        0.5 * (
            1 - overlap[(old[unit], new[unit])] / old_totals[old[unit]]
            + 1 - overlap[(old[unit], new[unit])] / new_totals[new[unit]]
        )
        for unit in shared
    ) / len(shared)
    return {"score": distance, "units": len(shared)}


def finish_map(scores: dict[str, dict]) -> dict:
    ordered = sorted(scores.items(), key=lambda item: (item[1]["score"], item[0]))
    values = [data["score"] for _, data in ordered]
    result = {code: dict(data) for code, data in scores.items()}
    for code, data in result.items():
        data["rank"] = 1 + sum(score < data["score"] - 1e-12 for score in values)
        data["rank_ties"] = sum(abs(score - data["score"]) <= 1e-12 for score in values)
        farther = sum(score > data["score"] + 1e-12 for score in values)
        data["closer_than_percent"] = round(100 * farther / max(1, len(values) - 1))
    return {
        "department_count": len(result),
        "department_average": sum(values) / len(values) if values else 0.0,
        "departments": result,
    }


def main() -> None:
    state = pickle.loads(STATE.read_bytes())
    geometries = pickle.loads(GEOMETRIES.read_bytes())
    official_data = read_snapshot(ROOT / "export/browser/election-2024.js", "election-2024")
    neutral_data = read_snapshot(ROOT / "export/browser/projection-2026.js", "projection-2026")
    official = map_assignments(official_data["features"], state["units"], geometries, "code")
    neutral = map_assignments(neutral_data["map"]["features"], state["units"], geometries, "district_number")
    maps = {}
    maps["neutral"] = finish_map({
        department: score_department(official[department], neutral[department])
        for department in sorted(METRO) if department in official and department in neutral
    })

    scenarios = {}
    for scenario, filename in SCENARIO_FILES.items():
        plan = json.loads((REPO / "docs/redistricting" / filename).read_text(encoding="utf-8"))
        new_by_department = {department: dict(assignments) for department, assignments in official.items()}
        for item in plan["selected"]:
            department = item["department"]
            # The saved plan uses zero-based district IDs; browser maps use 1-based numbers.
            new_by_department[department] = {unit: int(district) + 1
                                             for unit, district in item["assignment"].items()}
        scenarios[scenario] = finish_map({
            department: score_department(official[department], new_by_department[department])
            for department in sorted(METRO) if department in official and department in new_by_department
        })

    payload = {
        "maps": maps,
        "partisan": scenarios,
        "definition": "For each model unit U, average (1 - overlap/old constituency size) and (1 - overlap/new constituency size), counting model units. A department score is the mean of its unit scores. The displayed distance is the unweighted mean of department scores, so each metropolitan department has equal weight. The department percentile is the percentage of other departments with a greater distance; ties are excluded.",
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded = base64.b64encode(gzip.compress(raw, compresslevel=9, mtime=0)).decode("ascii")
    OUT.write_text(
        "window.REDISTRICTING_DATA=window.REDISTRICTING_DATA||{};"
        "window.REDISTRICTING_DATA['department-distances']=(async()=>{"
        f'const b=Uint8Array.from(atob("{encoded}"),c=>c.charCodeAt(0));'
        "const d=new DecompressionStream('gzip');"
        "return JSON.parse(await new Response(new Blob([b]).stream().pipeThrough(d)).text())})();\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes), {len(maps['neutral']['departments'])} departments")


if __name__ == "__main__":
    main()
