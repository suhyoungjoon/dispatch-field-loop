"""[N6] 통합 흐름 서비스: 계획 → 실적 → 분석 → 대화 → 개선안 → 전후 시뮬레이션 → 승인 (가짜 LLM)."""

import json

import pytest
import yaml
from core.llm.client import load_config

from flow.service import FlowService
from tests.conftest import REPO
from tests.fake_llm import FakeLLM, tool_use

CFG = load_config(REPO / "settings" / "llm.yaml", role="analysis")


def _out(messages, name):
    ids = {b["id"]: b["name"] for m in messages if m["role"] == "assistant" for b in m["content"]
           if b.get("type") == "tool_use"}
    for m in reversed(messages):
        if m["role"] == "user" and not isinstance(m["content"], str):
            for b in m["content"]:
                if b.get("type") == "tool_result" and ids.get(b["tool_use_id"]) == name:
                    return json.loads(b["content"])
    return None


def scripted(steps):
    def policy(item, n, messages, tools):
        return steps[min(n, len(steps) - 1)](messages)
    return policy


def analysis_llm():
    def submit(m):
        wt = _out(m, "outcome_by_group")
        repair = next(r for r in wt["rows"] if r["work_type"] == "repair")
        return tool_use("submit_report", {"summary": "실적", "findings": [
            {"title": "장애 고객 불만", "description": f"장애 불만율 {repair['complaint_rate']}",
             "slice": {"work_type": ["repair"]}, "cited_calls": [wt["call_ref"]]}]})
    return FakeLLM(scripted([lambda m: tool_use("outcome_by_group", {"group_by": ["work_type"]}), submit]))


def dialogue_llm():
    return FakeLLM(scripted([lambda m: tool_use("record_notes", {
        "reply": "이렇게 이해했습니다. 관할 확장은 4km까지, F1은 원인이 맞다는 말씀이죠?",
        "items": [{"kind": "constraint", "utterance": "4km 넘으면 출동 못 해요", "summary": "3단계 관할 4km까지",
                   "constraint": {"type": "param", "path": "matching.area_extension_km[2]", "max": 4}},
                  {"kind": "label", "utterance": "F1은 원인 맞아요", "summary": "F1 원인 맞음",
                   "label": {"finding_id": "F1", "label": "cause_ok"}}]})]))


def proposal_llm(km):
    return FakeLLM(scripted([lambda m: tool_use("submit_proposals", {"proposals": [
        {"kind": "params", "title": f"관할 {km}km", "rationale": "경계 지역", "target_findings": ["F1"],
         "params_changes": [{"path": "matching.area_extension_km[2]", "value": km}]}]})]))


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    return FlowService(root=tmp_path_factory.mktemp("flows"))


@pytest.fixture(scope="module")
def flow(svc):
    return svc.create_flow({"name": "테스트"})


def test_create_flow_has_plan_outcome_and_meta(svc, flow):
    assert flow["plan"]["assigned"] == 1040 and flow["plan"]["on_time"] == 741
    assert 0 < flow["outcome"]["complaint_rate"] < 1
    m = flow["meta"]
    assert (m["data_seed"], m["outcome_seed"], m["profile"], m["params_version"]) == (42, 1, "normal", 1)
    assert m["core_ref"] and svc.list_flows()[0]["id"] == flow["id"]
    assert (svc.store.dir(flow["id"]) / "params.yaml").exists()


