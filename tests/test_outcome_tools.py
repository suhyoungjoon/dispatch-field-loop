"""[N4] 분석 agent용 실적 도구와 팩 래퍼. 도구 결과에 현실 모델 설정이 새지 않아야 한다 (원칙 2)."""

import inspect
import json

import pytest
from core.analysis.aggregate_tools import Aggregator
from core.analysis.perspectives import perspective_errors

from outcome.analysis_pack import OUTCOME_PERSPECTIVE, OutcomePack
from outcome.tools import OUTCOME_TOOL_NAMES, outcome_tools
from tests.conftest import profile_path
from world.carryover import simulate_outcomes
from world.config import load_world

WORLD_KEYS = ("by_work_type", "tolerance_shift", "bands_min", "rush_speed_factor", "rush_hours", "noise_sd",
              "max_carry_days", "per_day", "truth", "execution", "profile")


@pytest.fixture(scope="module")
def records(scenario):
    instance, params, decisions = scenario
    return simulate_outcomes(instance, decisions, params, load_world(profile_path("normal")), seed=1)


@pytest.fixture(scope="module")
def tools(records):
    return {t["name"]: t for t in outcome_tools(records, promise_window_min=60)}


def call(tools, name, args):
    return tools[name]["handler"](args)


def test_tool_definitions(tools):
    assert set(tools) == set(OUTCOME_TOOL_NAMES)
    for t in tools.values():
        assert t["description"] and t["input_schema"]["type"] == "object" and callable(t["handler"])
    assert "world" not in inspect.signature(outcome_tools).parameters     # 현실 모델 설정을 받지 않는다


def test_outcome_by_group_shows_p5(tools):
    out = call(tools, "outcome_by_group", {"group_by": ["work_type"]})
    rows = {r["work_type"]: r for r in out["rows"]}
    assert rows["repair"]["complaint_rate"] > 1.5 * rows["install"]["complaint_rate"]
    band = call(tools, "outcome_by_group", {"group_by": ["work_type", "time_diff_band"], "min_items": 5})
    assert any(r["time_diff_band"] == "31-45" for r in band["rows"])


def test_outcome_by_group_filters_and_limits(tools):
    out = call(tools, "outcome_by_group", {"group_by": ["branch"], "filters": {"work_type": ["repair"]}, "limit": 2})
    assert len(out["rows"]) == 2 and out["filters"] == {"work_type": ["repair"]}
    with pytest.raises(ValueError):
        call(tools, "outcome_by_group", {"group_by": ["nope"]})


def test_ratio_tools_show_p6(tools):
    dur = call(tools, "duration_ratio", {"group_by": "difficulty"})["rows"]
    assert dur["pole"]["mean_ratio"] > 1.15 and abs(dur["none"]["mean_ratio"] - 1) < 0.05
    trv = call(tools, "travel_ratio", {"group_by": "hour"})["rows"]
    # hour는 희망 시각의 시다. 08~10시 출발이 몰린 09시 희망 건에서 뚜렷하고, 10시 건은 약하다
    assert trv["09"]["mean_ratio"] > 1.25
    assert trv["10"]["mean_ratio"] > max(trv[h]["mean_ratio"] for h in ("12", "13", "14"))
    assert max(trv[h]["mean_ratio"] for h in ("12", "13", "14")) < 1.1


def test_tool_outputs_hide_world_settings(tools):
    outs = [call(tools, "outcome_overview", {}),
            call(tools, "outcome_by_group", {"group_by": ["work_type", "difficulty", "time_diff_band"], "min_items": 1}),
            call(tools, "duration_ratio", {"group_by": "difficulty"}),
            call(tools, "travel_ratio", {"group_by": "depart_hour"})]
    text = json.dumps(outs, ensure_ascii=False)
    for key in WORLD_KEYS:
        assert key not in text


def test_outcome_pack_adds_tools_and_delegates(scenario, records):
    from domains.dispatch import get_pack
    instance, params, decisions = scenario
    base = get_pack(params)
    pack = OutcomePack(base, records, promise_window_min=60)
    names = [t["name"] for t in pack.analysis_tools(instance, decisions)]
    assert names[:len(base.analysis_tools(instance, decisions))] == [t["name"] for t in base.analysis_tools(instance, decisions)]
    assert set(OUTCOME_TOOL_NAMES) <= set(names)
    assert pack.dimensions() == base.dimensions() and pack.name == base.name
    assert pack.metrics(instance, decisions) == base.metrics(instance, decisions)
    core_names = {t["name"] for t in Aggregator(decisions, pack.dimensions()).tools()}
    assert perspective_errors([OUTCOME_PERSPECTIVE], core_names | set(names)) == []
