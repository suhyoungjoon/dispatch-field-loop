"""가상 LLM(데모): API 키 없이 분석 → 현장 대화 → AI 개선안 단계를 돌려 보기 위한 미리 정한 응답.

실제 모델이 아니다. 역할별로 정해 둔 도구 호출·제출을 내며, 같은 입력이면 항상 같은 응답이다
(호출 순서는 내부 카운터가 아니라 받은 메시지 기록으로 판단한다). 실행 메타데이터에는 모델명 DEMO_MODEL이 남는다.
앱 코드가 tests/를 import하지 않도록 테스트용 가짜 LLM(tests/fake_llm.py)과 따로 둔다.
"""

import json
import re
from pathlib import Path

from core.llm.client import LLMResponse

REPO = Path(__file__).resolve().parents[1]
DEMO_MODEL = "demo-fake"
ROLES = ("analysis", "dialogue", "proposals")
_KM = re.compile(r"(\d+(?:\.\d+)?)\s*km")


def _tool_use(messages: list[dict], name: str, input: dict) -> dict:
    return {"type": "tool_use", "id": f"demo_toolu_{len(messages)}", "name": name, "input": input}


def _tool_outputs(messages: list[dict], name: str) -> list[dict]:
    """그 이름의 도구 결과 (call_ref 포함, 오래된 것부터)."""
    names = {b["id"]: b["name"] for m in messages if m["role"] == "assistant" for b in m["content"]
             if b.get("type") == "tool_use"}
    out = []
    for m in messages:
        if m["role"] == "user" and not isinstance(m["content"], str):
            for b in m["content"]:
                if b.get("type") == "tool_result" and names.get(b["tool_use_id"]) == name and not b.get("is_error"):
                    out.append(json.loads(b["content"]))
    return out


def _analysis(messages: list[dict]) -> dict:
    found = _tool_outputs(messages, "outcome_by_group")
    if not found:
        return _tool_use(messages, "outcome_by_group", {"group_by": ["work_type"]})
    out = found[-1]
    rows = {r["work_type"]: r for r in out["rows"]}
    repair, install = rows.get("repair"), rows.get("install")
    desc = f"장애 불만율 {repair['complaint_rate']}" + (f", 개통 불만율 {install['complaint_rate']}" if install else "")
    return _tool_use(messages, "submit_report", {"summary": "[데모] 실적에서 장애 고객 불만이 개통보다 높다", "findings": [
        {"title": "[데모] 장애 고객 불만율이 높음", "description": desc, "slice": {"work_type": ["repair"]},
         "hypothesis": "장애 고객은 지연에 더 민감할 수 있다 (데모 가설)", "cited_calls": [out["call_ref"]]}]})


def _last_field_text(messages: list[dict]) -> str:
    """대화 agent 입력의 '# 지금까지의 대화' 마지막 줄 = 이번 현장 발언 (dialogue.agent.render_transcript 형식)."""
    first = messages[0]["content"]
    body = first.split("# 지금까지의 대화\n", 1)[-1].split("\n\n마지막 현장 발언", 1)[0]
    last = body.strip().splitlines()[-1] if body.strip() else ""
    return re.sub(r"^\[[^\]]*\]\s*", "", last).strip()


def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[.?!。]\s*", text) if p.strip()]
    return parts or [text]


def _dialogue(messages: list[dict]) -> dict:
    text = _last_field_text(messages)
    sentences = _sentences(text)
    first = sentences[0]
    items = [{"kind": "fact", "utterance": first, "summary": "[데모] 현장 발언을 사실 항목으로 정리",
              "fact": {"statement": first}}]
    km_sentence = next((s for s in sentences if _KM.search(s)), None)
    if km_sentence:
        km = float(_KM.search(km_sentence).group(1))
        items.append({"kind": "constraint", "utterance": km_sentence,
                      "summary": "[데모] 3단계 관할 확장 거리 상한으로 정리",
                      "constraint": {"type": "param", "path": "matching.area_extension_km[2]",
                                     "max": int(km) if km.is_integer() else km}})
    reply = f"이렇게 이해했습니다: \"{first}\". 정리한 항목을 확인해 주세요. (가상 LLM 데모 응답)"
    return _tool_use(messages, "record_notes", {"reply": reply, "items": items})


def _proposals(messages: list[dict]) -> dict:
    return _tool_use(messages, "submit_proposals", {"proposals": [
        {"kind": "params", "title": "관할 4km (데모)", "rationale": "[데모] 경계 지역 배정 실패를 줄이기 위해 3단계 관할 확장",
         "target_findings": ["F1"], "params_changes": [{"path": "matching.area_extension_km[2]", "value": 4}]}]})


POLICIES = {"analysis": _analysis, "dialogue": _dialogue, "proposals": _proposals}


class DemoLLM:
    model = DEMO_MODEL

    def __init__(self, role: str):
        if role not in POLICIES:
            raise ValueError(f"데모 LLM 역할은 {ROLES} 중 하나")
        self.role = role

    def create(self, *, system, messages, tools, salt=""):
        block = POLICIES[self.role](messages)
        return LLMResponse(content=[block], stop_reason="tool_use",
                           usage={"input_tokens": 0, "output_tokens": 0,
                                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
                           model=self.model)


def make_demo_llm(role: str, llm_settings=REPO / "settings" / "llm.yaml"):
    """(DemoLLM, config). flow.llm.make_llm과 같은 모양이라 화면에서 바꿔 끼울 수 있다."""
    from core.llm.client import load_config
    return DemoLLM(role), load_config(Path(llm_settings), role=role)
