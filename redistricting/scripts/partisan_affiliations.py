"""Validated candidate financial-attachment join for 2024 first-round data."""
from __future__ import annotations
import csv
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
import pandas as pd

PARTY_LFI = 'La France insoumise (LFI)'


def clean(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', str(value or ''))
                            if not unicodedata.combining(c)).upper().replace('-', ' ').split())


def candidate_key(department, name, first):
    dep = str(department or '').strip().upper().zfill(2)
    dep = {'ZZ': 'FEHF', 'ZX': '977/978'}.get(dep, dep)
    return dep, clean(name), clean(first)


def load_affiliations(path: Path, constituency_results: Path):
    table = pd.read_excel(path, dtype=str).fillna('')
    records = defaultdict(list)
    for row in table.to_dict('records'):
        key = candidate_key(row['Code département'], row['Nom du candidat'], row['Prénom du candidat'])
        records[key].append(row)
    if any(len(rows) != 1 for rows in records.values()):
        raise ValueError('candidate attachment data has ambiguous name/department keys')
    official_keys = set()
    with constituency_results.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream, delimiter=';'):
            for field, nuance in row.items():
                match = re.fullmatch(r'Nuance candidat (\d+)', field or '')
                if not match or not nuance: continue
                slot = match.group(1)
                key = candidate_key(row['Code département'], row['Nom candidat '+slot], row['Prénom candidat '+slot])
                if key in official_keys or key not in records:
                    raise ValueError(f'missing or ambiguous official candidate: {key}')
                official_keys.add(key)
                observed = int((row['Voix '+slot] or '0').replace(' ', ''))
                attached = int((records[key][0]['Voix'] or '0').replace(' ', ''))
                if observed != attached:
                    raise ValueError(f'candidate vote totals do not match: {key}')
    if official_keys != set(records):
        raise ValueError(f'attachment data has {len(set(records)-official_keys)} candidates not in official results')
    return {key: rows[0]['Parti de rattachement'].strip() for key, rows in records.items()}


def affiliation_for(mapping, row, slot):
    key = candidate_key(row['Code département'], row['Nom candidat '+str(slot)], row['Prénom candidat '+str(slot)])
    if key not in mapping: raise ValueError(f'candidate not in validated attachment data: {key}')
    return mapping[key]
