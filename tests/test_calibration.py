"""[N3] 추정값 보정 제안: 실적 근거 없이는 거절, 사람 승인 후에만 반영."""

import copy

import pytest
import yaml

from outcome.aggregate import duration_ratio, travel_ratio
from outcome.calibration import apply_calibration, approve, calibration_errors, check, reject
from tests.conftest import REPO, profile_path
from world.carryover import simulate_outcomes
from world.config import load_world

SETTINGS = yaml.safe_load(open(REPO / "settings" / "flow.yaml", encoding="utf-8"))["calibration"]


@pytest.fixture(scope="module")
def records(scenario):
    instance, params, decisions = scenario
    return simulate_outcomes(instance, decisions, params, load_world(profile_path("normal")), seed=1)


def pole(value, evidence=True):
    p = {"path": "weights.difficulty", "key": "pole", "value": value, "source": "분석 agent", "rationale": "승주 실적이 김"}
    if evidence:
        p["evidence"] = {"table": "duration_ratio", "group_by": "difficulty", "group": "pole"}
    return p


def test_duration_ratio_finds_p6(records):
    table = duration_ratio(records, "difficulty")
    assert table["pole"]["mean_ratio"] == pytest.approx(1.25, abs=0.05)
    assert table["none"]["mean_ratio"] == pytest.approx(1.0, abs=0.05)
    assert table["pole"]["n"] >= 30
    assert "all" in table


def test_travel_ratio_by_depart_hour_shows_rush(records):
    table = travel_ratio(records, "depart_hour")     # 집계는 세상 설정(출퇴근 시간대)을 모른다
    rush = [table[h]["mean_ratio"] for h in ("08", "09") if h in table]
    calm = [table[h]["mean_ratio"] for h in ("11", "12", "13", "14") if h in table]
    assert rush and calm
    assert min(rush) > max(calm) * 1.25


def test_pole_calibration_with_evidence_passes(scenario, records):
    _, params, _ = scenario
    assert calibration_errors(params, pole(1.9), records, SETTINGS) == []


def test_rejected_without_evidence(scenario, records):
    _, params, _ = scenario
    errors = calibration_errors(params, pole(1.9, evidence=False), records, SETTINGS)
    assert any("근거" in e for e in errors)


def test_rejected_when_against_evidence(scenario, records):
    _, params, _ = scenario
    assert any("실적 배율" in e for e in calibration_errors(params, pole(1.2), records, SETTINGS))
    # 근거가 다른 구간이면 (승주 값을 바꾸는데 일반 작업 실적을 근거로) 거절
    p = pole(1.9)
    p["evidence"]["group"] = "none"
    assert any("구간" in e for e in calibration_errors(params, p, records, SETTINGS))


def test_rejected_for_small_sample(scenario, records):
    _, params, _ = scenario
    settings = {**SETTINGS, "min_samples": 10_000}
    assert any("건수" in e for e in calibration_errors(params, pole(1.9), records, settings))


def test_only_estimate_parameters(scenario, records):
    _, params, _ = scenario
    p = {"path": "matching.area_extension_km", "value": [0, 1, 4], "source": "x",
         "evidence": {"table": "duration_ratio", "group_by": "difficulty", "group": "all"}}
    assert any("estimate" in e for e in calibration_errors(params, p, records, SETTINGS))


def test_rejected_out_of_bounds(scenario, records):
    _, params, _ = scenario
    tight = copy.deepcopy(params)
    tight["weights"]["bounds"]["difficulty"] = [1.0, 1.6]
    assert calibration_errors(tight, pole(1.9), records, SETTINGS)


def test_status_flow_needs_human(scenario, records):
    _, params, _ = scenario
    item = check(params, pole(1.9), records, SETTINGS)
    assert item["status"] == "checked" and item["evidence_result"]["mean_ratio"] == pytest.approx(1.25, abs=0.05)
    with pytest.raises(ValueError):
        apply_calibration(params, item)                # 승인 전에는 반영 불가
    with pytest.raises(ValueError):
        approve(item, approver="")                     # 승인자 필수
    approved = approve(item, approver="운영팀 김", note="실적 확인")
    new = apply_calibration(params, approved)
    assert new["weights"]["difficulty"]["pole"] == 1.9
    assert params["weights"]["difficulty"]["pole"] == 1.5   # 원본은 그대로

    bad = check(params, pole(1.9, evidence=False), records, SETTINGS)
    assert bad["status"] == "invalid"
    with pytest.raises(ValueError):
        approve(bad, approver="운영팀 김")
    assert reject(item, approver="운영팀 김", note="보류")["status"] == "rejected"
