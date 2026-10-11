"""[N5] 현장 의견 대화 agent (가짜 LLM): 대화 → 이해 확인 → 항목 제안 → 사람 확인 → 제약 → 개선 agent 입력."""

import json

import pytest
from core.llm.client import load_config

from dialogue.agent import DialogueContext, dialogue_turn
from dialogue.store import ItemStore
from outcome.scoring import outcome_faults
from tests.conftest import REPO, profile_path
from tests.fake_llm import FakeLLM, tool_use
from world.carryover import simulate_outcomes
from world.config import load_world

LLM_CONFIG = load_config(REPO / "settings" / "llm.yaml", role="analysis")
REPORT = {"summary": "실적 패턴", "findings": [
    {"id": "F1", "title": "장애 고객 불만", "description": "장애 불만율 높음", "slice": {"work_type": ["repair"]},
     "cited_calls": []},
    {"id": "F2", "title": "경계 지역 실패", "description": "OUT_OF_AREA", "slice": {"area_zone": ["boundary"]},
     "cited_calls": []}]}


@pytest.fixture(scope="module")
def ctx(scenario):
    from domains.dispatch import get_pack
    instance, params, decisions = scenario
    world = load_world(profile_path("normal"))
    records = simulate_outcomes(instance, decisions, params, world, seed=1)
    return DialogueContext(pack_factory=get_pack, instance=instance, params=params, decisions=decisions,
                           records=records, report=REPORT, promise_window_min=60)


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


TRANSCRIPT = [
    {"role": "field", "speaker": "강남 현장 담당자", "text": "관할 밖 4km 넘으면 출동 못 해요. 그리고 장애 고객은 30분만 늦어도 민원 들어와요."},
    {"role": "field", "speaker": "강남 현장 담당자", "text": "고객한테는 희망 시각 30분 안에 간다고 약속해요. 장애 불만 발견(F1)은 원인 맞아요."},
]


def good_submit(messages):
    by = _out(messages, "outcome_by_group")
    repair = next(r for r in by["rows"] if r["work_type"] == "repair")
    return tool_use("record_notes", {
        "reply": f"이렇게 이해했습니다. 실적에서도 장애 불만율이 {repair['complaint_rate']}로 높습니다.",
        "items": [
            {"kind": "constraint", "utterance": "관할 밖 4km 넘으면 출동 못 해요",
             "summary": "3단계 관할 확장은 4km까지",
             "constraint": {"type": "param", "path": "matching.area_extension_km[2]", "max": 4}},
            {"kind": "check", "utterance": "장애 고객은 30분만 늦어도 민원 들어와요",
             "summary": "현장 의견과 실적이 맞는지 시간차 구간별로 확인 필요",
             "check": {"field_claim": "장애 고객은 30분 지연부터 민원", "data_summary": "장애 불만율이 높다"},
             "cited_calls": [by["call_ref"]]},
            {"kind": "fact", "utterance": "고객한테는 희망 시각 30분 안에 간다고 약속해요",
             "summary": "약속 기준은 희망 시각 ±30분 (현재 평가 기준 60분과 다름)",
             "fact": {"statement": "약속 기준 ±30분", "topic": "promise_window_min", "value": 30}},
            {"kind": "label", "utterance": "장애 불만 발견(F1)은 원인 맞아요", "summary": "F1 원인 맞음",
             "label": {"finding_id": "F1", "label": "cause_ok"}},
        ]})


