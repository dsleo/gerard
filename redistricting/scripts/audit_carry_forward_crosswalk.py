"""Audit whether the stored simplified INSEE constituency contours identify atoms.

This is a diagnostic only. INSEE explicitly warns that its simplified boundaries
cannot determine constituency membership precisely, so the output must never be
used as a legal crosswalk or to clear Gate 1.
"""

from __future__ import annotations

import csv
import pickle
import sys
from pathlib import Path

import geopandas as gpd
from shapely import make_valid, wkb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TARGET_DEPARTMENTS = {"17", "21", "22", "29", "54", "56", "59", "65", "84", "85", "971", "976"}
STATE_DIR = ROOT / "data/processed/gate1"
CONTOURS = ROOT / "data/raw/constituencies/insee_circonscriptions_2022_simplified.zip"
OUT = STATE_DIR / "official_boundary_overlay_audit.csv"


def main() -> None:
    with (STATE_DIR / "sampler_state.pkl").open("rb") as fh:
        state = pickle.load(fh)
    with (STATE_DIR / state["geometry_file"]).open("rb") as fh:
        geometry_wkb = pickle.load(fh)

    atoms = gpd.GeoDataFrame(
        {
            "unit": list(geometry_wkb),
            "department": [state["unit_dept"][unit] for unit in geometry_wkb],
        },
        geometry=[make_valid(wkb.loads(raw)) for raw in geometry_wkb.values()],
        crs="EPSG:2154",
    )
    atoms = atoms[atoms["department"].isin(TARGET_DEPARTMENTS)]
    contours = gpd.read_file(f"zip://{CONTOURS}").to_crs(atoms.crs)
    contours["department"] = contours["dep"].astype(str).str.zfill(2)
    contours["geometry"] = contours.geometry.make_valid()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "unit",
                "department",
                "candidate_constituencies",
                "largest_intersection_share",
                "strictly_inside_one_simplified_contour",
            ],
        )
        writer.writeheader()
        for atom in atoms.itertuples(index=False):
            dept_contours = contours[contours["department"] == atom.department]
            candidates = dept_contours.iloc[
                list(dept_contours.sindex.query(atom.geometry, predicate="intersects"))
            ]
            area = atom.geometry.area
            shares = []
            ids = []
            if area > 0:
                for contour in candidates.itertuples(index=False):
                    share = contour.geometry.intersection(atom.geometry).area / area
                    if share > 1e-9:
                        shares.append(share)
                        ids.append(str(contour.id_circo))
            top_share = max(shares, default=0.0)
            strict = len(shares) == 1 and top_share >= 1.0 - 1e-6
            writer.writerow(
                {
                    "unit": atom.unit,
                    "department": atom.department,
                    "candidate_constituencies": ";".join(sorted(ids)),
                    "largest_intersection_share": f"{top_share:.9f}",
                    "strictly_inside_one_simplified_contour": str(strict).lower(),
                }
            )

    print(f"Wrote diagnostic-only overlay audit: {OUT}")


if __name__ == "__main__":
    main()
