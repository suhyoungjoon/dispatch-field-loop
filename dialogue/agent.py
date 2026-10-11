"""현장 의견 대화 agent: 대화 한 턴마다 도구로 데이터를 확인하고, 답변과 구조화 항목(제안)을 record_notes로 낸다.

- 답변의 수치와 check 항목의 데이터 요약 수치는 도구 결과나 현장 발언에 있어야 한다 (코어 근거 검사 재사용).
- 항목의 utterance는 실제 현장 발언 원문 일부여야 한다 (말하지 않은 것을 정리하지 않는다).
- 항목은 모두 proposed로 저장된다. 확인은 사람만 한다 (dialogue.store). 대화가 규칙을 직접 바꾸지 않는다.
- 도구는 실적 집계뿐이다. 현실 모델 설정은 받지 않는다 (원칙 2).
"""

from dataclasses import dataclass
from typing import Callable

from core import apply_params, params_errors, params_view, simulate_params
from core.analysis.grounding import numbers_in, unsupported_numbers
from core.llm.tool_loop import resolve_call, run_tool_loop, usage_dict

from dialogue.items import KINDS, LABELS, item_errors, new_item
from outcome.tools import OUTCOME_TOOL_NAMES, outcome_tools

SUBMIT = "record_notes"

SYSTEM = """너는 출동 배정 개선을 돕는 현장 의견 정리 담당이다. 현장 담당자와 대화하며 그들의 판단을 구조화한다.

규칙:
- 너는 규칙을 바꾸지 않는다. 정리한 항목은 '제안'이고, 사람이 확인해야 반영된다.
- 정리할 것이 생기면 답변을 "이렇게 이해했습니다"로 시작해 무엇을 어떻게 이해했는지 짧게 되묻는다.
- 데이터에 대한 수치는 도구 결과에 있는 그대로만 말한다. 계산해서 새 수치를 만들지 않는다.
- 항목 종류:
  - constraint: 지켜야 할 한도. 코어 제약 형식 {type: param, path, min|max} 또는 {type: metric, metric, min|max|max_drop|max_rise}
  - fact: 데이터에 없는 현장 정보 {statement, topic?, value?}
  - check: 현장 의견과 실적 데이터가 어긋나거나 확인이 필요한 지점 {field_claim, data_summary}. 실적 도구 결과를 cited_calls로 인용
  - label: 분석 리포트 발견에 대한 판정 {finding_id, label: cause_ok | cause_wrong | false_positive}
- 항목마다 utterance에 근거가 된 현장 발언을 원문 그대로 일부 옮긴다.
- 현장 의견이 실적과 맞는지 실적 도구로 대조해 보고, 어긋나거나 데이터로 판단이 안 되면 check로 올린다.
- 끝나면 record_notes로 답변과 항목을 제출한다."""


@dataclass
class DialogueContext:
    pack_factory: Callable
    instance: object
    params: dict
    decisions: list
    records: list
    report: dict
    promise_window_min: int

    def metric_names(self) -> list[str]:
        return sorted(self.pack_factory(self.params).metrics(self.instance, self.decisions))

    def finding_ids(self) -> set[str]:
        return {f["id"] for f in self.report.get("findings", [])}


def submit_tool() -> dict:
    item = {"type": "object", "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "utterance": {"type": "string", "description": "근거가 된 현장 발언 원문 일부"},
        "summary": {"type": "string", "description": "이렇게 이해했다는 한 문장"},
        "constraint": {"type": "object"}, "fact": {"type": "object"}, "check": {"type": "object"},
        "label": {"type": "object", "properties": {"finding_id": {"type": "string"},
                                                   "label": {"type": "string", "enum": list(LABELS)}}},
        "cited_calls": {"type": "array", "items": {"type": "string"}}},
        "required": ["kind", "utterance", "summary"]}
    return {"name": SUBMIT, "description": "현장 담당자에게 할 답변과 정리한 항목(제안)을 제출한다.",
            "input_schema": {"type": "object", "properties": {"reply": {"type": "string"},
                                                              "items": {"type": "array", "items": item}},
                             "required": ["reply", "items"]}}


def dialogue_tools(ctx: DialogueContext) -> list[dict]:
    def get_report(args):
        keys = ("id", "title", "description", "slice", "reason_codes", "hypothesis")
        return {"summary": ctx.report.get("summary"),
                "findings": [{k: f.get(k) for k in keys if f.get(k) is not None} for f in ctx.report.get("findings", [])]}

    def get_params(args):
        return {"params": ctx.params, **params_view(ctx.params)}

    def simulate(args):
        dims = ctx.pack_factory(ctx.params).dimensions()
        errors = params_errors(ctx.params, args, dims)
        if errors:
            return {"error": "; ".join(errors)}
        return simulate_params(ctx.pack_factory, ctx.instance, ctx.params, apply_params(ctx.params, args))

    changes = {"type": "array", "items": {"type": "object", "properties": {"path": {"type": "string"}, "value": {}}}}
    return [
        {"name": "get_report", "description": "분석 리포트의 발견 목록 (id, 제목, 설명, 구간, 원인 가설).",
         "input_schema": {"type": "object", "properties": {}}, "handler": get_report},
        {"name": "get_params", "description": "현재 규칙 파라미터와 분류 (바꿀 수 있는 것 / 참고만).",
         "input_schema": {"type": "object", "properties": {}}, "handler": get_params},
        {"name": "simulate_params", "description": "파라미터 변경을 임시 적용해 규칙 엔진 계획 지표 전후를 본다 (반영 아님).",
         "input_schema": {"type": "object", "properties": {"params_changes": changes, "override_rules": {"type": "array"}}},
         "handler": simulate},
    ] + outcome_tools(ctx.records, ctx.promise_window_min)


