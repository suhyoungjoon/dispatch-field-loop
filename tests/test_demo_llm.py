"""[N6] 가상 LLM(데모) 모드: API 키 없이 분석 → 현장 대화 → AI 개선안이 검사를 통과하며 돈다."""

import pytest

from flow.demo_llm import DEMO_MODEL, DemoLLM, make_demo_llm
from flow.service import FlowService
from tests.conftest import REPO

FIELD = "강남 현장 담당자"
TEXT = "관할 밖 4km 넘으면 출동 못 해요. 장애 고객은 기다리는 걸 싫어해요."


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    svc = FlowService(root=tmp_path_factory.mktemp("demo"))
    fid = svc.create_flow({"name": "데모"})["id"]
    report = svc.run_analysis(fid, *make_demo_llm("analysis"))
    turn = svc.dialogue_turn(fid, FIELD, TEXT, *make_demo_llm("dialogue"))
    for item in turn["items"]:
        svc.decide_item(fid, item["id"], "confirm", by="김 팀장")
    proposals = svc.generate_proposals(fid, *make_demo_llm("proposals"))
    return svc, fid, report, turn, proposals


def test_demo_analysis_is_grounded(run):
    _, _, report, _, _ = run
    assert report["stop"] == "submitted" and report["dropped"] == [] and report["feedback_rounds"] == 0
    f = report["findings"][0]
    assert f["slice"] == {"work_type": ["repair"]} and f["cited_calls"]


def test_demo_dialogue_items_pass_checks(run):
    _, _, _, turn, _ = run
    assert turn["stop"] == "submitted" and turn["dropped_items"] == [] and turn["reply_problems"] == []
    kinds = {i["kind"]: i for i in turn["items"]}
    assert kinds["fact"]["fact"]["statement"] and kinds["fact"]["speaker"] == FIELD
    assert kinds["constraint"]["constraint"] == {"type": "param", "path": "matching.area_extension_km[2]",
                                                 "max": 4, "source": FIELD}
    assert all(i["utterance"] in TEXT for i in turn["items"])


def test_demo_proposal_is_valid_and_uses_confirmed_constraint(run):
    svc, fid, _, _, proposals = run
    assert len(proposals) == 1 and proposals[0]["status"] == "proposed" and proposals[0]["errors"] == []
    assert proposals[0]["source"] == f"ai ({DEMO_MODEL})"
    assert proposals[0]["constraints"][0]["max"] == 4
    sim = svc.simulate_proposal(fid, proposals[0]["id"])["simulation"]
    assert sim["constraint_violations"] == []


def test_demo_model_in_run_metadata(run):
    svc, fid, _, _, _ = run
    state = svc.get_flow(fid)
    assert state["meta"]["llm_models"] == {"analysis": DEMO_MODEL, "dialogue": DEMO_MODEL, "proposals": DEMO_MODEL}
    assert state["transcript"][-1]["model"] == DEMO_MODEL


def test_demo_is_deterministic_and_role_checked():
    msgs = [{"role": "user", "content": "# 지금까지의 대화\n[현장] 4km까지요.\n\n마지막 현장 발언에 답하라."}]
    a = DemoLLM("dialogue").create(system="", messages=msgs, tools=[])
    b = DemoLLM("dialogue").create(system="", messages=msgs, tools=[])
    assert a.content == b.content and a.model == DEMO_MODEL
    with pytest.raises(ValueError):
        DemoLLM("customer")


def test_app_demo_mode_runs_ai_steps(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("FIELD_FLOW_DIR", str(tmp_path))
    at = AppTest.from_file(str(REPO / "flow" / "app.py"), default_timeout=180)
    at.run()
    at.sidebar.radio(key="ai_mode_choice").set_value("demo")
    at.sidebar.button[0].click()                          # 흐름 만들기
    at.run()
    assert not at.exception
    assert any("가상 LLM(데모) 모드" in i.value for i in at.info)

    next(b for b in at.button if b.label == "분석 실행").click()
    at.run()
    assert not at.exception
    assert any("데모 결과" in w.value for w in at.warning)

    at.chat_input[0].set_value(TEXT)
    at.run()
    assert not at.exception
    assert any("데모 결과" in c.value for c in at.caption)
    assert any("발언" in c.value and "4km" in c.value for c in at.caption)

    next(b for b in at.button if b.label == "AI 개선안 받기").click()
    at.run()
    assert not at.exception
    assert any("관할 4km (데모)" in e.label for e in at.expander)
