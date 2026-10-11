"""개선안마다 계획 지표와 실적 지표를 함께 계산한다 (세상 프로필 × 실적 seed)."""

from statistics import mean

from core import apply_params
from domains.dispatch import get_pack

from outcome.metrics import compute
from world.carryover import simulate_outcomes


def plan_summary(pack, instance, decisions) -> dict:
    m = pack.metrics(instance, decisions)
    n = len(decisions)
    return {"assigned": sum(d.status == "success" for d in decisions),
            "on_time": round(m["on_time_rate"] * n),
            "violations": len(pack.validate(instance, decisions)),
            "avg_travel_min": m["avg_travel_min"]}


def outcome_summary(records, promise_window_min: int) -> dict:
    m = compute(records, promise_window_min)
    n = m["orders"]
    by_wt = {}
    for wt in ("install", "repair"):
        subset = [r for r in records if r.work_type == wt]
        by_wt[wt] = sum(r.result == "complained" for r in subset) / len(subset) if subset else 0.0
    return {**m,
            "completed_no_complaint": round(sum(r.result == "completed" for r in records)),
            "promise_kept": round(m["promise_kept_rate"] * n),
            "complaint_rate_install": by_wt["install"],
            "complaint_rate_repair": by_wt["repair"]}


def compare(base_params: dict, instance, candidates: list[dict], worlds: dict[str, dict],
            seeds: list[int], promise_window_min: int) -> dict:
    """반환: {candidate_id: {"name", "plan", "outcome": {profile: 평균 지표}}}. 같은 seed를 모든 개선안에 쓴다."""
    out = {}
    for cand in candidates:
        params = apply_params(base_params, cand["proposal"]) if cand["proposal"] else base_params
        pack = get_pack(params)
        decisions = pack.solve(instance, params)
        per_profile = {}
        for profile, world in worlds.items():
            runs = [outcome_summary(simulate_outcomes(instance, decisions, params, world, s, pack.solve),
                                    promise_window_min) for s in seeds]
            per_profile[profile] = {k: mean(r[k] for r in runs) for k in runs[0]}
        out[cand["id"]] = {"name": cand["name"], "plan": plan_summary(pack, instance, decisions),
                           "outcome": per_profile}
    return out


def best_by(result: dict, profile: str, key: str) -> str:
    return max(result, key=lambda cid: result[cid]["outcome"][profile][key])


def recommendation(result: dict, profiles: list[str], key: str, min_agree: int) -> dict:
    """프로필별 최고안. 같은 안이 min_agree개 이상 프로필에서 최고일 때만 recommended (원칙 6)."""
    winners = {p: best_by(result, p, key) for p in profiles}
    counts = {c: list(winners.values()).count(c) for c in set(winners.values())}
    top, n = max(counts.items(), key=lambda kv: kv[1])
    return {"key": key, "winners": winners, "recommended": top if n >= min_agree else None, "agree": n}
