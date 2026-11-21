"""Build an offline map snapshot from the Assembly's current open-data roster."""

from __future__ import annotations

import io
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen

import geopandas as gpd
from shapely.geometry import Polygon, mapping
from shapely.ops import unary_union

from build_election_atlas import BOUNDARIES, QUARANTINE, winners

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "export/browser/current-assembly.js"
ASSEMBLY_DATA = "https://data.assemblee-nationale.fr/static/openData/repository/17/amo/deputes_actifs_mandats_actifs_organes/AMO10_deputes_actifs_mandats_actifs_organes.json.zip"
MIN_DISPLAY_AREA = 0.0001  # Drop sub-pixel islands and holes at national-map scale.


def clean_display_geometry(geometry):
    """Remove tiny rings that render as stray ink strokes in the national view."""
    polygons = [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)
    cleaned = []
    for polygon in polygons:
        if polygon.area < MIN_DISPLAY_AREA:
            continue
        holes = [ring.coords for ring in polygon.interiors
                 if Polygon(ring).area >= MIN_DISPLAY_AREA]
        candidate = Polygon(polygon.exterior.coords, holes)
        if not candidate.is_empty:
            cleaned.append(candidate)
    if not cleaned:
        largest = max(polygons, key=lambda polygon: polygon.area)
        return Polygon(largest.exterior.coords)
    return unary_union(cleaned)


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def read_assembly_snapshot() -> tuple[list[dict], dict[str, dict]]:
    request = Request(ASSEMBLY_DATA, headers={"User-Agent": "AtlasCivique/1.0 (local research interface)"})
    with urlopen(request, timeout=40) as response:
        archive_bytes = response.read()
    archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    actors = {}
    organs = {}
    for name in archive.namelist():
        if name.startswith("json/acteur/") and name.endswith(".json"):
            actor = json.loads(archive.read(name).decode("utf-8"))["acteur"]
            actor_id = actor["uid"]["#text"]
            actors[actor_id] = actor
        elif name.startswith("json/organe/") and name.endswith(".json"):
            organ = json.loads(archive.read(name).decode("utf-8"))["organe"]
            organs[organ["uid"]] = organ

    deputies = []
    for actor in actors.values():
        mandates = as_list((actor.get("mandats") or {}).get("mandat"))
        mandate = next((m for m in mandates if m.get("typeOrgane") == "ASSEMBLEE"
                        and m.get("legislature") == "17" and m.get("dateFin") is None), None)
        if not mandate:
            continue
        ident = actor["etatCivil"]["ident"]
        place = mandate.get("mandature", {}).get("placeHemicycle")
        location = mandate.get("election", {}).get("lieu", {})
        group_mandate = next((m for m in mandates if m.get("typeOrgane") == "GP"
                              and m.get("legislature") == "17" and m.get("dateFin") is None), None)
        group = organs.get(group_mandate.get("organes", {}).get("organeRef")) if group_mandate else None
        label = (group or {}).get("libelle") or "Non inscrit"
        color = (group or {}).get("couleurAssociee") or "#8f8979"
        code_dep = str(location.get("numDepartement") or "").zfill(2)
        code_circo = str(location.get("numCirco") or "").zfill(2)
        code = f"{code_dep}{code_circo}" if code_dep and code_circo else None
        deputies.append({
            "name": " ".join(x for x in (ident.get("prenom"), ident.get("nom")) if x),
            "group": label,
            "abbreviation": (group or {}).get("libelleAbrege") or "NI",
            "color": color,
            "code": code,
            "place": int(place) if str(place or "").isdigit() else None,
        })
    return deputies, organs


def main() -> None:
    deputies, _ = read_assembly_snapshot()
    current_by_code = {d["code"]: d for d in deputies if d["code"]}
    group_counts = Counter(d["group"] for d in deputies)
    group_meta: dict[str, dict] = {}
    for deputy in deputies:
        group_meta.setdefault(deputy["group"], {
            "label": deputy["group"], "abbreviation": deputy["abbreviation"], "color": deputy["color"],
        })

    past = winners(QUARANTINE / "legislatives_2024_t1_circonscriptions.csv")
    past.update(winners(QUARANTINE / "legislatives_2024_t2_circonscriptions.csv"))
    department_names = {row["department"]: row["department_name"] for row in past.values()
                        if row.get("department") and row.get("department_name")}
    with zipfile.ZipFile(BOUNDARIES) as archive:
        shp = next(n for n in archive.namelist() if n.endswith(".shp"))
        geo = gpd.read_file(f"zip://{BOUNDARIES}!{shp}")

    features = []
    mapped = 0
    for row in geo.itertuples():
        code = str(row.id_circo).zfill(4)
        member = current_by_code.get(code)
        historical = past.get(code)
        if member:
            mapped += 1
            candidate, group, color, status = member["name"], member["group"], member["color"], "pourvu"
        else:
            candidate, group, color, status = "Siège vacant", "Siège vacant", "#e4dac3", "vacant"
        geom = clean_display_geometry(row.geometry.simplify(0.0007, preserve_topology=True))
        features.append({
            "type": "Feature",
            "properties": {
                "code": code, "department": str(row.dep).zfill(2), "label": row.libelle,
                "department_name": department_names.get(str(row.dep).zfill(2), str(row.dep)),
                "candidate": candidate, "group": group, "group_label": group,
                "color": color, "status": status,
                "election_nuance_2024": historical["nuance"] if historical else "",
            },
            "geometry": mapping(geom),
        })

    meta = {
        "source": "Assemblée nationale · données ouvertes · députés actifs, XVIIe législature",
        "source_url": ASSEMBLY_DATA,
        "group_source_url": "https://www2.assemblee-nationale.fr/deputes/liste/groupe-politique",
        "snapshot_date": "2026-11-18",
        "members": len(deputies),
        "vacant": max(0, 577 - len(deputies)),
        "mapped_current": mapped,
        "mapped_department_seats": len(features),
        "group_counts": dict(group_counts),
        "group_meta": group_meta,
        "hemicycle": sorted(deputies, key=lambda d: d["place"] if d["place"] is not None else 1000),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"type": "FeatureCollection", "features": features, "meta": meta}
    OUTPUT.write_text(
        "window.REDISTRICTING_DATA=window.REDISTRICTING_DATA||{};"
        f"window.REDISTRICTING_DATA['current-assembly']={json.dumps(payload, ensure_ascii=False, separators=(',', ':'))};",
        encoding="utf-8",
    )
    print(json.dumps({"members": len(deputies), "mapped_current": mapped, "mapped_department_seats": len(features),
                      "vacant": meta["vacant"], "group_counts": dict(group_counts)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
