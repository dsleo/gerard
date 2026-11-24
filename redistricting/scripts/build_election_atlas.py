"""Build a visual 2024 election snapshot from official, audit-only results."""

from __future__ import annotations

import csv
import json
import zipfile
from collections import Counter
from pathlib import Path

import geopandas as gpd
from shapely.geometry import mapping
from partisan_affiliations import load_affiliations, affiliation_for, PARTY_LFI

ROOT = Path(__file__).resolve().parents[1]
QUARANTINE = ROOT / "data/quarantine/electoral"
BOUNDARIES = ROOT / "data/raw/constituencies/insee_circonscriptions_2022_simplified.zip"
OUTPUT = ROOT / "export/browser/election-2024.js"

# Ministry candidate nuances grouped for map reading. The same grouping is
# documented as a proposed coarse visual grouping in docs/redistricting/blocs.draft.yaml.
GROUPS = {
    "extreme_gauche": {"label": "Extrême gauche", "color": "#8F3441", "hatch": False, "nuances": {"EXG"}},
    "gauche": {"label": "Gauche", "color": "#B85E43", "hatch": False, "nuances": {"COM", "FI", "SOC", "RDG", "VEC", "UG", "DVG", "ECO"}},
    "centre": {"label": "Centre · Ensemble", "color": "#D39476", "hatch": True, "nuances": {"REN", "MDM", "HOR", "ENS", "DVC", "UDI"}},
    "droite": {"label": "Droite · LR et alliés", "color": "#4E7883", "hatch": False, "nuances": {"LR", "DVD", "DSV"}},
    "rn": {"label": "RN · alliés", "color": "#829DA0", "hatch": True, "nuances": {"RN", "REC", "UXD", "EXD"}},
    "autres": {"label": "Autres · régionaux / divers", "color": "#7d8978", "hatch": False, "nuances": {"REG", "DIV"}},
}


def constituency_code(row: dict[str, str]) -> str:
    dept = (row.get("Code département") or "").strip().zfill(2)
    raw = (row.get("Code circonscription législative") or "").strip()
    suffix = raw[-2:].zfill(2)
    return dept + suffix


def winners(path: Path, affiliations=None) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            for i in range(1, 50):
                if (row.get(f"Elu {i}") or "").strip().casefold() != "élu":
                    continue
                code = constituency_code(row)
                found[code] = {
                    "candidate": " ".join(x.strip() for x in (row.get(f"Prénom candidat {i}"), row.get(f"Nom candidat {i}")) if x and x.strip()),
                    "nuance": (row.get(f"Nuance candidat {i}") or "DIV").strip(),
                    "department": (row.get("Code département") or "").strip().zfill(2),
                    "department_name": (row.get("Libellé département") or "").strip(),
                    "constituency": (row.get("Libellé circonscription législative") or "").strip(),
                    "round": "1er tour" if "t1_" in path.name else "2d tour",
                    "votes": (row.get(f"Voix {i}") or "").strip(),
                    "lfi_attached": bool(affiliations is not None and affiliation_for(affiliations, row, i) == PARTY_LFI),
                }
                break
    return found


def classify(nuance: str) -> str:
    for key, group in GROUPS.items():
        if nuance in group["nuances"]:
            return key
    return "autres"


def main() -> None:
    # The 1st-round file supplies the 76 candidates elected immediately; the
    # 2nd-round file supplies the remaining 501 constituency winners.
    first = QUARANTINE / "legislatives_2024_t1_circonscriptions.csv"
    affiliations = load_affiliations(QUARANTINE / "rattachement-candidats-leg-2024.xlsx", first)
    elected = winners(first, affiliations)
    elected.update(winners(QUARANTINE / "legislatives_2024_t2_circonscriptions.csv", affiliations))
    def winner_group(row):
        return 'extreme_gauche' if row['lfi_attached'] else classify(row['nuance'])
    seats = Counter(winner_group(row) for row in elected.values())

    with zipfile.ZipFile(BOUNDARIES) as archive:
        shp = next(n for n in archive.namelist() if n.endswith(".shp"))
        geo = gpd.read_file(f"zip://{BOUNDARIES}!{shp}")
    features = []
    for row in geo.itertuples():
        code = str(row.id_circo).zfill(4)
        result = elected.get(code)
        if not result:
            continue
        group = winner_group(result)
        geom = row.geometry.simplify(0.00012, preserve_topology=True)
        features.append({
            "type": "Feature",
            "properties": {
                "code": code,
                "department": result["department"],
                "department_name": result["department_name"],
                "label": result["constituency"],
                "candidate": result["candidate"],
                "nuance": result["nuance"],
                "group": group,
                "group_label": GROUPS[group]["label"],
                "color": GROUPS[group]["color"],
                "round": result["round"],
                "votes": result["votes"],
            },
            "geometry": mapping(geom),
        })

    payload = {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "election": "Élections législatives des 30 juin et 7 juillet 2024",
            "source": "Ministère de l’Intérieur · résultats définitifs aux circonscriptions",
            "boundary_source": "Insee · contours simplifiés des circonscriptions, millésime 2022",
            "seats": dict(seats),
            "group_meta": {key: {"label": group["label"], "color": group["color"], "hatch": group["hatch"]} for key, group in GROUPS.items()},
            "winner_count": len(elected),
            "mapped_count": len(features),
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        "window.REDISTRICTING_DATA=window.REDISTRICTING_DATA||{};"
        f"window.REDISTRICTING_DATA['election-2024']={json.dumps(payload, ensure_ascii=False, separators=(',', ':'))};",
        encoding="utf-8",
    )
    print(f"Built 2024 election atlas: {len(features)} mapped constituencies, {len(elected)} elected seats")
    print("Seat colors:", dict(seats))


if __name__ == "__main__":
    main()
