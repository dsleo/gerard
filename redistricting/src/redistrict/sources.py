"""Registry of input datasets.

Each entry says what the dataset is, where it comes from, whether the engine may
read it during generation, and its download status. URLs are filled in only once
they are confirmed on the publisher's page; `url=None` means "not yet confirmed",
and the ingest step refuses to download it.

Generation-eligible sources are read by the generation pipeline. Quarantined sources
are audit-only and must never be opened by generation code (see ingest/generation.py).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    key: str
    description: str
    publisher: str
    url: str | None  # None until confirmed on the publisher's page
    file_format: str
    approx_size_mb: float | None
    licence: str
    quarantined: bool  # True = audit-only, never read during generation
    sha256: str | None = None  # filled in after the first verified download


SOURCES: dict[str, Source] = {
    s.key: s
    for s in [
        Source(
            key="admin_express_fra",
            description=("ADMIN EXPRESS COG 3.2, edition 2024-02-22, national (metropolitan + DROM + Mayotte), "
                         "WGS84G shapefiles. Use this one: it covers all 2024 communes and arrondissements. "
                         "Matches INSEE 2021 population for 971-974 exactly; Mayotte uses its latest official 2017 commune population."),
            publisher="IGN (via Géoplateforme download API, data.geopf.fr/telechargement)",
            url=("https://data.geopf.fr/telechargement/download/ADMIN-EXPRESS-COG/"
                 "ADMIN-EXPRESS-COG_3-2__SHP_WGS84G_FRA_2024-02-22/"
                 "ADMIN-EXPRESS-COG_3-2__SHP_WGS84G_FRA_2024-02-22.7z"),
            file_format="7z containing shapefiles (COMMUNE, ARRONDISSEMENT_MUNICIPAL, ...), WGS84G",
            approx_size_mb=560,
            licence="Licence Ouverte 2.0 [CONFIRM on cartes.gouv.fr]",
            quarantined=False,
            sha256="7ec91626a7c4acda765caa41fe3093bece4d1a03b8e0e6f2d0cdbd3a995ee055",
        ),
        Source(
            key="admin_express_cog",
            description=("SUPERSEDED by admin_express_fra. Metropolitan-only ADMIN EXPRESS COG 3.2, edition 2024-02-22, "
                         "Lambert-93. Kept for the join check script."),
            publisher="IGN (via Géoplateforme download API, data.geopf.fr/telechargement)",
            url=("https://data.geopf.fr/telechargement/download/ADMIN-EXPRESS-COG/"
                 "ADMIN-EXPRESS-COG_3-2__SHP_LAMB93_FXX_2024-02-22/"
                 "ADMIN-EXPRESS-COG_3-2__SHP_LAMB93_FXX_2024-02-22.7z"),
            file_format="7z containing shapefiles (COMMUNE, ARRONDISSEMENT_MUNICIPAL, ...), Lambert-93",
            approx_size_mb=237.8,
            licence="Licence Ouverte 2.0 [CONFIRM on cartes.gouv.fr]",
            quarantined=False,
            sha256="eba0319777a54854e9295009902689f1a4213aa5f5b9b0faacf1369dfa6e8b2e",
        ),
        Source(
            key="population_legal",
            description=("Populations légales, millésime 2021 (reference date 1 Jan 2021, in force 1 Jan 2024). "
                         "Use PMUN (population municipale) as legal population. Contains municipal "
                         "arrondissements of Paris, Lyon, Marseille as communes (codes 75101..., etc.)."),
            publisher="INSEE",
            url="https://www.insee.fr/fr/statistiques/fichier/7739582/ensemble.zip",
            file_format=("zip of csv including donnees_communes.csv and donnees_communes_deleguees.csv; "
                         "';' separated, utf-8; delegated-commune PMUN supports documented COG transition mapping"),
            approx_size_mb=1.1,
            licence="Licence Ouverte [CONFIRM on INSEE page]",
            quarantined=False,
            sha256="f002a648fbb5d0fbf4f2f528997cd4ce3ebee3b5366ecdb55d16107dd4043816",
        ),
        Source(
            key="population_legal_2006",
            description=("INSEE populations légales 2006, reference date 1 Jan 2006 and municipal geography "
                         "in force 1 Jan 2008. Audit-only historical population basis for checking the "
                         "2009 constituency redistricting; never a population input for the 2024 snapshot."),
            publisher="INSEE",
            url="https://www.insee.fr/fr/statistiques/2119916",
            file_format="XLS, sheet 'Communes', municipal and total population columns",
            approx_size_mb=8.1,
            licence="Licence Ouverte [verify exact historical metadata before redistribution]",
            quarantined=False,
            sha256="8a1e6eb7706956938df9f2b43c473e4833b9a9153a891de0c48ae1c58b2ba46c",
        ),
        Source(
            key="mayotte_population_legal_2017",
            description=("Official 2017 commune-level municipal population for Mayotte, authenticated by decree. "
                         "Used as the latest official Mayotte commune population for a 2024 snapshot; reference vintage differs explicitly."),
            publisher="INSEE",
            url="https://www.insee.fr/fr/statistiques/fichier/5392668/mayotte-RP2017-tableaux_pop_legale.xlsx",
            file_format="XLSX, Communes sheet, municipal population column",
            approx_size_mb=0.01,
            licence="Licence Ouverte [confirm on INSEE page]",
            quarantined=False,
            sha256="bf6c49f5adebd4df543fb55be1efd2a2c962163ecea7c26943a030290c585603",
        ),
        Source(
            key="iris_contours",
            description=("IRIS small-area boundaries, edition 2024-01-01, metropolitan France (FXX, Lambert-93). "
                         "Publisher's MD5 verified. Overseas: see iris_contours_drom."),
            publisher="INSEE / IGN (via Géoplateforme download API)",
            url=("https://data.geopf.fr/telechargement/download/CONTOURS-IRIS/"
                 "CONTOURS-IRIS_3-0__SHP_LAMB93_FXX_2024-01-01/CONTOURS-IRIS_3-0__SHP_LAMB93_FXX_2024-01-01.7z"),
            file_format="7z containing shapefiles (CONTOURS-IRIS), Lambert-93",
            approx_size_mb=35,
            licence="Licence Ouverte 2.0 [CONFIRM on cartes.gouv.fr]",
            quarantined=False,
            sha256="fda58eb782a9043be04f69a303a7cbb6a8e693762654cfc9c27f43d9c3c6816a",
        ),
        Source(
            key="iris_contours_drom",
            description=("IRIS 2024-01-01 for the five DROM (Guadeloupe GLP, Martinique MTQ, Guyane GUF, "
                         "Réunion REU, Mayotte MYT), one 7z each, local CRS. Hashes in data/raw/iris/SHA256SUMS."),
            publisher="INSEE / IGN (via Géoplateforme download API)",
            url=None,  # five separate files; each URL follows the same download pattern as iris_contours
            file_format="7z containing shapefiles, local CRS per territory",
            approx_size_mb=4,
            licence="Licence Ouverte 2.0 [CONFIRM on cartes.gouv.fr]",
            quarantined=False,
        ),
        Source(
            key="iris_population",
            description=("INSEE 2022 census population shares by IRIS, published on geography in force 2024-01-01. "
                         "Used only to distribute the selected 2021 legal commune totals over IRIS pieces; each "
                         "parent's scaled pieces sum exactly to its 2021 legal population."),
            publisher="INSEE",
            url="https://www.insee.fr/fr/statistiques/fichier/8647014/base-ic-evol-struct-pop-2022_csv.zip",
            file_format="ZIP of semicolon-delimited CSV plus metadata; IRIS code and P22_POP column",
            approx_size_mb=22.6,
            licence="Open data; confirm exact licence metadata before redistribution",
            quarantined=False,
            sha256="f42c155e14d32c6ca9697f74795a56c046c1b4e5404279cf70a173b210eb0bc5",
        ),
        Source(
            key="constituencies_2024",
            description=("INSEE simplified legislative-constituency map published 2022-05-04; reference context for the "
                         "2024 map only. The publisher warns it is too simplified for precise location-to-constituency "
                         "assignment. Not a commune membership crosswalk or a suitable source for exact boundary diffs."),
            publisher="INSEE",
            url="https://www.insee.fr/fr/statistiques/fichier/6441661/contours_circonscriptions_legislatives_03052022.zip",
            file_format="ZIP containing ESRI Shapefile, WGS84 (EPSG:4326), 558 departmental constituency features",
            approx_size_mb=5.8,
            licence="Open data; verify exact licence metadata before redistribution",
            quarantined=False,
            sha256="bd16cb3c822a03fd5343d628edd37efa719bb129141fdfbd2b814c9da2ddb0df",
        ),
        Source(
            key="constituency_commune_correspondence_2026",
            description=("INSEE commune-to-legislative-constituency table for the current constituency map. "
                         "Rows mark a commune as entirely or partially included in a constituency; partial rows "
                         "identify split communes but do not specify the sub-commune boundary. The map itself "
                         "remains the 2012 delimitation used in the 2024 baseline."),
            publisher="INSEE",
            url="https://www.insee.fr/fr/statistiques/6436476",
            file_format="XLSX, sheet 'table', 2021 commune codes, constituency code, type_com",
            approx_size_mb=1.4,
            licence="Open data; verify exact licence metadata before redistribution",
            quarantined=False,
            sha256="a5b00c7b9c1d27565692e2dba712ca005e1b348f055483d34a29a713dcdc6e3c",
        ),
        Source(
            key="liaison_iris_bureaux_2024",
            description=("Estimated 2024 polling-station to IRIS linkage weights based on the INSEE 2019 200 m "
                         "population grid. Audit-only sensitivity input; bureau IDs require exact reconciliation "
                         "to Ministry results and coverage is metropolitan only."),
            publisher="Jérémy Perrin via data.gouv.fr",
            url="https://static.data.gouv.fr/resources/liaison-iris-bureaux-de-vote-de-2024/20260329-123247/liaison-iris-bureaux-de-vote.csv",
            file_format="CSV, UTF-8, columns iris/bureau/poids_dans_iris/poids_dans_bureau",
            approx_size_mb=6.2,
            licence="Licence Ouverte / Open Licence 2.0",
            quarantined=True,
            sha256="80538c5924160f2584a915144771d4f42e944be99470238ad67bcf839b32f7ab",
        ),
        Source(
            key="results_leg_2024_t1_communes",
            description=("Legislative 2024 official first-round results by commune, including registered voters and "
                         "candidate votes. Paris, Lyon, and Marseille are aggregated at commune level."),
            publisher="Ministère de l'Intérieur via data.gouv.fr",
            url="https://static.data.gouv.fr/resources/elections-legislatives-des-30-juin-et-7-juillet-2024-resultats-definitifs-du-1er-tour/20240711-075056/resultats-definitifs-par-communes.csv",
            file_format="semicolon-delimited CSV, UTF-8",
            approx_size_mb=73.5,
            licence="Licence Ouverte 2.0",
            quarantined=True,
            sha256="853d7a396f17a1e94df17747e9ada3f439220113cd1b6bee686efbc292a6aad5",
        ),
        Source(
            key="results_leg_2024_t1_polling_stations",
            description=("Legislative 2024 official first-round results by polling station, including registered voters "
                         "and candidate votes. Requires a validated polling-station to small-area crosswalk."),
            publisher="Ministère de l'Intérieur via data.gouv.fr",
            url="https://static.data.gouv.fr/resources/elections-legislatives-des-30-juin-et-7-juillet-2024-resultats-definitifs-du-1er-tour/20240710-171445/resultats-definitifs-par-bureau-de-vote.csv",
            file_format="semicolon-delimited CSV, UTF-8",
            approx_size_mb=37.5,
            licence="Licence Ouverte 2.0",
            quarantined=True,
            sha256="359ee3e0a29bb917b79799f0490c9e893aa073dd9d89ca33788af6ccac1d9e33",
        ),
        Source(
            key="results_leg_2024_t2_communes",
            description=("Legislative 2024 official second-round results by commune, including registered voters and "
                         "candidate votes. Paris, Lyon, and Marseille are aggregated at commune level; communes "
                         "whose seats were filled in round one are absent."),
            publisher="Ministère de l'Intérieur via data.gouv.fr",
            url="https://static.data.gouv.fr/resources/elections-legislatives-des-30-juin-et-7-juillet-2024-resultats-definitifs-du-2nd-tour/20240710-170606/resultats-definitifs-par-commune.csv",
            file_format="semicolon-delimited CSV, UTF-8",
            approx_size_mb=12,
            licence="Licence Ouverte 2.0",
            quarantined=True,
            sha256="03ce0560c3398165b2833486d305aec9cc0d0c543f1ad3a95956f2cb8d05ebb8",
        ),
        Source(
            key="results_leg_2024_t2_polling_stations",
            description=("Legislative 2024 official second-round results by polling station, including registered voters "
                         "and candidate votes. Requires a validated polling-station to small-area crosswalk; "
                         "round-two totals differ as seats filled in round one are not voted again."),
            publisher="Ministère de l'Intérieur via data.gouv.fr",
            url="https://static.data.gouv.fr/resources/elections-legislatives-des-30-juin-et-7-juillet-2024-resultats-definitifs-du-2nd-tour/20240710-170658/resultats-definitifs-par-bureau-de-vote.csv",
            file_format="semicolon-delimited CSV, UTF-8",
            approx_size_mb=16,
            licence="Licence Ouverte 2.0",
            quarantined=True,
            sha256="c4cf7aa7ea9e1ff707c4058af93351c77dbf204f8c0042731a1901290fe09f53",
        ),
        Source(
            key="results_leg_2024_t1_constituencies",
            description="Official legislative 2024 first-round constituency results; used for D11 historical validation and the exact current-official-map audit baseline.",
            publisher="Ministère de l'Intérieur via data.gouv.fr",
            url="https://static.data.gouv.fr/resources/elections-legislatives-des-30-juin-et-7-juillet-2024-resultats-definitifs-du-1er-tour/20240710-171413/resultats-definitifs-par-circonscriptions-legislatives.csv",
            file_format="semicolon-delimited CSV, UTF-8",
            approx_size_mb=0.34,
            licence="Licence Ouverte 2.0",
            quarantined=True,
            sha256="dbeb0214bc9f54d44d4641400177ea93203b0b90d35485a2b4ed4fc3c300ab3f",
        ),
        Source(
            key="results_leg_2024_t2_constituencies",
            description="Official legislative 2024 second-round constituency results; used for D11 historical validation and restricted current-official-map metrics.",
            publisher="Ministère de l'Intérieur via data.gouv.fr",
            url="https://static.data.gouv.fr/resources/elections-legislatives-des-30-juin-et-7-juillet-2024-resultats-definitifs-du-2nd-tour/20240710-170728/resultats-definitifs-par-circonscription.csv",
            file_format="semicolon-delimited CSV, UTF-8",
            approx_size_mb=0.15,
            licence="Licence Ouverte 2.0",
            quarantined=True,
            sha256="bcc062b9264dcf3dc1eac5463acf1e8743171b86385923e7f770fd9028271083",
        ),
        Source(
            key="results_pres_2022",
            description="Presidential 2022 first-round results per commune",
            publisher="Ministère de l'Intérieur",
            url=None,
            file_format="csv",
            approx_size_mb=None,
            licence="Licence Ouverte [CONFIRM]",
            quarantined=True,
        ),
    ]
}


def generation_sources() -> list[Source]:
    """Sources the generation pipeline may read."""
    return [s for s in SOURCES.values() if not s.quarantined]


def quarantined_sources() -> list[Source]:
    """Sources that only the audit may read."""
    return [s for s in SOURCES.values() if s.quarantined]
