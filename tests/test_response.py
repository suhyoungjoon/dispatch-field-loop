"""[N2] 고객 반응: 구간 선택, 이월 가산, 결정성."""

from tests.conftest import profile_path
from world.config import load_world
from world.response import band_index, draw, response_probs

WORLD = load_world(profile_path("normal"))


def test_band_index_boundaries():
    bands = [0, 30, 60, 90]
    assert [band_index(d, bands) for d in (0, 1, 30, 31, 60, 90, 91, 500)] == [0, 1, 1, 2, 2, 3, 4, 4]


def test_apartment_shift_moves_band():
    house = response_probs(WORLD, "repair", "house", diff_min=25, carry_days=0)
    apt = response_probs(WORLD, "repair", "apartment", diff_min=25, carry_days=0)   # 25 + 10 = 35 → 30~60 구간
    assert house == WORLD["response"]["by_work_type"]["repair"][1]
    assert apt == WORLD["response"]["by_work_type"]["repair"][2]


def test_early_and_late_are_treated_alike():
    assert response_probs(WORLD, "install", "house", -45, 0) == response_probs(WORLD, "install", "house", 45, 0)


def test_carry_days_raise_complain_and_cancel():
    p0 = response_probs(WORLD, "install", "house", 0, 0)
    p2 = response_probs(WORLD, "install", "house", 0, 2)
    assert abs(sum(p2.values()) - 1) < 1e-9
    assert p2["complain"] > p0["complain"] and p2["cancel"] > p0["cancel"]
    assert p2["accept"] < p0["accept"]


def test_draw_is_deterministic_and_follows_probs():
    probs = {"accept": 0.5, "complain": 0.3, "reschedule": 0.2, "cancel": 0.0}
    assert draw(probs, 0.0) == "accept"
    assert draw(probs, 0.49) == "accept"
    assert draw(probs, 0.5) == "complain"
    assert draw(probs, 0.85) == "reschedule"
    assert draw(probs, 0.9999999) == "reschedule"
