"""실적 지표. 분모는 모두 전체 지시서 수다."""

from outcome.records import OutcomeRecord


def compute(records: list[OutcomeRecord], promise_window_min: int) -> dict[str, float]:
    n = len(records)
    if n == 0:
        return {"orders": 0}

    def rate(pred) -> float:
        return sum(1 for r in records if pred(r)) / n

    done = ("completed", "complained")
    delays = sorted(r.arrival_delay_min for r in records if r.arrival_delay_min is not None)
    return {
        "orders": n,
        "promise_kept_rate": rate(lambda r: r.result in done and r.final_day == r.original_day
                                  and abs(r.time_diff_min) <= promise_window_min),
        "completion_rate": rate(lambda r: r.result in done),
        "complaint_rate": rate(lambda r: r.result == "complained"),
        "cancel_rate": rate(lambda r: r.result == "cancelled"),
        "unserved_rate": rate(lambda r: r.result == "unserved"),
        "reschedule_rate": rate(lambda r: any(a.get("response") == "reschedule" for a in r.attempts)),
        "avg_carry_days": sum(r.carry_days for r in records) / n,
        # 도착 지연: 작업자가 도착한 건 기준 (계획 시작 대비)
        "avg_arrival_delay_min": sum(delays) / len(delays) if delays else 0.0,
        "p90_arrival_delay_min": float(delays[min(len(delays) - 1, int(0.9 * len(delays)))]) if delays else 0.0,
    }
