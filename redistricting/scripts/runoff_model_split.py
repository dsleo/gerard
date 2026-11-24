"""Candidate-level LFI split and cached central predictions for the runoff model."""
import collections
import bisect
import csv
import re
import yaml
import experiment_partisan_campaign as campaign
from partisan_affiliations import load_affiliations, affiliation_for, PARTY_LFI

BLOCKS = ['lfi', 'left', 'centre', 'right', 'far_right', 'other']

def merge_lfi_votes(counts):
    """Combine separately classified EXG and LFI-attachment votes without loss."""
    merged = collections.defaultdict(float)
    for bloc, value in counts.items():
        merged['lfi' if bloc == 'party:LFI' else bloc] += value
    return dict(merged)

def inputs():
    definitions = yaml.safe_load(campaign.exp.BLOCS.read_text())['mappings']
    # EXG is an electoral nuance; LFI candidates generally carry UG in 2024
    # and must additionally be identified by their financial attachment.
    coarse = definitions['coarse']['blocs']
    coarse['left'].remove('EXG')
    coarse['lfi'] = ['EXG']
    mapping = {n: b for b, ns in definitions['coarse']['blocs'].items() for n in ns}
    mapping['LFI_ATTACHMENT'] = 'lfi'
    mapping.update({'model:' + b: b for b in BLOCKS})
    affiliations = load_affiliations(campaign.AFFILIATION, campaign.FIRST)
    builder, _ = campaign.second_round_inputs()
    def read(path):
        out = []
        with path.open(encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f, delimiter=';'):
                dep = builder.department(row.get('Code département'))
                if not builder.in_department_scope(dep): continue
                code = str(row.get('Code circonscription législative') or '').strip()
                try: number = int(code[len(dep):])
                except ValueError: continue
                votes = collections.defaultdict(float); count = 0
                for field, nuance in row.items():
                    match = re.fullmatch(r'Nuance candidat (\d+)', field or '')
                    if not match: continue
                    slot = match.group(1)
                    if not (row.get('Nom candidat '+slot) or row.get('Prénom candidat '+slot) or '').strip(): continue
                    count += 1
                    n = 'LFI_ATTACHMENT' if affiliation_for(affiliations, row, slot) == PARTY_LFI else (nuance or '').strip()
                    votes[n] += builder.number(row.get('Voix '+slot))
                out.append({'department':dep, 'district_number':number, 'candidate_count':count, 'expressed':builder.number(row.get('Exprimés')), 'votes_by_nuance':dict(votes), 'estimated':True})
        return out
    return builder, definitions, mapping, affiliations, read(campaign.FIRST), read(campaign.SECOND)

class Scorer:
    def __init__(self, builder, mapping, first, second):
        self.builder, self.mapping = builder, mapping
        model = builder.round_two_mapping_model(first, second, [], mapping, BLOCKS, 2024)
        self.bias = model['validation']['applied_calibration_bias']
        self.residuals = {key:sorted(values) for key,values in model['calibration']['centered_residuals_by_pair'].items()}
        self.global_residuals = sorted(model['calibration']['global_residuals'])
        first_by = {(r['department'], r['district_number']):r for r in first}
        self.pairs = collections.defaultdict(list)
        for r in second:
            if r['candidate_count'] != 2 or r['expressed'] <= 0: continue
            candidates = [(mapping.get(n,'other'),v) for n,v in r['votes_by_nuance'].items() if v >= 0]
            pair = tuple(sorted({b for b,v in candidates}))
            first_row = first_by.get((r['department'],r['district_number']))
            if len(pair) != 2 or not first_row: continue
            shares = builder.block_shares(first_row['votes_by_nuance'], mapping, BLOCKS)
            self.pairs[pair].append({'features':tuple(shares[b] for b in BLOCKS), 'target':sum(v for b,v in candidates if b == pair[0])/r['expressed']})
    def prediction(self, votes):
        total = sum(votes.values())
        if not total: return None
        shares = {b:votes.get(b,0)/total for b in BLOCKS}
        ordered = sorted(BLOCKS, key=lambda b:shares[b], reverse=True)
        a,b = sorted(ordered[:2]); peers = self.pairs.get((a,b),[])
        if len(peers) >= 5: value,_ = self.builder.nearest_prediction(tuple(shares[x] for x in BLOCKS), peers)
        else: value = shares[a]/(shares[a]+shares[b])
        value = max(0,min(1,value+self.bias))
        return a,b,value
    def winner(self, votes):
        result = self.prediction(votes)
        if result is None: return None
        a,b,value = result
        return a if value >= .5 else b
    def win_probabilities(self, votes):
        prediction = self.prediction(votes)
        result = {b:0.0 for b in BLOCKS}
        if prediction is None: return result
        a,b,value = prediction
        pool = self.residuals.get(' + '.join(sorted((a,b))), [])
        if len(pool) < 10: pool = self.global_residuals
        p = (len(pool)-bisect.bisect_left(pool,.5-value))/len(pool) if pool else float(value >= .5)
        result[a],result[b] = p,1-p
        return result
    def expected_scores(self, plan, votes):
        totals = collections.defaultdict(lambda:collections.defaultdict(float))
        for unit,district in plan.items():
            for bloc,value in votes.get(unit,{}).items(): totals[district][bloc] += value
        result = {b:{'expected':0.0,'smooth_score':0.0} for b in BLOCKS}
        for counts in totals.values():
            total = sum(counts.values())
            if not total: continue
            probabilities = self.win_probabilities(counts)
            for bloc in BLOCKS:
                result[bloc]['expected'] += probabilities[bloc]
                result[bloc]['smooth_score'] += counts.get(bloc,0)/total
        return result
    def all_scores(self, plan, votes):
        totals = collections.defaultdict(lambda:collections.defaultdict(float))
        for unit,district in plan.items():
            for bloc,value in votes.get(unit,{}).items(): totals[district][bloc] += value
        result = {b:{'pluralities':0,'smooth_score':0.0} for b in BLOCKS}
        for counts in totals.values():
            total=sum(counts.values())
            if not total: continue
            winner=self.winner(counts)
            if winner is not None: result[winner]['pluralities']+=1
            for bloc in BLOCKS: result[bloc]['smooth_score']+=counts.get(bloc,0)/total
        return result
    def score(self, plan, votes, target):
        return self.all_scores(plan, votes)[target]