def render_transcript(transcript: list[dict]) -> str:
    return "\n".join(f"[{t.get('speaker') or t['role']}] {t['text']}" for t in transcript)


def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


def _speaker_of(utterance: str, transcript: list[dict]) -> str | None:
    u = _norm(utterance)
    for t in reversed(transcript):
        if t["role"] == "field" and u and u in _norm(t["text"]):
            return t.get("speaker") or "현장"
    return None


def _field_numbers(transcript: list[dict]) -> list[float]:
    return [n for t in transcript if t["role"] == "field" for n in numbers_in(t["text"])]


def _build(raw: dict, transcript: list[dict]) -> dict:
    kind = raw.get("kind")
    speaker = _speaker_of(raw.get("utterance", ""), transcript)
    item = new_item(kind if kind in KINDS else "fact", speaker=speaker or "", utterance=raw.get("utterance", ""),
                    summary=raw.get("summary", ""), cited_calls=raw.get("cited_calls"),
                    **({kind: raw.get(kind)} if kind in KINDS else {}))
    if kind not in KINDS:
        item["kind"] = kind
    return item


def item_problems(raw: dict, transcript: list[dict], calls: dict, ctx: DialogueContext) -> list[str]:
    if _speaker_of(raw.get("utterance", ""), transcript) is None:
        return ["utterance가 현장 발언에 없다 (말한 내용을 원문 그대로 옮긴다)"]
    item = _build(raw, transcript)
    problems = item_errors(item, ctx.params, ctx.metric_names(), ctx.finding_ids())
    if item["kind"] == "check" and item.get("cited_calls"):
        cited = [resolve_call(c, calls) for c in item["cited_calls"]]
        if not all(cited) or any(calls[c]["name"] not in OUTCOME_TOOL_NAMES for c in cited):
            problems.append("check는 실적 도구 결과(호출 번호)를 인용해야 한다")
        else:
            sources = [n for c in cited for n in numbers_in(calls[c]["output"]) + numbers_in(calls[c]["input"])]
            bad = unsupported_numbers(str((item.get("check") or {}).get("data_summary", "")), sources + _field_numbers(transcript))
            if bad:
                problems.append(f"data_summary의 근거 없는 수치 {', '.join(bad)}")
    return problems


def reply_problems(reply: str, transcript: list[dict], calls: dict) -> list[str]:
    sources = [n for c in calls.values() for n in numbers_in(c["output"]) + numbers_in(c["input"])]
    bad = unsupported_numbers(reply, sources + _field_numbers(transcript))
    return [f"답변의 근거 없는 수치 {', '.join(bad)} (도구 결과나 현장 발언에 있는 수치만 쓴다)"] if bad else []


def dialogue_turn(ctx: DialogueContext, transcript: list[dict], llm, llm_config: dict, store=None,
                  salt: str = "", max_calls: int = 12) -> dict:
    """transcript: [{role: field | agent, speaker, text}]. store가 있으면 통과한 항목을 proposed로 저장한다."""
    def check(submission: dict, calls: dict) -> list[str]:
        out = reply_problems(submission.get("reply", ""), transcript, calls)
        for i, raw in enumerate(submission.get("items") or []):
            out += [f"items[{i}] ({raw.get('kind')}): {p}" for p in item_problems(raw, transcript, calls, ctx)]
        return out

    user = ("# 지금까지의 대화\n" + render_transcript(transcript)
            + "\n\n마지막 현장 발언에 답하라. 필요하면 도구로 리포트·실적을 확인하고, 정리할 항목이 있으면 함께 제출하라.")
    result = run_tool_loop(llm, system=SYSTEM, user=user, tools=dialogue_tools(ctx), submit_tool=submit_tool(),
                           max_calls=max_calls, salt=salt, check_submission=check)
    submission = result.submission or {}
    items, dropped = [], []
    for raw in submission.get("items") or []:
        problems = item_problems(raw, transcript, result.calls, ctx)
        if problems:
            dropped.append({"item": raw, "problems": problems})
            continue
        item = _build(raw, transcript)
        items.append(store.add(item) if store is not None else item)
    reply = submission.get("reply", "")
    return {"reply": reply, "reply_problems": reply_problems(reply, transcript, result.calls),
            "items": items, "dropped_items": dropped, "calls": result.calls, "stop": result.stop,
            "feedback_rounds": result.feedback_rounds, "usage": usage_dict(result, llm.model, llm_config)}
