"""[N1] 고정한 코어로 규칙 엔진 기준 결과를 재현한다."""

from pathlib import Path

import core
from core import load_params
from domains.dispatch import get_pack

REPO = Path(__file__).resolve().parents[1]
CORE_TOP_NAMES = ("core", "domains", "api", "scripts", "configs")


def test_core_imports_from_installed_package():
    # 이 레포에 같은 이름의 폴더가 있으면 import가 가려진다 (CLAUDE.md 코어 재사용 규칙)
    for name in CORE_TOP_NAMES:
        assert not (REPO / name).exists(), f"{name}/ 는 코어 패키지 이름과 겹친다"
    assert "site-packages" in Path(core.__file__).resolve().parts


def test_rule_engine_baseline_seed42_p1_p4():
    pack = get_pack()
    params = load_params(pack)
    instance, _ = pack.generate(42, ["P1", "P2", "P3", "P4"])
    decisions = pack.solve(instance, params)
    metrics = pack.metrics(instance, decisions)

    assert params["version"] == 1
    assert len(decisions) == 1500
    assert sum(d.status == "success" for d in decisions) == 1040
    assert round(metrics["on_time_rate"] * len(decisions)) == 741
    assert pack.validate(instance, decisions) == []
