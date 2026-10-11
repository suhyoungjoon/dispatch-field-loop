"""실적 레코드: 지시서 하나마다 하나."""

from dataclasses import dataclass, field

RESULTS = ("completed", "complained", "cancelled", "unserved")


@dataclass
class OutcomeRecord:
    order_id: str
    work_type: str
    building_type: str
    dims: dict[str, str]             # 마지막으로 시도한 날의 분석 차원 값 (DecisionRecord.dims)
    original_day: int
    final_day: int                   # 결과가 정해진 날 (이월 한도 초과 취소는 넘어갈 예정이던 날)
    carry_days: int                  # 다음 날로 넘어간 횟수
    desired_min: int
    start_min: int | None            # 완료된 배정의 계획 시작 시각 (완료가 아니면 None)
    time_diff_min: int | None        # 실제 시작 - 희망 시각 (고객이 겪은 차이)
    result: str                      # RESULTS
    cancel_reason: str | None        # customer | carried_too_long
    attempts: list[dict] = field(default_factory=list)   # [{day, plan_status, reason_code, worker_id, start_min, response, ...실행}]
    difficulty: str = ""
    # --- 실행 (N3): 마지막으로 작업자가 도착한 시도 기준. 도착한 적이 없으면 None
    actual_start_min: int | None = None
    arrival_delay_min: int | None = None     # 실제 시작 - 계획 시작 (0 이상)
    depart_min: int | None = None
    est_travel_min: int | None = None
    actual_travel_min: int | None = None
    est_duration_min: int | None = None      # 추정 소요 (params)
    actual_duration_min: int | None = None   # 실제 소요 (작업을 한 경우만)
