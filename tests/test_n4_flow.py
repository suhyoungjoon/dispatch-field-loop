"""[N4] 실적 → 분석 agent(가짜 LLM) → 채점 흐름."""

import json

from core.llm.client import load_config

from flow.n4_analysis import run_analysis
from tests.conftest import REPO, profile_path
from tests.fake_llm import FakeLLM, tool_use


def _tool_output(messages, name):
    """가장 최근 그 이름의 도구 결과 (call_ref 포함)."""
    ids = {b["id"]: b["name"] for m in messages if m["role"] == "assistant" for b in m["content"]
           if b.get("type") == "tool_use"}
    for m in reversed(messages):
        if m["role"] != "user" or isinstance(m["content"], str):
            continue
        for b in m["content"]:
            if b.get("type") == "tool_result" and ids.get(b["tool_use_id"]) == name:
                return json.loads(b["content"])
    return None


def _policy(item, n, messages, tools):
    steps = [lambda: tool_use("outcome_by_group", {"group_by": ["work_type"]}),
             lambda: tool_use("duration_ratio", {"group_by": "difficulty"}),
             lambda: tool_use("travel_ratio", {"group_by": "hour"})]
    if n < len(steps):
        return steps[n]()
    wt = _tool_output(messages, "outcome_by_group")
    dur = _tool_output(messages, "duration_ratio")
    trv = _tool_output(messages, "travel_ratio")
    repair = next(r for r in wt["rows"] if r["work_type"] == "repair")
    return tool_use("submit_report", {"summary": "실적 패턴", "findings": [
        {"title": "장애 고객 불만", "description": f"장애 불만율 {repair['complaint_rate']}",
         "slice": {"work_type": ["repair"]}, "cited_calls": [wt["call_ref"]]},
        {"title": "승주 소요 과소 추정", "description": f"승주 실제/추정 {dur['rows']['pole']['mean_ratio']}",
         "slice": {"difficulty": ["pole"]}, "cited_calls": [dur["call_ref"]]},
        {"title": "오전 이동 지연", "description": f"09시 실제/추정 이동 {trv['rows']['09']['mean_ratio']}",
         "slice": {"hour": ["09", "10"]}, "cited_calls": [trv["call_ref"]]},
    ]})


def test_fake_llm_finds_p5_p6(tmp_path):
    llm = FakeLLM(_policy)
    out = run_analysis(data_seed=42, faults=["P1", "P2", "P3", "P4"], world_path=profile_path("normal"),
                       outcome_seed=1, flow_path=REPO / "settings" / "flow.yaml",
                       llm=llm, llm_config=load_config(REPO / "settings" / "llm.yaml", role="analysis"))
    report, scored, meta = out["report"], out["score"], out["meta"]
    assert report["stop"] == "submitted" and len(report["findings"]) == 3 and not report["dropped"]
    assert (scored["detected"], scored["total"]) == (3, 3)
    assert meta["data_seed"] == 42 and meta["outcome_seed"] == 1 and meta["profile"] == "normal"
    assert meta["llm_model"] == "fake-model" and meta["params_version"] == 1 and meta["core_ref"]
    assert meta["perspective"] == "outcome"
    # 분석 agent에게 간 입력에 현실 모델 설정 원문이 없다 (원칙 2)
    sent = json.dumps([c["system"] for c in llm.calls] + [c["messages"] for c in llm.calls], ensure_ascii=False)
    for key in ("by_work_type", "rush_speed_factor", "tolerance_shift", "truth", "1.875"):
        assert key not in sent
