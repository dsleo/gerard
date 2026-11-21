"""Map official population references onto the COG 2024 units used by ADMIN EXPRESS 2024.

INSEE 2021 is used for metropolitan France and DROM 971-974. Mayotte uses its
separate official 2017 commune table, the latest official commune population
available for the 2024 snapshot (D31).

Rules (INSEE COG 2024, MOD codes in v_mvt_commune_2024.csv):
  R1  2021 code is a commune (COM) in COG 2024             -> same unit
  R2  2021 code is a commune déléguée (COMD) in COG 2024   -> its parent (COMPARENT)
  R3  2021 code no longer exists in COG 2024                -> follow the movement row (COM_AV -> COM_AP)
  R4  a 2021 commune's population includes communes déléguées that are now separate
      communes (COM) in COG 2024 (commune rétablie, MOD 21): subtract them from the
      parent and give them their own 2021 population
Population is conserved across units covered by the INSEE 2021 file. Mayotte's
separate 2017 total is checked independently because its reference year differs.

Outputs (data/processed/):
  cog2024_mapping.csv       one row per population contribution, with source code, population, target, and rule
  cog2024_population.csv    one row per 2024 unit, with population and explicit reference-vintage exception

Run from redistricting/:  .venv/bin/python scripts/run_blind.py map_to_cog2024.py
"""

from __future__ import annotations

import io
import zipfile
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from redistrict.ingest.generation import install_generation_guard

ROOT = Path(__file__).resolve().parents[1]
install_generation_guard(ROOT, "map_to_cog2024.py")
RAW = ROOT / "data/raw"
OUT = ROOT / "data/processed"
DROM = {"971", "972", "973", "974", "976"}


def load():
    z = zipfile.ZipFile(RAW / "population/populations_legales_2021_ensemble.zip")
    read = lambda name: pd.read_csv(io.BytesIO(z.read(name)), sep=";", dtype=str, encoding="utf-8")
    pop = read("donnees_communes.csv")
    pop["PMUN"] = pop["PMUN"].str.replace(" ", "").astype(int)
    dl = read("donnees_communes_deleguees.csv")
    dl["PMUN"] = dl["PMUN"].str.replace(" ", "").astype(int)

    cog = pd.read_csv(RAW / "insee_cog2024/v_commune_2024.csv", dtype=str, keep_default_na=False)
    mvt = pd.read_csv(RAW / "insee_cog2024/v_mvt_commune_2024.csv", dtype=str, keep_default_na=False)
    mayotte = pd.read_excel(RAW / "population/mayotte_population_reference_2017.xlsx",
                            sheet_name="Communes", header=None, skiprows=3, dtype=object)
    mayotte = mayotte.iloc[:, [0, 2]].dropna()
    mayotte.columns = ["label", "PMUN"]
    mayotte = mayotte[mayotte["label"].astype(str).str.match(r"^\d{2} - ")].copy()
    mayotte["code"] = mayotte["label"].str.extract(r"^(\d{2})")[0].map(lambda n: "976" + n)
    mayotte["name"] = mayotte["label"].str.replace(r"^\d{2} - ", "", regex=True)
    mayotte["PMUN"] = mayotte["PMUN"].astype(int)
    return pop, dl, cog, mvt, mayotte


