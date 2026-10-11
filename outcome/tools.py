"""분석 agent용 실적 집계 도구. 실적 레코드만 받는다 — 현실 모델 설정은 받지도 보지도 않는다 (원칙 2).

도구 형식은 DomainPack.analysis_tools와 같다: {name, description, input_schema, handler(args) -> dict}.
"""

from statistics import mean

from outcome.aggregate import duration_ratio, travel_ratio
from outcome.metrics import compute
from outcome.records import OutcomeRecord

OUTCOME_TOOL_NAMES = ("outcome_overview", "outcome_by_group", "duration_ratio", "travel_ratio")
BAND_STEP_MIN = 15
DERIVED = ("time_diff_band",)
SORT_KEYS = ("complaint_rate", "cancel_rate", "reschedule_rate", "promise_kept_rate", "avg_arrival_delay_min", "items")


def time_diff_band(r: OutcomeRecord) -> str:
    """고객이 겪은 |실제 시작 - 희망 시각|을 15분 단위로. 도착하지 않은 건은 not_arrived."""
    if r.actual_start_min is None:
        return "not_arrived"
    d = abs(r.actual_start_min - r.desired_min)
    if d == 0:
        return "0"
    lo = (d - 1) // BAND_STEP_MIN * BAND_STEP_MIN + 1
    return "121+" if lo > 120 else f"{lo}-{lo + BAND_STEP_MIN - 1}"


def _value(r: OutcomeRecord, key: str) -> str:
    return time_diff_band(r) if key == "time_diff_band" else str(r.dims.get(key))


def _r(x: float) -> float:
    return round(x, 4)


def outcome_tools(records: list[OutcomeRecord], promise_window_min: int) -> list[dict]:
    dims = sorted({k for r in records for k in r.dims})
    groupable = dims + list(DERIVED)

    def overview(args: dict) -> dict:
        m = compute(records, promise_window_min)
        by_result = {res: sum(r.result == res for r in records)
                     for res in ("completed", "complained", "cancelled", "unserved")}
        return {"orders": m["orders"], "by_result": by_result,
                **{k: _r(v) for k, v in m.items() if k != "orders"},
                "promise_window_min": promise_window_min, "group_by_options": groupable}

    def by_group(args: dict) -> dict:
        group_by = args.get("group_by") or []
        bad = [g for g in group_by if g not in groupable]
        if not group_by or bad:
            raise ValueError(f"group_by는 {groupable} 중에서 고른다 (잘못된 값: {bad})")
        filters = args.get("filters") or {}
        bad_f = [k for k in filters if k not in groupable]
        if bad_f:
            raise ValueError(f"filters 키는 {groupable} 중에서 고른다 (잘못된 값: {bad_f})")
        sort_by = args.get("sort_by", "complaint_rate")
        if sort_by not in SORT_KEYS:
            raise ValueError(f"sort_by는 {list(SORT_KEYS)} 중 하나")
        chosen = [r for r in records if all(_value(r, k) in {str(v) for v in vs} for k, vs in filters.items())]
        groups: dict[tuple, list] = {}
        for r in chosen:
            groups.setdefault(tuple(_value(r, g) for g in group_by), []).append(r)
        rows = []
        for key, rs in groups.items():
            if len(rs) < int(args.get("min_items", 10)):
                continue
            m = compute(rs, promise_window_min)
            rows.append({**dict(zip(group_by, key)), "items": len(rs),
                         "complaint_rate": _r(m["complaint_rate"]), "cancel_rate": _r(m["cancel_rate"]),
                         "reschedule_rate": _r(m["reschedule_rate"]), "promise_kept_rate": _r(m["promise_kept_rate"]),
                         "avg_arrival_delay_min": _r(m["avg_arrival_delay_min"])})
        rows.sort(key=lambda row: (-row[sort_by], [row[g] for g in group_by]))
        overall = compute(chosen, promise_window_min) if chosen else {}
        return {"group_by": group_by, "filters": filters, "items": len(chosen),
                "overall_complaint_rate": _r(overall.get("complaint_rate", 0.0)),
                "rows": rows[:int(args.get("limit", 30))]}

    def ratio(fn, extra: tuple):
        def handler(args: dict) -> dict:
            g = args.get("group_by")
            if g not in dims + list(extra):
                raise ValueError(f"group_by는 {dims + list(extra)} 중 하나")
            table = fn(records, g)
            return {"group_by": g, "rows": table,
                    "note": "mean_ratio = 실제 / 추정 (1보다 크면 추정보다 오래 걸림)"}
        return handler

    group_schema = {"type": "array", "items": {"type": "string", "enum": groupable}}
    return [
        {"name": "outcome_overview",
         "description": "배정 계획을 실행한 실적 전체 요약: 결과별 건수(완료·불만·취소·미처리), 약속 준수율, 불만율, "
                        "취소율, 일정 재요청 비율, 평균 이월 일수, 도착 지연. 묶을 수 있는 차원 목록도 준다.",
         "input_schema": {"type": "object", "properties": {}}, "handler": overview},
        {"name": "outcome_by_group",
         "description": "실적을 차원별로 묶어 구간마다 불만율·취소율·일정 재요청 비율·약속 준수율·평균 도착 지연을 준다. "
                        "time_diff_band는 고객이 겪은 희망 시각과 실제 도착의 차이(15분 단위)다.",
         "input_schema": {"type": "object", "properties": {
             "group_by": group_schema,
             "filters": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}}},
             "sort_by": {"type": "string", "enum": list(SORT_KEYS)},
             "min_items": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["group_by"]},
         "handler": by_group},
        {"name": "duration_ratio",
         "description": "작업을 한 건의 실제 작업소요 / 추정 작업소요를 차원별로 준다 (n, 평균, 중앙값).",
         "input_schema": {"type": "object", "properties": {"group_by": {"type": "string", "enum": dims}},
                          "required": ["group_by"]},
         "handler": ratio(duration_ratio, ())},
        {"name": "travel_ratio",
         "description": "작업자가 도착한 건의 실제 이동시간 / 추정 이동시간을 차원별로 준다. "
                        "depart_hour는 작업자 출발 시각의 시다.",
         "input_schema": {"type": "object", "properties": {"group_by": {"type": "string", "enum": dims + ["depart_hour"]}},
                          "required": ["group_by"]},
         "handler": ratio(travel_ratio, ("depart_hour",))},
    ]
