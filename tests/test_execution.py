"""[N3] 실행 편차: 실제 작업소요·이동, 연쇄 지연, P6 정답."""

import copy

import pytest
from domains.dispatch.rule_engine import duration_min, travel_min

from tests.conftest import PROFILE_NAMES, profile_path
from world.carryover import simulate_outcomes
from world.config import load_world, world_errors
from world.execution import true_duration, true_travel

WORLD = load_world(profile_path("normal"))


def _noiseless(world, *, pole=None, rush=True):
    w = copy.deepcopy(world)
    ex = w["execution"]
    ex["duration"]["noise_sd"] = 0.0
    ex["travel"]["noise_sd"] = 0.0
    if pole is not None:
        ex["duration"]["difficulty"]["pole"] = pole
    if not rush:
        ex["travel"]["rush_hours"] = []
    return w


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_p6_truth_in_every_profile(name, scenario):
    _, params, _ = scenario
    world = load_world(profile_path(name))
    assert world_errors(world) == []
    ex = world["execution"]
    est = params["weights"]["difficulty"]
    assert ex["duration"]["difficulty"]["pole"] / est["pole"] == pytest.approx(1.25)
    for k in ("none", "outdoor", "high_risk"):
        assert ex["duration"]["difficulty"][k] == est[k]
    assert ex["duration"]["base_min"] == params["duration"]["base_min"]
    assert ex["travel"]["avg_speed_kmh"] == params["travel"]["avg_speed_kmh"]
    assert ex["travel"]["rush_speed_factor"] == 0.7
    assert [480, 600] in ex["travel"]["rush_hours"] and [1020, 1140] in ex["travel"]["rush_hours"]
    assert world["truth"]["P6"]["answer"]["duration"]["actual_over_estimate"] == 1.25


def test_true_duration_pole_is_25_percent_longer(scenario):
    instance, params, _ = scenario
    world = _noiseless(WORLD)
    for order in instance.orders[:300]:
        ratio = true_duration(order, world, seed=1, day=order.day) / duration_min(order, params)
        expected = 1.25 if order.difficulty == "pole" else 1.0
        assert ratio == pytest.approx(expected, abs=0.03)    # 추정은 올림(ceil)이라 약간 어긋난다


def test_rush_hour_travel_is_slower(scenario):
    instance, params, _ = scenario
    world = _noiseless(WORLD)
    w, o = instance.workers[0], instance.orders[0]
    calm = true_travel(w.x, w.y, o.x, o.y, depart_min=11 * 60, world=world, rng_key="k")
    rush = true_travel(w.x, w.y, o.x, o.y, depart_min=8 * 60 + 30, world=world, rng_key="k")
    assert calm == pytest.approx(travel_min(w.x, w.y, o.x, o.y, params), abs=1)
    assert rush == pytest.approx(calm / 0.7, abs=1)


def test_no_execution_section_means_no_delay(scenario):
    instance, params, decisions = scenario
    world = copy.deepcopy(WORLD)
    del world["execution"]
    records = simulate_outcomes(instance, decisions, params, world, seed=1)
    arrived = [r for r in records if r.actual_start_min is not None]
    assert arrived and all(r.arrival_delay_min == 0 for r in arrived)


def test_estimates_equal_truth_means_no_delay(scenario):
    instance, params, decisions = scenario
    world = _noiseless(WORLD, pole=1.5, rush=False)
    records = simulate_outcomes(instance, decisions, params, world, seed=1)
    assert all((r.arrival_delay_min or 0) == 0 for r in records)


def test_long_pole_jobs_cascade_to_later_jobs(scenario):
    instance, params, decisions = scenario
    world = _noiseless(WORLD, rush=False)          # P6 소요만 남김
    records = simulate_outcomes(instance, decisions, params, world, seed=1)
    delayed = [r for r in records if (r.arrival_delay_min or 0) > 0]
    assert delayed, "승주 작업이 길어지면 뒤 일정이 밀려야 한다"
    by_worker_day = {}
    for r in records:
        for a in r.attempts:
            if a.get("worker_id"):
                by_worker_day.setdefault((a["worker_id"], a["day"]), []).append((a["start_min"], r, a))
    for r in delayed:
        last = next(a for a in reversed(r.attempts) if a.get("worker_id"))
        earlier = [x for x in by_worker_day[(last["worker_id"], last["day"])] if x[0] < last["start_min"]]
        assert any(x[1].difficulty == "pole" for x in earlier), r.order_id


def test_customer_reacts_to_actual_arrival(scenario):
    instance, params, decisions = scenario
    records = simulate_outcomes(instance, decisions, params, WORLD, seed=2)
    for r in records:
        if r.result in ("completed", "complained"):
            assert r.time_diff_min == r.actual_start_min - r.desired_min
            assert r.actual_start_min == r.start_min + r.arrival_delay_min
            assert r.arrival_delay_min >= 0
            assert r.actual_duration_min > 0 and r.est_duration_min > 0
