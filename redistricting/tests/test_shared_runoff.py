"""Cross-target sharing and optional focus must preserve scoring semantics."""
import random
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from search_shared_runoff import SharedArchive, preferred_pair, TARGETS

class MockScorer:
    def all_scores(self, plan, votes):
        return {target:{'pluralities':plan.get(target,0), 'smooth_score':0.0} for target in TARGETS}
    def prediction(self, counts):
        return ('left','right',.51)

def test_candidate_can_improve_another_target_even_if_not_accepted_by_origin():
    archive=SharedArchive(MockScorer(),{})
    archive.observe({'left':2,'right':1},{'target':'left'})
    archive.observe({'left':1,'right':3},{'target':'left'})
    assert archive.best['left']['score']['pluralities']==2
    assert archive.best['right']['score']['pluralities']==3
    assert archive.cross_updates['right']==1
    assert archive.best['right']['origin']['target']=='left'

def test_focus_retains_uniform_path_and_selects_only_adjacent_pairs():
    plan={'a':0,'b':1,'c':2}; adj={'a':{'b'},'b':{'a','c'},'c':{'b'}}
    votes={'a':{'left':51,'right':49},'b':{'left':20,'right':80},'c':{'left':40,'right':60}}
    assert preferred_pair(plan,adj,votes,'left',MockScorer(),random.Random(1),0)==None
    assert preferred_pair(plan,adj,votes,'left',MockScorer(),random.Random(1),1) in {(0,1),(1,2)}
