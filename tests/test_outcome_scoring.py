"""[N4] P5·P6 정답을 코어 채점 형식으로 쓰고 코어 score()로 채점한다."""

import pytest
from core.evaluation.fault_scorer import matches, score

from outcome.scoring import outcome_faults
from tests.conftest import PROFILE_NAMES, profile_path
from world.config import load_world


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_faults_in_core_format(name):
    faults = outcome_faults(load_world(profile_path(name)))
    assert set(faults) == {"P5", "P6a", "P6b"}
    for f in faults.values():
        assert f["name"] and f["answer"]["dims"] and f["answer"]["requires_tools"]
        assert "detail" not in f                      # 채점에 필요한 것만 넘긴다


CALLS = {"t1": {"name": "outcome_by_group"}, "t2": {"name": "aggregate"}, "t3": {"name": "duration_ratio"},
         "t4": {"name": "travel_ratio"}}


def test_p5_needs_outcome_tool():
    p5 = outcome_faults(load_world(profile_path("normal")))["P5"]["answer"]
    assert matches({"slice": {"work_type": ["repair"]}, "cited_calls": ["t1"]}, p5, CALLS)
    # 계획 집계만 보고 쓴 장애 발견은 P5로 치지 않는다
    assert not matches({"slice": {"work_type": ["repair"]}, "cited_calls": ["t2"]}, p5, CALLS)
    assert not matches({"slice": {"work_type": ["install"]}, "cited_calls": ["t1"]}, p5, CALLS)


def test_score_all():
    faults = outcome_faults(load_world(profile_path("normal")))
    findings = [{"id": "F1", "slice": {"work_type": ["repair"]}, "cited_calls": ["t1"]},
                {"id": "F2", "slice": {"difficulty": ["pole"]}, "cited_calls": ["t3"]},
                {"id": "F3", "slice": {"hour": ["09"]}, "cited_calls": ["t4"]},
                {"id": "F4", "slice": {"branch": ["C"]}, "cited_calls": ["t2"]}]
    s = score(findings, faults, CALLS)
    assert (s["detected"], s["total"]) == (3, 3)
    assert s["unmatched_findings"] == ["F4"]
