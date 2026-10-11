"""실적 시뮬레이터: 고객 반응 + 날짜 이월 (N2) + 실행 편차·연쇄 지연 (N3).

배정 실패·일정 재요청 건은 다음 날 지시서로 추가하고 그날을 규칙 엔진으로 다시 배정한다 (plan 6장 결정 #2 (a)).
엔진에는 우선순위 입력이 없어 이월 건을 먼저 배정하지 못한다. 희망 시각은 그대로 두며, 같은 희망 시각이면
원래 ID(앞 날짜)가 먼저 정렬되는 정도의 우선만 있다 (N2 결정).
고객은 계획 시각이 아니라 실제 도착 시각에 반응한다.
"""

from collections import defaultdict
from dataclasses import replace
from typing import Callable

from domains.dispatch.models import hhmm_to_min

from outcome.records import OutcomeRecord
from world.execution import execute_worker_day
from world.response import draw, response_probs, uniform

Solve = Callable[[object, dict], list]
EXEC_FIELDS = ("actual_start_min", "arrival_delay_min", "depart_min", "est_travel_min", "actual_travel_min",
               "est_duration_min", "actual_duration_min")


def _default_solve(params: dict) -> Solve:
    from domains.dispatch import get_pack
    return get_pack(params).solve


def solve_by_day(instance, params: dict, solve: Solve) -> list:
    """날짜마다 따로 배정한다. 엔진은 날짜별로 일정을 새로 잡으므로 전체 solve와 결과가 같다."""
    records = []
    for day in sorted({o.day for o in instance.orders}):
        records += solve(replace(instance, orders=[o for o in instance.orders if o.day == day]), params)
    return records


def simulate_outcomes(instance, decisions: list, params: dict, world: dict, seed: int,
                      solve: Solve | None = None) -> list[OutcomeRecord]:
    """계획(decisions)을 날짜 순으로 현실에 적용한 실적. 같은 입력·seed면 같은 결과."""
    solve = solve or _default_solve(params)
    plan = {d.item_id: d for d in decisions}
    max_carry = world["carryover"]["max_carry_days"]
    last_day = instance.days
    days = sorted({o.day for o in instance.orders})
    attempts: dict[str, list[dict]] = {o.id: [] for o in instance.orders}
    last_exec: dict[str, dict] = {}
    results: dict[str, OutcomeRecord] = {}
    pending: list[tuple[object, int]] = []      # (원래 지시서, 이월 횟수)

    for day in range(days[0], last_day + 1):
        todays = pending + [(o, 0) for o in instance.orders if o.day == day]
        pending = []
        if not todays:
            continue
        if any(c for _, c in todays):
            day_inst = replace(instance, orders=[replace(o, day=day) for o, _ in todays])
            decided = {d.item_id: d for d in solve(day_inst, params)}
        else:
            decided = {o.id: plan[o.id] for o, _ in todays}
        carry_of = {o.id: c for o, c in todays}

        # 작업자별 동선 실행 → 실제 도착 시각에 고객 반응
        jobs = defaultdict(list)
        for order, _ in todays:
            dec = decided[order.id]
            if dec.status == "success":
                jobs[dec.decision["worker_id"]].append((order, hhmm_to_min(dec.decision["start_time"])))

        def respond(order, actual_start):
            probs = response_probs(world, order.work_type, order.building_type,
                                   actual_start - order.desired, carry_of[order.id])
            return draw(probs, uniform(seed, order.id, day))

        executed = {}
        for worker_id in sorted(jobs):
            for ex in execute_worker_day(instance.worker_index[worker_id], jobs[worker_id], params, world,
                                         seed, day, respond):
                executed[ex["order"].id] = ex

        for order, carry in todays:
            dec = decided[order.id]
            ex = executed.get(order.id)
            attempt = {"day": day, "plan_status": dec.status, "reason_code": dec.reason_code,
                       "worker_id": dec.decision["worker_id"] if ex else None,
                       "start_min": ex["planned_start"] if ex else None,
                       "response": ex["response"] if ex else None}
            if ex:
                attempt.update({k: ex[k] for k in EXEC_FIELDS})
                last_exec[order.id] = attempt
            attempts[order.id].append(attempt)

            def settle(result, *, final_day=day, carry_days=carry, cancel_reason=None, done=False):
                le = last_exec.get(order.id, {})
                results[order.id] = OutcomeRecord(
                    order_id=order.id, work_type=order.work_type, building_type=order.building_type,
                    dims=dict(dec.dims), original_day=order.day, final_day=final_day, carry_days=carry_days,
                    desired_min=order.desired, start_min=ex["planned_start"] if done else None,
                    time_diff_min=ex["actual_start_min"] - order.desired if done else None,
                    result=result, cancel_reason=cancel_reason, attempts=attempts[order.id],
                    difficulty=order.difficulty, **{k: le.get(k) for k in EXEC_FIELDS})

            if ex:
                response = ex["response"]
                if response == "accept":
                    settle("completed", done=True)
                    continue
                if response == "complain":
                    settle("complained", done=True)
                    continue
                if response == "cancel":
                    settle("cancelled", cancel_reason="customer")
                    continue
            # 배정 실패 또는 일정 재요청 → 다음 날로
            if day == last_day:
                settle("unserved")
            elif carry + 1 > max_carry:
                settle("cancelled", final_day=day + 1, carry_days=carry + 1, cancel_reason="carried_too_long")
            else:
                pending.append((order, carry + 1))

    return [results[o.id] for o in sorted(instance.orders, key=lambda o: (o.day, o.desired, o.id))]
