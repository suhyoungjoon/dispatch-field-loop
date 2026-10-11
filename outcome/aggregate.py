"""실적 집계. 실적 레코드만 보고, 세상 설정은 보지 않는다 (원칙 2)."""

from statistics import mean, median

from outcome.records import OutcomeRecord


def _group_value(r: OutcomeRecord, group_by: str) -> str:
    if group_by == "depart_hour":
        return f"{r.depart_min // 60:02d}"
    value = getattr(r, group_by, None)
    return str(value if value not in (None, "") else r.dims.get(group_by))


def _ratio_table(pairs: list[tuple[str, float]]) -> dict:
    groups: dict[str, list[float]] = {}
    for g, ratio in pairs:
        groups.setdefault(g, []).append(ratio)
        groups.setdefault("all", []).append(ratio) if g != "all" else None
    return {g: {"n": len(v), "mean_ratio": round(mean(v), 4), "median_ratio": round(median(v), 4)}
            for g, v in sorted(groups.items())}


def duration_ratio(records: list[OutcomeRecord], group_by: str) -> dict:
    """작업을 한 건의 실제 소요 / 추정 소요. {구간 값: {n, mean_ratio, median_ratio}}, 'all'은 전체."""
    return _ratio_table([(_group_value(r, group_by), r.actual_duration_min / r.est_duration_min)
                         for r in records if r.actual_duration_min and r.est_duration_min])


def travel_ratio(records: list[OutcomeRecord], group_by: str) -> dict:
    """작업자가 도착한 건의 실제 이동 / 추정 이동 (추정 0분인 건 제외)."""
    return _ratio_table([(_group_value(r, group_by), r.actual_travel_min / r.est_travel_min)
                         for r in records if r.actual_travel_min is not None and r.est_travel_min])


TABLES = {"duration_ratio": duration_ratio, "travel_ratio": travel_ratio}
