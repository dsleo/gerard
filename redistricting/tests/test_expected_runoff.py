"""Expected-seat search must share candidates by expected, not cutoff, wins."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'scripts'))
from search_expected_runoff import SharedArchive, TARGETS

class Scorer:
    def expected_scores(self, plan, votes):
        return {bloc:{'expected':plan.get(bloc,0.0),'smooth_score':0.0} for bloc in TARGETS}

def test_archive_shares_fractional_expected_gains():
    archive=SharedArchive(Scorer(),{})
    archive.observe({'left':1.3,'right':2.0},{'target':'left'})
    archive.observe({'left':1.2,'right':2.1},{'target':'left'})
    assert archive.best['left']['score']['expected']==1.3
    assert archive.best['right']['score']['expected']==2.1
    assert archive.best['right']['origin']['target']=='left'
