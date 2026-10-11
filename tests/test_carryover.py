"""[N2] 실적 시뮬레이션: 날짜 이월과 재현성."""

import copy
from dataclasses import replace

from domains.dispatch.rule_engine import solve

from tests.conftest import profile_path
from world.carryover import simulate_outcomes, solve_by_day
from world.config import load_world

WORLD = load_world(profile_path("normal"))


def _always(world, outcome):
    w = copy.deepcopy(world)
    for rows in w["response"]["by_work_type"].values():
        for row in rows:
            row.update({"accept": 0.0, "complain": 0.0, "reschedule": 0.0, "cancel": 0.0, outcome: 1.0})
    w["carryover"]["per_day"] = {"complain": 0.0, "cancel": 0.0}
    return w


def test_solving_day_by_day_matches_engine(scenario):
    instance, params, decisions = scenario
    assert [(d.item_id, d.status, d.decision) for d in solve_by_day(instance, params, solve)] == \
           [(d.item_id, d.status, d.decision) for d in decisions]


def test_same_seed_same_outcomes(scenario):
    instance, params, decisions = scenario
    a = simulate_outcomes(instance, decisions, params, WORLD, seed=7)
    b = simulate_outcomes(instance, decisions, params, WORLD, seed=7)
    c = simulate_outcomes(instance, decisions, params, WORLD, seed=8)
    assert a == b
    assert a != c
    assert len(a) == len(instance.orders)
    assert {r.order_id for r in a} == {o.id for o in instance.orders}


def test_all_accept_without_carry_completes_successes(scenario):
    instance, params, decisions = scenario
    one_day = replace(instance, orders=[o for o in instance.orders if o.day == instance.days])
    plan = [d for d in decisions if d.item_id in {o.id for o in one_day.orders}]
    records = simulate_outcomes(one_day, plan, params, _always(WORLD, "accept"), seed=1)
    by_id = {r.order_id: r for r in records}
    for d in plan:
        r = by_id[d.item_id]
        if d.status == "success":
            assert r.result == "completed" and r.carry_days == 0
            assert r.start_min is not None and r.time_diff_min is not None
        else:                                   # 마지막 날 실패 → 넘길 날이 없음
            assert r.result == "unserved"


def test_failed_orders_carry_and_cancel_after_two_days(scenario):
    instance, params, decisions = scenario
    records = simulate_outcomes(instance, decisions, params, _always(WORLD, "accept"), seed=1)
    carried = [r for r in records if r.carry_days > 0]
    assert carried, "실패 건이 다음 날로 넘어가야 한다"
    for r in records:
        assert r.carry_days <= 3
        assert r.final_day == r.original_day + min(r.carry_days, instance.days - r.original_day)
        if r.carry_days == 3:
            assert r.result == "cancelled" and r.cancel_reason == "carried_too_long"
    assert any(r.cancel_reason == "carried_too_long" for r in records)
    # 이월 건은 하루에 한 번만 시도한다
    for r in records:
        days = [a["day"] for a in r.attempts]
        assert days == sorted(set(days))


def test_reschedule_moves_order_to_next_day(scenario):
    instance, params, decisions = scenario
    records = simulate_outcomes(instance, decisions, params, _always(WORLD, "reschedule"), seed=1)
    for r in records:
        assert r.result in {"cancelled", "unserved"}
        first = r.attempts[0]
        if first["plan_status"] == "success":
            assert first["response"] == "reschedule"


def test_plan_on_day_one_is_the_given_decisions(scenario):
    instance, params, decisions = scenario
    records = simulate_outcomes(instance, decisions, params, WORLD, seed=3)
    plan = {d.item_id: d for d in decisions}
    for r in records:
        if r.original_day == 1:
            assert r.attempts[0]["plan_status"] == plan[r.order_id].status
