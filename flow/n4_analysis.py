"""[N4] 실적 → 분석 agent → 채점.

가짜 LLM:  테스트에서 run_analysis(..., llm=FakeLLM(...))
실제 API:  사람이 요청할 때만.  python -m flow.n4_analysis --real [--profile normal] [--out runs/n4_analysis.json]
"""

import argparse
import json
import time
from importlib.metadata import distribution
from pathlib import Path

import yaml
from core import load_params
from core.analysis.agent import analyze
from core.evaluation.fault_scorer import score
from core.storage.store import to_jsonable
from domains.dispatch import get_pack

from outcome.analysis_pack import OUTCOME_PERSPECTIVE, OutcomePack
from outcome.scoring import outcome_faults
from world.carryover import simulate_outcomes
from world.config import load_world, world_errors

REPO = Path(__file__).resolve().parents[1]


def core_ref() -> str:
    direct = json.loads(distribution("optimization-agent-harness").read_text("direct_url.json") or "{}")
    return direct.get("vcs_info", {}).get("commit_id", "unknown")


def run_analysis(*, data_seed: int, faults: list[str], world_path, outcome_seed: int, flow_path,
                 llm, llm_config: dict, salt: str = "", max_calls: int = 30) -> dict:
    world = load_world(world_path)
    if errors := world_errors(world):
        raise ValueError(f"{world_path}: {errors}")
    window = yaml.safe_load(open(flow_path, encoding="utf-8"))["outcome"]["promise_window_min"]

    pack = get_pack()
    params = load_params(pack)
    instance, _ = pack.generate(data_seed, faults)
    decisions = pack.solve(instance, params)
    records = simulate_outcomes(instance, decisions, params, world, outcome_seed, pack.solve)

    started = time.time()
    report = analyze(OutcomePack(pack, records, window), instance, decisions, llm, llm_config,
                     salt=salt, max_calls=max_calls, perspective=OUTCOME_PERSPECTIVE)
    scored = score(report["findings"], outcome_faults(world), report["calls"])
    meta = {"data_seed": data_seed, "faults": faults, "outcome_seed": outcome_seed, "profile": world["profile"],
            "params_version": params["version"], "promise_window_min": window, "llm_model": llm.model,
            "core_ref": core_ref(), "perspective": OUTCOME_PERSPECTIVE["id"], "confirmed_items": [],
            "seconds": round(time.time() - started, 1)}
    return {"meta": meta, "report": report, "score": scored}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true", help="실제 Claude API를 호출한다 (비용 발생)")
    ap.add_argument("--profile", default="normal", choices=["lenient", "normal", "sensitive"])
    ap.add_argument("--outcome-seed", type=int, default=1)
    ap.add_argument("--out", default=str(REPO / "runs" / "n4_analysis.json"))
    args = ap.parse_args(argv)
    if not args.real:
        raise SystemExit("실제 API 실행은 --real을 붙여야 한다 (CLAUDE.md: 사람이 요청할 때만)")

    from core.llm.client import AnthropicClient, ResponseCache, load_config
    config = load_config(REPO / "settings" / "llm.yaml", role="analysis")
    llm = AnthropicClient(config, cache=ResponseCache(REPO / "runs" / "llm_cache.sqlite"), env_path=REPO / ".env")
    out = run_analysis(data_seed=42, faults=["P1", "P2", "P3", "P4"],
                       world_path=REPO / "world" / "profiles" / f"world_{args.profile}.yaml",
                       outcome_seed=args.outcome_seed, flow_path=REPO / "settings" / "flow.yaml",
                       llm=llm, llm_config=config)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(to_jsonable(out), ensure_ascii=False, indent=2), encoding="utf-8")
    s = out["score"]
    print(f"탐지 {s['detected']}/{s['total']}, 발견 {len(out['report']['findings'])}개, "
          f"제외 {len(out['report']['dropped'])}개, 사용량 {out['report']['usage']}")


if __name__ == "__main__":
    main()
