"""[N2] 세상 설정 파일 형식과 P5 정답."""

import pytest

from tests.conftest import PROFILE_NAMES, profile_path
from world.config import OUTCOMES, load_world, world_errors


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_profiles_are_valid(name):
    world = load_world(profile_path(name))
    assert world["profile"] == name
    assert world_errors(world) == []


def test_world_errors_catch_bad_rows():
    world = load_world(profile_path("normal"))
    world["response"]["by_work_type"]["repair"][0]["accept"] = 0.5
    world["response"]["by_work_type"]["install"].pop()
    errors = world_errors(world)
    assert any("repair" in e and "합" in e for e in errors)
    assert any("install" in e and "구간" in e for e in errors)


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_p5_repair_complaints_jump_after_30_min(name):
    rows = load_world(profile_path(name))["response"]["by_work_type"]
    repair, install = rows["repair"], rows["install"]
    # 구간 1 = 30분 이내, 구간 2 = 30~60분
    assert repair[2]["complain"] >= 2.5 * repair[1]["complain"]
    assert repair[2]["complain"] >= 3 * install[2]["complain"]
    assert install[2]["accept"] >= 0.8        # 개통은 ±60분까지 대체로 수락


def test_profiles_are_ordered_by_sensitivity():
    worlds = [load_world(profile_path(n)) for n in PROFILE_NAMES]
    for wt in ("install", "repair"):
        for band in range(5):
            accepts = [w["response"]["by_work_type"][wt][band]["accept"] for w in worlds]
            assert accepts == sorted(accepts, reverse=True)
    assert set(OUTCOMES) == {"accept", "complain", "reschedule", "cancel"}
