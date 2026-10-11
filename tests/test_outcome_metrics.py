"""[N2] 실적 지표."""

import pytest

from outcome.metrics import compute
from outcome.records import OutcomeRecord


def rec(oid, result, *, diff=0, carry=0, wt="repair", reason=None, n_resched=0):
    attempts = [{"day": 1, "plan_status": "success", "reason_code": None, "start_min": 600,
                 "response": "reschedule"}] * n_resched
    return OutcomeRecord(order_id=oid, work_type=wt, building_type="house", dims={"work_type": wt},
                         original_day=1, final_day=1 + carry, carry_days=carry, desired_min=600,
                         start_min=None if result in ("cancelled", "unserved") else 600 + diff,
                         time_diff_min=None if result in ("cancelled", "unserved") else diff,
                         result=result, cancel_reason=reason, attempts=attempts)


def test_compute_rates():
    records = [
        rec("a", "completed", diff=0),               # 약속 준수
        rec("b", "completed", diff=45),              # 시간 밖
        rec("c", "complained", diff=20),             # 약속 준수 + 불만
        rec("d", "completed", diff=0, carry=1),      # 날짜 밀림
        rec("e", "cancelled", carry=3, reason="carried_too_long"),
        rec("f", "unserved", carry=1),
        rec("g", "cancelled", reason="customer", n_resched=1),
        rec("h", "completed", diff=-30),             # 이른 도착도 ±30 안
    ]
    m = compute(records, promise_window_min=30)
    assert m["orders"] == 8
    assert m["promise_kept_rate"] == pytest.approx(3 / 8)
    assert m["completion_rate"] == pytest.approx(5 / 8)
    assert m["complaint_rate"] == pytest.approx(1 / 8)
    assert m["cancel_rate"] == pytest.approx(2 / 8)
    assert m["unserved_rate"] == pytest.approx(1 / 8)
    assert m["avg_carry_days"] == pytest.approx((1 + 3 + 1) / 8)
    assert m["reschedule_rate"] == pytest.approx(1 / 8)


def test_compute_empty():
    assert compute([], promise_window_min=30)["orders"] == 0


def test_arrival_delay_metrics():
    records = [rec(str(i), "completed") for i in range(10)]
    for i, r in enumerate(records):
        r.arrival_delay_min = i * 10               # 0, 10, ..., 90
    records.append(rec("x", "unserved"))           # 도착하지 않은 건은 빼고 계산
    m = compute(records, promise_window_min=60)
    assert m["avg_arrival_delay_min"] == pytest.approx(45)
    assert m["p90_arrival_delay_min"] == 90