def main() -> None:
    pop, dl, cog, mvt, mayotte = load()

    # keep metropolitan communes (ADMIN EXPRESS 2024 currently available is FXX)
    is_arr = pop["Commune"].str.contains("Arrondissement", na=False)
    units = pop[~is_arr].copy()  # all communes in the INSEE file (metropolitan + DROM 971-974; Mayotte absent)
    arr = pop[is_arr].copy()  # municipal arrondissements map to themselves (verified 45/45)

    cog_com = cog[cog["TYPECOM"] == "COM"].set_index("COM")
    cog_comd = cog[cog["TYPECOM"] == "COMD"].drop_duplicates("COM").set_index("COM")
    move_to = mvt.drop_duplicates("COM_AV", keep="last").set_index("COM_AV")["COM_AP"].to_dict()

    def unit_2024(code: str) -> tuple[str, str]:
        if code in cog_com.index:
            return code, "R1 same commune"
        if code in cog_comd.index:
            return cog_comd.loc[code, "COMPARENT"], "R2 commune déléguée -> parent"
        if code in move_to:
            return move_to[code], "R3 movement (changed code or merged)"
        return "", "UNMATCHED"

    # INSEE's 2021 communes déléguées table gives the component populations for
    # the 2021 Les Hauts-Talican total. In COG 2024, Beaumont-les-Nonains is
    # again a commune (60054), while La Neuville-Garnier and Villotran are
    # delegated communes of Les Hauts-Talican (60694). Preserve the official
    # 2021 reference year and allocate each component to its 2024 territorial
    # unit. The source values must sum to the parent commune total.
    component_splits = {"60054": {"60054": "60054", "60455": "60694", "60694": "60694"}}
    component_child_codes = {child for assignments in component_splits.values() for child in assignments}
    component_rows = {code: group for code, group in dl.groupby("COMP")}
    split_parts: dict[str, dict[str, int]] = {}
    for parent, assignments in component_splits.items():
        parts = component_rows[parent]
        parent_total = int(units.loc[units["COM"] == parent, "PMUN"].iloc[0])
        if int(parts["PMUN"].sum()) != parent_total:
            raise ValueError(f"INSEE delegated populations do not sum to {parent} total")
        split_parts[parent] = {
            target: int(parts.loc[parts["COM"].isin([child for child, dest in assignments.items() if dest == target]), "PMUN"].sum())
            for target in set(assignments.values())
        }

    # R4: children of a 2021 commune that are communes (COM) again in 2024
    children = dl.copy()
    carve: dict[str, int] = {}
    for _, row in children.iterrows():
        parent_2021, child = row["COMP"], row["COM"]
        if parent_2021 in component_splits or child in component_splits:
            continue
        child_unit, _ = unit_2024(child)
        parent_unit, _ = unit_2024(parent_2021)
        if child in cog_com.index and child_unit != parent_unit:
            carve[parent_2021] = carve.get(parent_2021, 0) + row["PMUN"]

    rows = []
    for _, r in units.iterrows():
        code = r["COM"]
        target, rule = unit_2024(code)
        if code in component_splits:
            rows.append({"code_2021": code, "name_2021": r["Commune"], "pmun_2021": r["PMUN"],
                         "unit_2024": code, "pop_contribution": split_parts[code][code],
                         "rule": "R5 INSEE commune-déléguée component population (millésime 2021)"})
            assignments = component_splits[code]
            for child, dest in assignments.items():
                if child == code:
                    continue
                part = component_rows[code].loc[component_rows[code]["COM"] == child].iloc[0]
                rows.append({"code_2021": child, "name_2021": part["Commune"], "pmun_2021": part["PMUN"],
                             "unit_2024": dest, "pop_contribution": int(part["PMUN"]),
                             "rule": f"R5 INSEE commune-déléguée component population (millésime 2021) -> {dest}"})
            continue
        exclusive = r["PMUN"] - carve.get(code, 0)
        if carve.get(code):
            rule += f" (minus {carve[code]} for communes rétablies, R4)"
        rows.append({"code_2021": code, "name_2021": r["Commune"], "pmun_2021": r["PMUN"],
                     "unit_2024": target, "pop_contribution": exclusive, "rule": rule})
    # children that are now communes: give them their own 2021 population
    for _, row in children.iterrows():
        child = row["COM"]
        if child in cog_com.index and child not in set(units["COM"]) and child not in component_child_codes:
            rows.append({"code_2021": child, "name_2021": row["Commune"], "pmun_2021": row["PMUN"],
                         "unit_2024": child, "pop_contribution": row["PMUN"],
                         "rule": "R4 commune rétablie (own population from communes déléguées file)"})
    for _, r in arr.iterrows():
        rows.append({"code_2021": r["COM"], "name_2021": r["Commune"], "pmun_2021": r["PMUN"],
                     "unit_2024": r["COM"], "pop_contribution": r["PMUN"], "rule": "arrondissement municipal"})

    # Mayotte has no commune-level entry in the 2021 national release. Its 2017
    # exhaustive census remained the latest official commune population used for
    # the 2024 snapshot; keep the vintage exception explicit and separate.
    if len(mayotte) != 17 or int(mayotte["PMUN"].sum()) != 256_518:
        raise ValueError("unexpected Mayotte 2017 population table; expected 17 communes and 256,518 residents")
    for row in mayotte.itertuples(index=False):
        rows.append({"code_2021": row.code, "name_2021": row.name, "pmun_2021": int(row.PMUN),
                     "unit_2024": row.code, "pop_contribution": int(row.PMUN),
                     "rule": "R6 latest official Mayotte commune population available for 2024 snapshot (reference 2017)"})

    mapping = pd.DataFrame(rows)
    pop_2024 = (mapping[(mapping["unit_2024"] != "") & mapping["pop_contribution"].notna()]
                .groupby("unit_2024", as_index=False)["pop_contribution"].sum()
                .rename(columns={"pop_contribution": "pop_2024"}))
    pop_2024["status"] = "ok"
    OUT.mkdir(parents=True, exist_ok=True)
    mapping.to_csv(OUT / "cog2024_mapping.csv", index=False)
    pop_2024.to_csv(OUT / "cog2024_population.csv", index=False)

    # checks
    total_2021 = int(units["PMUN"].sum() + arr["PMUN"].sum())
    total_2024_nonmayotte = int(pop_2024.loc[~pop_2024["unit_2024"].str.startswith("976"), "pop_2024"].fillna(0).sum())
    total_mayotte = int(pop_2024.loc[pop_2024["unit_2024"].str.startswith("976"), "pop_2024"].sum())
    total_2024 = total_2024_nonmayotte + total_mayotte
    unresolved_pop = int(units[units["COM"].isin(pop_2024.loc[pop_2024["status"] == "UNRESOLVED", "unit_2024"])]["PMUN"].sum())
    unmatched = mapping[mapping["unit_2024"] == ""]
    print(f"2021 total (metropolitan + DROM 971-974):     {total_2021:,}")
    print(f"same-vintage mapped total (excluding 976):    {total_2024_nonmayotte:,}")
    print(f"Mayotte latest official reference-2017 total:  {total_mayotte:,}")
    print(f"combined modeled total (mixed vintages):       {total_2024:,}")
    print(f"unresolved population total:                  {unresolved_pop:,}")
    print(f"conservation check excluding Mayotte:         {total_2024_nonmayotte + unresolved_pop - total_2021:,}")
    print(f"population-contribution rows: {len(mapping)}, unmatched: {len(unmatched)}")
    if len(unmatched):
        print(unmatched[["code_2021", "name_2021"]].to_string(index=False))
    rules = mapping["rule"].str.split(" ").str[0].value_counts().to_dict()
    print("rules applied:", rules)
    print(f"wrote {OUT / 'cog2024_mapping.csv'} and {OUT / 'cog2024_population.csv'}")


if __name__ == "__main__":
    main()
