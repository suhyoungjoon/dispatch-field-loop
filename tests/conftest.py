from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PROFILES = REPO / "world" / "profiles"
PROFILE_NAMES = ("lenient", "normal", "sensitive")


def profile_path(name: str) -> Path:
    return PROFILES / f"world_{name}.yaml"


@pytest.fixture(scope="session")
def scenario():
    """seed 42, P1~P4, 기본 params (N1 기준선)."""
    from core import load_params
    from domains.dispatch import get_pack
    pack = get_pack()
    instance, _ = pack.generate(42, ["P1", "P2", "P3", "P4"])
    params = load_params(pack)
    return instance, params, pack.solve(instance, params)
