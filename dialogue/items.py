"""현장 의견 대화에서 정리하는 구조화 항목.

종류:
- constraint: 코어 제약 형식 그대로 (core.improvement.constraints). source는 말한 사람
- fact: 데이터에 없는 현장 정보 {statement, topic?, value?}
- check: 현장 의견과 데이터가 어긋나거나 확인이 필요한 지점 {field_claim, data_summary} + 실적 도구 인용
- label: 발견 판정, 코어 labels 형식 {finding_id, label: cause_ok | cause_wrong | false_positive}
상태: proposed(AI 제안) → confirmed / rejected (사람만). 확인된 항목만 개선 흐름에 넘긴다.
"""

from datetime import datetime, timezone

from core.improvement.constraints import constraint_errors

KINDS = ("constraint", "fact", "check", "label")
LABELS = ("cause_ok", "cause_wrong", "false_positive")
STATUSES = ("proposed", "confirmed", "rejected")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_item(kind: str, *, speaker: str, utterance: str, summary: str, cited_calls: list[str] | None = None,
             **content) -> dict:
    """content: 종류 이름과 같은 키 하나 (constraint=..., fact=..., check=..., label=...)."""
    if kind not in KINDS:
        raise ValueError(f"알 수 없는 항목 종류: {kind} ({KINDS})")
    body = dict(content.get(kind) or {})
    if kind == "constraint":
        body.setdefault("source", speaker)
    return {"id": None, "kind": kind, "speaker": speaker, "ts": now(), "utterance": utterance, "summary": summary,
            kind: body, "cited_calls": list(cited_calls or []), "status": "proposed",
            "decided_by": None, "decided_at": None, "note": None}


def item_errors(item: dict, params: dict, metric_names: list[str], finding_ids: set[str]) -> list[str]:
    """종류별 형식 검사. 비면 통과. 대화 맥락(발언·수치 근거)은 dialogue.agent가 따로 본다."""
    kind = item.get("kind")
    if kind not in KINDS:
        return [f"알 수 없는 항목 종류: {kind}"]
    errors = []
    if not item.get("speaker"):
        errors.append("말한 사람(speaker)이 없다")
    if not str(item.get("summary") or "").strip():
        errors.append("이해한 내용(summary)이 없다")
    body = item.get(kind) or {}
    if kind == "constraint":
        errors += constraint_errors([body], params, metric_names)
    elif kind == "fact":
        if not str(body.get("statement") or "").strip():
            errors.append("fact.statement가 없다")
    elif kind == "check":
        if not body.get("field_claim") or not body.get("data_summary"):
            errors.append("check에는 field_claim과 data_summary가 필요하다")
        if not item.get("cited_calls"):
            errors.append("check는 데이터 근거(cited_calls)를 인용해야 한다")
    elif kind == "label":
        if body.get("finding_id") not in finding_ids:
            errors.append(f"리포트에 없는 발견: {body.get('finding_id')} (있는 발견: {sorted(finding_ids)})")
        if body.get("label") not in LABELS:
            errors.append(f"label은 {LABELS} 중 하나")
    return errors
