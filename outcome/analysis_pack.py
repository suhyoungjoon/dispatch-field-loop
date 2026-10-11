"""분석 agent에 실적 도구를 주는 팩 래퍼 (N4 결정 (가)).

코어 analyze()는 외부 도구 인자가 없고 `Aggregator 도구 + pack.analysis_tools()`만 쓴다.
DomainPack 인터페이스는 바꾸지 않고, 도메인 고유 통계를 넣는 확장 지점인 analysis_tools에 실적 도구를 더한다.
나머지 메서드는 감싼 팩에 그대로 넘긴다.
"""

from outcome.tools import OUTCOME_TOOL_NAMES, outcome_tools

CORE_AGGREGATE_TOOLS = ("overview", "aggregate", "list_items", "count_by_decision_field")

# 코어 관점(perspective) 형식. 질문에 정답(구간·수치)을 넣지 않는다 (원칙 2)
OUTCOME_PERSPECTIVE = {
    "id": "outcome",
    "name": "실적",
    "question": ("배정 계획이 현실에서 어떻게 됐는지(고객 반응, 날짜 이월, 도착 지연, 실제 작업소요·이동시간)를 "
                 "실적 도구(outcome_overview, outcome_by_group, duration_ratio, travel_ratio)로 살펴, "
                 "계획 지표만으로는 드러나지 않는 패턴을 찾아라. 예: 고객 반응이 유난히 나쁜 구간, "
                 "추정과 실제가 크게 다른 구간. 실적 패턴의 근거는 실적 도구 결과를 인용한다."),
    "tools": list(CORE_AGGREGATE_TOOLS) + list(OUTCOME_TOOL_NAMES),
}


class OutcomePack:
    def __init__(self, pack, records, promise_window_min: int):
        self._pack = pack
        self._records = records
        self._window = promise_window_min

    def __getattr__(self, name):
        return getattr(self._pack, name)

    def analysis_tools(self, instance, decisions) -> list[dict]:
        base = self._pack.analysis_tools(instance, decisions)
        clash = {t["name"] for t in base} & set(OUTCOME_TOOL_NAMES)
        if clash:
            raise ValueError(f"도메인 분석 도구와 이름이 겹친다: {sorted(clash)}")
        return base + outcome_tools(self._records, self._window)