def test_full_flow(svc, flow):
    fid = flow["id"]
    report = svc.run_analysis(fid, analysis_llm(), CFG)
    assert [f["id"] for f in report["findings"]] == ["F1"]
    assert svc.get_flow(fid)["score"]["faults"]["P5"]["status"] == "pending"      # 사람 원인 확인 대기

    turn = svc.dialogue_turn(fid, "강남 현장 담당자", "관할 밖 4km 넘으면 출동 못 해요. F1은 원인 맞아요.", dialogue_llm(), CFG)
    assert [i["status"] for i in turn["items"]] == ["proposed", "proposed"]
    for item in turn["items"]:
        svc.decide_item(fid, item["id"], "confirm", by="김 팀장")
    state = svc.get_flow(fid)
    assert state["meta"]["confirmed_items"] == ["I1", "I2"]
    assert state["score"]["faults"]["P5"]["status"] == "detected"                   # 대화의 판정으로 확정
    assert [t["role"] for t in state["transcript"]] == ["field", "agent"]

    p5km = svc.generate_proposals(fid, proposal_llm(5), CFG)[0]
    assert p5km["status"] == "proposed" and p5km["constraints"][0]["max"] == 4
    p4km = svc.add_manual_proposal(fid, {"title": "관할 4km", "params_changes": [
        {"path": "matching.area_extension_km[2]", "value": 4}]}, author="김 팀장")

    with pytest.raises(ValueError):
        svc.decide_proposal(fid, p4km["id"], "approve", approver="김 팀장")         # 시뮬레이션 전 승인 불가
    sim5 = svc.simulate_proposal(fid, p5km["id"])["simulation"]
    assert sim5["constraint_violations"]                                              # 현장 제약 위반 표시
    sim4 = svc.simulate_proposal(fid, p4km["id"])["simulation"]
    assert sim4["constraint_violations"] == []
    assert sim4["plan"]["after"]["assignment_rate"] > sim4["plan"]["before"]["assignment_rate"]
    assert set(sim4["outcome"][p4km["id"]]) == {"lenient", "normal", "sensitive"}
    assert {r["key"] for r in sim4["recommendations"]} == {"promise_kept_rate", "completed_no_complaint_rate"}

    with pytest.raises(ValueError):
        svc.decide_proposal(fid, p4km["id"], "approve", approver="")
    approved = svc.decide_proposal(fid, p4km["id"], "approve", approver="김 팀장", note="현장 제약 안")
    assert approved["decision"]["params_version_after"] == 2
    state = svc.get_flow(fid)
    assert {p["id"]: p["status"] for p in state["proposals"]} == {"P1": "stale", "P2": "approved"}
    assert state["meta"]["params_version"] == 2 and state["plan"]["assigned"] > 1040
    written = yaml.safe_load((svc.store.dir(fid) / "params.yaml").read_text(encoding="utf-8"))
    assert written["matching"]["area_extension_km"][2] == 4 and written["version"] == 2
    assert state["history"][-1]["changes"]["changes"][0] == {"path": "matching.area_extension_km[2]", "before": 3, "after": 4}


def test_manual_proposal_cannot_change_estimates(svc, flow):
    p = svc.add_manual_proposal(flow["id"], {"title": "승주 가중치", "params_changes": [
        {"path": "weights.difficulty", "value": {"none": 1.0, "pole": 1.9, "outdoor": 1.2, "high_risk": 1.8}}]},
        author="김 팀장")
    assert p["status"] == "invalid" and any("estimate" in e for e in p["errors"])


def test_calibration_path(svc):
    flow = svc.create_flow()
    fid = flow["id"]
    ev = {"table": "duration_ratio", "group_by": "difficulty", "group": "pole"}
    bad = svc.check_calibration(fid, {"path": "weights.difficulty", "key": "pole", "value": 1.9, "source": "x"})
    assert bad["status"] == "invalid"
    good = svc.check_calibration(fid, {"path": "weights.difficulty", "key": "pole", "value": 1.9, "source": "분석",
                                       "evidence": ev})
    assert good["status"] == "checked"
    with pytest.raises(ValueError):
        svc.decide_calibration(fid, bad["id"], "approve", approver="김 팀장")
    svc.decide_calibration(fid, good["id"], "approve", approver="김 팀장", note="실적 확인")
    state = svc.get_flow(fid)
    assert state["meta"]["params_version"] == 2 and state["history"][-1]["type"] == "calibration"
    written = yaml.safe_load((svc.store.dir(fid) / "params.yaml").read_text(encoding="utf-8"))
    assert written["weights"]["difficulty"]["pole"] == 1.9


def test_flow_state_hides_reality_model(svc, flow):
    text = json.dumps(svc.get_flow(flow["id"]), ensure_ascii=False)
    for key in ("by_work_type", "rush_speed_factor", "tolerance_shift", "1.875", "\"truth\""):
        assert key not in text
