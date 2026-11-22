"""Allocate 2024 polling-station counts to split model units for research.

Whole-commune model units retain exact commune totals. Split units use the
published bureau-to-IRIS weights, which assume votes follow population shares.
"""
from collections import defaultdict
import csv


def allocate_split_votes(state, departments, commune_votes, mappings, target_nuance,
                         crosswalk_path, bureau_path, candidate_affiliations=None):
    units = {u for u in state['units'] if state['unit_dept'][u] in departments}
    split_parents = {u[:5] for u in units if len(u) >= 9}
    by_bureau = defaultdict(list)
    parent_to_sources = defaultdict(set)
    with crosswalk_path.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            iris, bureau = row['iris'].strip(), row['bureau'].strip()
            parent = iris[:5]
            # Paris/Lyon/Marseille can use arrondissement units even though
            # the results file uses the city-wide commune code.
            is_arrondissement = parent in units and bureau[:5] != parent
            if parent in split_parents or is_arrondissement:
                if is_arrondissement:
                    split_parents.add(parent)
                weight = float(row['poids_dans_bureau'])
                if weight < 0 or weight > 1 + 1e-8: raise ValueError('invalid crosswalk weight')
                by_bureau[bureau].append((iris, weight))
                parent_to_sources[iris[:5]].add(bureau[:5])
    # Include all weights in the original split commune, even unmatched model
    # units, so coverage accounts for omitted pieces rather than renormalizing.
    source_parents = {source for sources in parent_to_sources.values() for source in sources}
    if source_parents & {u for u in units if len(u) == 5}:
        raise ValueError('split and whole units overlap in source commune')
    names = {name: {n:b for b, ns in d['blocs'].items() for n in ns}
             for name, d in mappings.items()}
    result = {name: {unit: dict(v) for unit, v in votes.items() if unit not in split_parents and unit not in source_parents}
              for name, votes in commune_votes.items()}
    for name in names:
        for unit in units:
            if len(unit) >= 9 or unit in split_parents: result[name][unit] = {}
    denominators = defaultdict(float)
    allocated = defaultdict(float)
    seen_bureau = set()
    with bureau_path.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f, delimiter=';'):
            parent = row['Code commune'].strip().upper().zfill(5)
            if parent not in source_parents: continue
            bureau = parent + row['Code BV'].strip().zfill(4)
            registered = float((row.get('Inscrits') or '0').replace(' ', ''))
            denominators[parent] += registered
            if bureau in seen_bureau and bureau in by_bureau:
                raise ValueError(f'ambiguous duplicate bureau key: {bureau}')
            seen_bureau.add(bureau)
            links = [(u if u in units else u[:5],w) for u,w in by_bureau.get(bureau, [])
                     if u in units or u[:5] in units]
            weight_sum = sum(w for _,w in links)
            if weight_sum > 1 + 1e-8: raise ValueError(f'weights exceed one for bureau {bureau}')
            allocated[parent] += registered * weight_sum
            if not links: continue
            for key, value in row.items():
                if not key.startswith('Nuance candidat ') or not value: continue
                slot = key.rsplit(' ',1)[1]; nuance = value.strip()
                raw = row.get('Voix ' + slot, '').strip().replace(' ', '')
                if not nuance or not raw: continue
                count = int(raw)
                target_affiliation = False
                if candidate_affiliations is not None:
                    from partisan_affiliations import affiliation_for, PARTY_LFI
                    target_affiliation = affiliation_for(candidate_affiliations, row, slot) == PARTY_LFI
                for name, mapping in names.items():
                    bloc = ('party:LFI' if target_affiliation else
                            ('party:' + nuance if nuance == target_nuance else mapping.get(nuance, 'other')))
                    for unit, weight in links:
                        dest = result[name][unit]
                        dest[bloc] = dest.get(bloc, 0) + count * weight
    source_coverage = {parent: allocated[parent] / denominators[parent] if denominators[parent] else 0
                       for parent in source_parents}
    coverage = {parent: min((source_coverage[source] for source in parent_to_sources[parent]), default=0)
                for parent in split_parents}
    source_dept = {}
    for parent, sources in parent_to_sources.items():
        dept = state['unit_dept'][next(u for u in units if u == parent or (u.startswith(parent) and len(u) >= 9))]
        for source in sources:
            if source in source_dept and source_dept[source] != dept:
                raise ValueError('bureau commune crosses departments')
            source_dept[source] = dept
    missing_by_dept = defaultdict(float)
    for source, dept in source_dept.items():
        missing_by_dept[dept] += max(0.0, denominators[source] - allocated[source])
    details = {'source_missing_registered': {source: max(0.0, denominators[source] - allocated[source])
                                               for source in source_parents},
               'parent_sources': {parent: sorted(sources) for parent, sources in parent_to_sources.items()}}
    return result, coverage, dict(missing_by_dept), details
