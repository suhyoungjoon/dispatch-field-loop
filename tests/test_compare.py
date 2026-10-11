"""[N2] 프로필별 최고안 표시 규칙 (원칙 6)."""

from outcome.compare import recommendation


def _result(scores: dict[str, dict[str, float]]) -> dict:
    return {cid: {"outcome": {p: {"k": v} for p, v in by_p.items()}} for cid, by_p in scores.items()}


def test_recommended_when_enough_profiles_agree():
    result = _result({"a": {"x": 1, "y": 1, "z": 0}, "b": {"x": 0, "y": 0, "z": 1}})
    rec = recommendation(result, ["x", "y", "z"], "k", min_agree=2)
    assert rec["recommended"] == "a" and rec["agree"] == 2


def test_withheld_when_profiles_disagree():
    result = _result({"a": {"x": 1, "y": 0, "z": 0}, "b": {"x": 0, "y": 1, "z": 0}, "c": {"x": 0, "y": 0, "z": 1}})
    assert recommendation(result, ["x", "y", "z"], "k", min_agree=2)["recommended"] is None