def test_turn_proposes_items_and_human_confirms(ctx, tmp_path):
    llm = FakeLLM(scripted([lambda m: tool_use("outcome_by_group", {"group_by": ["work_type"]}), good_submit]))
    store = ItemStore(tmp_path / "items.json")
    turn = dialogue_turn(ctx, TRANSCRIPT, llm, LLM_CONFIG, store=store)
    assert turn["reply"].startswith("이렇게 이해했습니다") and turn["stop"] == "submitted"
    assert [i["kind"] for i in turn["items"]] == ["constraint", "check", "fact", "label"]
    assert all(i["status"] == "proposed" and i["speaker"] == "강남 현장 담당자" for i in turn["items"])
    assert turn["items"][0]["constraint"]["source"] == "강남 현장 담당자"
    assert store.constraints() == []                       # 대화가 규칙을 직접 바꾸지 않는다

    for item in turn["items"]:
        store.confirm(item["id"], by="김 팀장")
    assert store.constraints() == [turn["items"][0]["constraint"]]
    assert store.labels() == {"F1": "cause_ok"}
    # 대화 agent에게 간 입력에 현실 모델 설정이 없다
    sent = json.dumps([c["system"] for c in llm.calls] + [c["messages"] for c in llm.calls], ensure_ascii=False)
    for key in ("by_work_type", "rush_speed_factor", "tolerance_shift", "1.875"):
        assert key not in sent


def test_ungrounded_number_and_invented_utterance_are_sent_back(ctx, tmp_path):
    def bad(messages):
        return tool_use("record_notes", {"reply": "장애 불만율이 77.7%입니다.", "items": [
            {"kind": "fact", "utterance": "현장은 주말에도 일해요", "summary": "주말 근무",
             "fact": {"statement": "주말 근무"}}]})
    llm = FakeLLM(scripted([lambda m: tool_use("outcome_overview", {}), bad, bad]))
    turn = dialogue_turn(ctx, TRANSCRIPT, llm, LLM_CONFIG, store=ItemStore(tmp_path / "i.json"))
    assert turn["feedback_rounds"] == 1                    # 한 번 고쳐 오게 했다
    assert turn["items"] == [] and turn["dropped_items"]     # 말하지 않은 발언을 근거로 한 항목은 뺀다
    assert any("발언" in p for d in turn["dropped_items"] for p in d["problems"])
    assert turn["reply_problems"] and "77.7%" in turn["reply_problems"][0]


def test_confirmed_constraints_reach_improvement_agent(ctx, tmp_path):
    from core.improvement.proposer import propose
    store = ItemStore(tmp_path / "items.json")
    llm = FakeLLM(scripted([lambda m: tool_use("outcome_by_group", {"group_by": ["work_type"]}), good_submit]))
    turn = dialogue_turn(ctx, TRANSCRIPT, llm, LLM_CONFIG, store=store)
    store.confirm(turn["items"][0]["id"], by="김 팀장")

    def prop_policy(item, n, messages, tools):
        if n == 0:
            return tool_use("simulate_params", {"params_changes": [{"path": "matching.area_extension_km[2]", "value": 5}]})
        return tool_use("submit_proposals", {"proposals": []})
    prop_llm = FakeLLM(prop_policy)
    result = propose(ctx.pack_factory, ctx.instance, ctx.params, "", ctx.pack_factory(ctx.params).dimensions(),
                     REPORT, prop_llm, LLM_CONFIG, constraints=store.constraints())
    first_input = prop_llm.calls[0]["messages"][0]["content"]
    assert "지켜야 할 제약" in first_input and "강남 현장 담당자" in first_input
    sim = next(c for c in result["calls"].values() if c["name"] == "simulate_params")
    assert sim["output"]["constraint_violations"]           # 5km는 현장 제약(4km) 위반으로 표시된다


def test_labels_from_dialogue_confirm_outcome_findings():
    """confirm_cause를 켜면 자동 채점이 맞아도 대기이고, 대화에서 확인된 판정으로 확정된다."""
    from core.evaluation.fault_scorer import apply_labels, score
    faults = outcome_faults(load_world(profile_path("normal")), confirm_cause=True)
    calls = {"t1": {"name": "outcome_by_group"}}
    s = score([{"id": "F1", "slice": {"work_type": ["repair"]}, "cited_calls": ["t1"]}], faults, calls)
    assert s["faults"]["P5"]["status"] == "pending" and s["detected"] == 0
    assert apply_labels(s, {"F1": "cause_ok"})["faults"]["P5"]["status"] == "detected"
