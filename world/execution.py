"""실행 편차: 실제 작업소요·이동시간과 작업자 하루 동선의 연쇄 지연.

실제 값은 세상 설정(execution)에서만 나온다. params(추정값)를 보정해도 현실은 바뀌지 않는다.
execution 섹션이 없으면 실제 = 추정 (N2와 같다).
"""

import math
import random

from domains.dispatch.models import road_distance
from domains.dispatch.rule_engine import duration_min, travel_min


def _noise(sd: float, key: str) -> float:
    """평균 1인 로그정규 배율. sd가 0이면 정확히 1."""
    if not sd:
        return 1.0
    return math.exp(random.Random(key).gauss(0.0, sd) - sd * sd / 2)


def true_duration(order, world: dict, seed: int, day: int) -> int:
    d = world["execution"]["duration"]
    raw = d["base_min"][order.work_type] * d["difficulty"][order.difficulty] * d["building"][order.building_type]
    return math.ceil(raw * _noise(d["noise_sd"], f"{seed}-{order.id}-{day}-dur"))


def _in_rush(minute: int, rush_hours: list) -> bool:
    return any(lo <= minute < hi for lo, hi in rush_hours)


def true_travel(x1, y1, x2, y2, depart_min: int, world: dict, rng_key: str) -> int:
    t = world["execution"]["travel"]
    speed = t["avg_speed_kmh"] * (t["rush_speed_factor"] if _in_rush(depart_min, t["rush_hours"]) else 1.0)
    raw = road_distance(x1, y1, x2, y2, t["detour_factor"]) / speed * 60
    return math.ceil(raw * _noise(t["noise_sd"], rng_key))


def execute_worker_day(worker, jobs: list[tuple], params: dict, world: dict, seed: int, day: int,
                       respond) -> list[dict]:
    """작업자 하루 일정을 시간순으로 실행한다.

    jobs: [(order, planned_start)]. respond(order, actual_start) -> 고객 반응 (accept/complain/reschedule/cancel).
    수락·불만이면 작업을 하고, 일정 재요청·취소면 도착만 하고 다음으로 간다.
    """
    real = "execution" in world
    loc = (worker.x, worker.y)
    prev_end = None
    out = []
    for order, planned in sorted(jobs, key=lambda j: (j[1], j[0].id)):
        est_travel = travel_min(*loc, order.x, order.y, params)
        depart = planned - est_travel if prev_end is None else prev_end
        travel = (true_travel(*loc, order.x, order.y, depart, world, f"{seed}-{order.id}-{day}-trv")
                  if real else est_travel)
        actual_start = max(planned, depart + travel)
        response = respond(order, actual_start)
        est_dur = duration_min(order, params)
        performed = response in ("accept", "complain")
        actual_dur = (true_duration(order, world, seed, day) if real else est_dur) if performed else None
        prev_end = actual_start + (actual_dur or 0)
        loc = (order.x, order.y)
        out.append({"order": order, "planned_start": planned, "depart_min": depart,
                    "est_travel_min": est_travel, "actual_travel_min": travel,
                    "actual_start_min": actual_start, "arrival_delay_min": actual_start - planned,
                    "est_duration_min": est_dur, "actual_duration_min": actual_dur, "response": response})
    return out
