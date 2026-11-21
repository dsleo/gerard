# 05 — Legal Notes and Sources

Every legal statement the engine relies on, with its source and verification status. Nothing here is legal advice. Status meanings:

- **CONFIRMED (secondary):** stated in parliamentary or Senate documents, not yet checked against the primary text.
- **VERIFY:** stated in our notes but not checked against any source.
- **OPEN:** not yet found in any source.

---

## L1 — Splitting communes

| Point | Status | Source |
|---|---|---|
| A commune under 5,000 inhabitants must lie wholly within one constituency | CONFIRMED (secondary) | [Senate report on the 2009 organic law](https://www.senat.fr/rap/l08-120/l08-120_mono.html); [Assemblée report on ordonnance 2009-935](https://www.assemblee-nationale.fr/13/rapports/r1949.asp) |
| Larger communes may be divided between constituencies | CONFIRMED (secondary) | same reports; the Senate report refers to Code électoral article L.125 and its annexed table no. 1 |
| Exact text of L.125 and the annexed table | OPEN | Légifrance, Code électoral |
| Rules specific to Paris, Lyon, Marseille (arrondissements) | OPEN | Légifrance, Code électoral |

**Engine consequence:** Communes under 5,000 are never split (checked by the validator, see `whole_commune_below_population` in config). Splitting for larger communes follows the rule in D4 of the decision log, pending the L.125 text.

## L2 — The ±20% population deviation

| Point | Status | Source |
|---|---|---|
| 20% deviation from the departmental average accepted since 1986 | CONFIRMED (secondary) | Senate and Assemblée reports cited in L1 |
| Constitutional Council applies the limit strictly; exceptions only for justified cases | CONFIRMED (secondary) | Commentary cited in the 2009 reports |
| Decision 2008-573 DC reserved exceptions for territorial continuity and for not following commune limits | CONFIRMED (secondary) | Assemblée report on ordonnance 2009-935 |
| A district at +26.44% was accepted in 2009 | CONFIRMED (secondary) | Assemblée report on ordonnance 2009-935 |
| Decision 2010-602 DC text | OPEN (not read) | [Conseil constitutionnel](https://www.conseil-constitutionnel.fr/sites/default/files/as/root/bank_mm/decisions/2010602dc/doc.pdf) |
| Decision 2008-573 DC text | OPEN (not read) | conseil-constitutionnel.fr |

**Engine consequence:** ±20% is a hard ceiling by default. Exceptions are configured per department with a justification and are shown as EXCEPTION in the compliance report (D5).

## L3 — Second-round qualification threshold

| Point | Status | Source |
|---|---|---|
| A candidate with at least 12.5% of **registered voters** may stand in round 2 | CONFIRMED (primary) | Code électoral article L.162, second paragraph: [Légifrance](https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000006353380/2025-12-15) |
| If one candidate meets the threshold, the next-highest candidate may also stand; if none meet it, the top two may stand | CONFIRMED (primary) | Code électoral article L.162, second paragraph: [Légifrance](https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000006353380/2025-12-15) |
| L.126 governs first-round election requirements and second-round majority; it is not the candidacy threshold | CONFIRMED (primary) | Code électoral article L.126: [Légifrance](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006353299) |

## L4 — Political nuance codes (Ministry of the Interior)

| Point | Status | Source |
|---|---|---|
| Instruction of 11 June 2024 on attribution of nuances (NOR IOMA2415630C) | CONFIRMED (secondary) | [Landot Avocats](https://blog.landot-avocats.net/2024/06/28/legislatives-2024-diffusion-de-linstruction-de-nuancage-avec-sans-doute-un-debat-a-venir-du-cote-du-nfp/), [Localtis / Banque des Territoires](https://www.banquedesterritoires.fr/legislatives-le-nuancier-politique-et-son-mode-demploi-enfin-mis-en-ligne) |
| Full grid of 24 nuances with labels | CONFIRMED (primary: Annexe 1 of the instruction, NOR IOMA2415630C) | [instruction PDF on Légifrance](https://www.legifrance.gouv.fr/download/file/pdf/cir_45565/CIRC), text layer extracted locally |
| Attribution rules: one nuance per candidate, from investiture or support; sensitivity nuances for independents; DIV only for candidates classifiable nowhere; no nuance for substitutes | CONFIRMED (primary) | §2 of the instruction |
| NFP has no nuance; its candidates get UG | CONFIRMED (primary: UG defined as "deux partis de gauche") | Annexe 1 |
| Party nuances: COM FI SOC RDG VEC REN MDM HOR UDI LR RN REC | CONFIRMED (primary) | Annexe 1 |
| Sensitivity nuances: EXG DVG ECO REG DVC DVD EXD | CONFIRMED (primary) | Annexe 1 |
| Alliance / special nuances: UG ENS UXD DSV DIV | CONFIRMED (primary) | Annexe 1 |
| Nuance decided by the prefect, not the candidate; can differ from declared label | CONFIRMED (primary) | §1 of the instruction |

**OCR caveat:** the text layer has a few OCR artifacts (for example "CaM" for COM, "MOM" for MDM). Annexe 1 on the second page gives the clean codes, which are the ones used in `blocs.draft.yaml`. A visual check of the PDF is still advisable before publication.

**Note for the audit:** the 2024 grid applies to the 2024 legislative elections only. Presidential 2022 results need their own nuance or party-to-bloc mapping (the presidential ballot has no nuance grid).

---

## Next verification steps

1. Obtain the 2024 nuance grid (OCR of the instruction PDF, or a text copy).
2. Read Code électoral L.125 and the annexed table on Légifrance; the L.162 second-round candidacy threshold and fallback have been verified against the primary text.
3. Read decisions 2008-573 DC and 2010-602 DC.
4. Have a qualified lawyer confirm L1–L3 before any output is presented as more than a reference study.
