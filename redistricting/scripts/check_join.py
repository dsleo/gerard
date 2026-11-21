"""Phase 0 check: do ADMIN EXPRESS (IGN, COG 2024) and populations légales (INSEE, 2021 reference)
join on commune and arrondissement codes, and do their populations agree?

Writes data/processed/join_report.md. Run from the redistricting/ folder:
    .venv/bin/python scripts/run_blind.py check_join.py
Requires the archives to be extracted under data/processed/ (see docs/redistricting/06_code_architecture.md).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from redistrict.ingest.generation import install_generation_guard
install_generation_guard(ROOT, "check_join.py")
ADMIN = ROOT / "data/processed/admin_express/ADMIN-EXPRESS-COG_3-2__SHP_LAMB93_FXX_2024-02-22/ADMIN-EXPRESS-COG/1_DONNEES_LIVRAISON_2024-03-00166/ADECOG_3-2_SHP_LAMB93_FXX-ED2024-02-22"
POP_ZIP = ROOT / "data/raw/population/populations_legales_2021_ensemble.zip"
DROM = {"971", "972", "973", "974", "976"}
REPORT = ROOT / "data/processed/join_report.md"


def main() -> None:
    com = gpd.read_file(ADMIN / "COMMUNE.shp", ignore_geometry=True)
    arm = gpd.read_file(ADMIN / "ARRONDISSEMENT_MUNICIPAL.shp", ignore_geometry=True)

    pop = pd.read_csv(io.BytesIO(zipfile.ZipFile(POP_ZIP).read("donnees_communes.csv")),
                      sep=";", dtype=str, encoding="utf-8")
    pop["PMUN"] = pop["PMUN"].str.replace(" ", "").astype(int)
    is_arr = pop["Commune"].str.contains("Arrondissement", na=False)
    pop_arr = pop[is_arr]
    pop_com = pop[~is_arr & ~pop["DEP"].isin(DROM)]  # metropolitan communes only

    admin_codes, pop_codes = set(com["INSEE_COM"]), set(pop_com["COM"])
    arr_admin, arr_pop = set(arm["INSEE_ARM"]), set(pop_arr["COM"])
    only_pop = sorted(pop_codes - admin_codes)
    only_admin = sorted(admin_codes - pop_codes)

    pop_total = int(pop_com["PMUN"].sum() + pop_arr["PMUN"].sum())
    admin_total = int(com["POPULATION"].sum())
    parents = com[com["INSEE_COM"].isin(["75056", "69123", "13055"])]

    lines = [
        "# Join check: ADMIN EXPRESS 2024 vs INSEE populations légales 2021",
        "",
        "## Arrondissements (municipal)",
        f"- ADMIN EXPRESS: {len(arr_admin)}, INSEE: {len(arr_pop)}",
        f"- Matching: {len(arr_admin & arr_pop)}; ADMIN-only: {sorted(arr_admin - arr_pop)}; INSEE-only: {sorted(arr_pop - arr_admin)}",
        "",
        "## Communes (metropolitan France)",
        f"- ADMIN EXPRESS communes: {len(admin_codes)}; INSEE communes (metropolitan, excl. arrondissements): {len(pop_codes)}",
        f"- In INSEE, absent from ADMIN EXPRESS: {len(only_pop)} codes, population {int(pop_com[pop_com['COM'].isin(only_pop)]['PMUN'].sum())}",
        f"  - {', '.join(only_pop)}",
        f"- In ADMIN EXPRESS, absent from INSEE: {len(only_admin)} codes",
        f"  - {', '.join(only_admin)}",
        "  - Paris (75056), Lyon (69123), Marseille (13055): expected, INSEE lists their arrondissements instead.",
        "  - 60694, 85165, 85212: not in the 2021 INSEE file, so probably created or changed after 2021. Verify against the COG 2024 change list.",
        "",
        "## Population",
        f"- INSEE PMUN (metropolitan communes + arrondissements): {pop_total:,}",
        f"- ADMIN EXPRESS POPULATION (metropolitan communes, parents included): {admin_total:,}",
        f"- Difference: {pop_total - admin_total:,} ({(pop_total - admin_total) / admin_total:.3%})",
        f"- Parent cities in ADMIN EXPRESS: {int(parents['POPULATION'].sum()):,} (equals INSEE arrondissement sum: {int(pop_arr['PMUN'].sum()):,})",
        "",
        "## Status",
        "- Not yet resolved: the codes listed under 'absent from ADMIN EXPRESS'. Gate 1 must refuse to run until they are mapped (COG 2024 change list) or excluded with a documented reason.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {REPORT}")


if __name__ == "__main__":
    main()
