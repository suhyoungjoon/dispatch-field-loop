"""추정값 보정 제안 경로 (원칙 3).

코어 개선안은 estimate 파라미터를 바꿀 수 없다(M13). 추정값은 이 경로로만 바꾼다.
- 제안에는 근거 집계(evidence)가 붙어야 하고, 코드가 실적 레코드로 집계를 다시 계산해 대조한다.
- 상태: checked(검사 통과) / invalid → 사람이 approved / rejected. 승인된 것만 반영(사본)한다.

제안 형식:
  {"path": "weights.difficulty", "key": "pole", "value": 1.9, "source": "...", "rationale": "...",
   "evidence": {"table": "duration_ratio", "group_by": "difficulty", "group": "pole"}}
"""

import copy

from core import check_params, get_path, param_kind

from outcome.aggregate import TABLES


def _current(params: dict, proposal: dict):
    value = get_path(params, proposal["path"])
    return value[proposal["key"]] if proposal.get("key") is not None else value


def _set(params: dict, proposal: dict) -> dict:
    new = copy.deepcopy(params)
    section, key = proposal["path"].split(".", 1)
    if proposal.get("key") is not None:
        new[section][key][proposal["key"]] = proposal["value"]
    else:
        new[section][key] = proposal["value"]
    return new


def evidence_result(proposal: dict, records) -> dict | None:
    ev = proposal.get("evidence") or {}
    if ev.get("table") not in TABLES:
        return None
    return TABLES[ev["table"]](records, ev["group_by"]).get(str(ev.get("group")))


def calibration_errors(params: dict, proposal: dict, records, settings: dict) -> list[str]:
    """비면 통과. settings: flow.yaml의 calibration."""
    path = proposal.get("path", "")
    try:
        kind = param_kind(params, path)
        current = _current(params, proposal)
    except (ValueError, KeyError, TypeError) as exc:
        return [f"{path}: 경로 오류 ({exc})"]
    if kind != "estimate":
        return [f"{path}: estimate 파라미터만 보정 경로로 바꿀 수 있다 (현재 분류: {kind})"]
    if not proposal.get("source"):
        return ["source(누가 제안했는지)가 없다"]
    ev = proposal.get("evidence")
    if not ev:
        return [f"{path}: 실적 근거(evidence)가 없다. 실적 집계 없이 추정값을 바꿀 수 없다"]

    errors = []
    spec = settings["evidence"].get(path)
    if spec is None:
        return [f"{path}: 보정 근거 규칙이 settings에 없다"]
    if ev.get("table") != spec["table"] or ev.get("group_by") != spec["group_by"]:
        errors.append(f"{path}: 근거 집계가 맞지 않다 (필요: {spec['table']} / {spec['group_by']})")
    expected_group = str(proposal["key"]) if proposal.get("key") is not None else "all"
    if str(ev.get("group")) != expected_group:
        errors.append(f"{path}: 근거 구간({ev.get('group')})이 바꾸려는 값({expected_group})과 다르다")
    if errors:
        return errors

    row = evidence_result(proposal, records)
    if row is None or row["n"] < settings["min_samples"]:
        return [f"{path}: 근거 구간의 실적 건수 부족 ({0 if row is None else row['n']} < {settings['min_samples']})"]
    new = proposal["value"]
    if not isinstance(new, (int, float)) or not isinstance(current, (int, float)) or new <= 0:
        return [f"{path}: 숫자 값 하나만 보정할 수 있다"]
    proposed = current / new if spec.get("inverse") else new / current
    observed = row["mean_ratio"]
    if abs(proposed - observed) > settings["ratio_tolerance"]:
        errors.append(f"{path}: 제안 배율 {proposed:.3f}가 실적 배율 {observed:.3f}와 "
                      f"{settings['ratio_tolerance']} 넘게 다르다")
    errors += check_params(_set(params, proposal))
    return errors


def check(params: dict, proposal: dict, records, settings: dict) -> dict:
    errors = calibration_errors(params, proposal, records, settings)
    try:
        current = _current(params, proposal)
    except (ValueError, KeyError, TypeError):
        current = None
    return {"proposal": proposal, "current_value": current, "evidence_result": evidence_result(proposal, records),
            "errors": errors, "status": "invalid" if errors else "checked"}


def approve(item: dict, approver: str, note: str = "") -> dict:
    if item["status"] != "checked":
        raise ValueError(f"검사를 통과한 제안만 승인할 수 있다 (현재: {item['status']})")
    if not approver:
        raise ValueError("승인자(approver)가 필요하다")
    return {**item, "status": "approved", "approver": approver, "note": note}


def reject(item: dict, approver: str, note: str) -> dict:
    if not approver:
        raise ValueError("반려자(approver)가 필요하다")
    return {**item, "status": "rejected", "approver": approver, "note": note}


def apply_calibration(params: dict, item: dict) -> dict:
    """승인된 보정만 params 사본에 반영한다. 원본과 파일은 바꾸지 않는다."""
    if item.get("status") != "approved":
        raise ValueError("사람이 승인한 보정만 반영할 수 있다")
    return _set(params, item["proposal"])
