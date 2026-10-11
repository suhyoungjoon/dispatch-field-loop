"""N2 비교표를 만든다.

    python -m outcome.report --out docs/n2-outcome-compare.md --json runs/n2_compare.json
"""

import argparse
import json
import subprocess
from datetime import date
from importlib.metadata import distribution
from pathlib import Path

import yaml
from core import load_params
from domains.dispatch import get_pack

from outcome.compare import compare, recommendation
from world.config import load_world, world_errors

REPO = Path(__file__).resolve().parents[1]
PROFILES = ("lenient", "normal", "sensitive")
PROFILE_KO = {"lenient": "관대", "normal": "보통", "sensitive": "민감"}


def core_ref() -> str:
    direct = json.loads(distribution("optimization-agent-harness").read_text("direct_url.json") or "{}")
    return direct.get("vcs_info", {}).get("commit_id", "unknown")


def repo_ref() -> str:
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def render(result: dict, meta: dict, recs: list[dict]) -> str:
    lines = ["# N2 실적 비교: 기존 개선안의 고객 결과", "",
             f"- 생성: {meta['date']}, 코어 `{meta['core_ref'][:7]}`, 이 레포 `{meta['repo_ref']}`",
             f"- 데이터 seed {meta['data']['seed']}, 결함 {', '.join(meta['data']['faults'])}, params v{meta['params_version']}",
             f"- 실적 seed {meta['seeds']} 평균 (모든 개선안에 같은 seed = 공통 난수), 세상 프로필 {', '.join(PROFILE_KO[p] for p in PROFILES)}",
             f"- 약속 준수 = 원래 희망 날짜에, 희망 시각 ±{meta['promise_window_min']}분 안에 완료 (불만이 있어도 완료로 셈)",
             f"- 실행 메타데이터 전체: `{meta['json']}`", "",
             "## 계획 지표 (규칙 엔진, 하루 한 번 배정)", "",
             "| 개선안 | 배정 | 정시 | 위반 | 평균 이동 |", "|---|---|---|---|---|"]
    for r in result.values():
        p = r["plan"]
        lines.append(f"| {r['name']} | {p['assigned']:,} | {p['on_time']:,} | {p['violations']} | {p['avg_travel_min']:.1f}분 |")
    for prof in PROFILES:
        lines += ["", f"## 실적 지표: {PROFILE_KO[prof]} 세상", "",
                  "| 개선안 | 약속 준수 | 불만 없이 완료 | 완료율 | 불만율 (개통 / 장애) | 취소율 | 미처리 | 평균 이월 |",
                  "|---|---|---|---|---|---|---|---|"]
        for r in result.values():
            o = r["outcome"][prof]
            lines.append(f"| {r['name']} | {o['promise_kept']:,.0f} ({pct(o['promise_kept_rate'])}) "
                         f"| {o['completed_no_complaint']:,.0f} | {pct(o['completion_rate'])} "
                         f"| {pct(o['complaint_rate'])} ({pct(o['complaint_rate_install'])} / {pct(o['complaint_rate_repair'])}) "
                         f"| {pct(o['cancel_rate'])} | {pct(o['unserved_rate'])} | {o['avg_carry_days']:.2f}일 |")
    lines += ["", "## 프로필별 최고안 (표시 규칙, 결정은 사람이 한다)", "",
              f"1·2위 차이가 {meta['tie_margin_pp']}%p 미만인 프로필은 동률로 보고, 동률이 아닌 같은 최고안이 "
              f"{meta['min_profiles_agree']}개 이상 프로필에서 나올 때만 추천으로 표시한다.", "",
              "| 기준 | " + " | ".join(PROFILE_KO[p] for p in PROFILES) + " | 추천 |",
              "|---|" + "---|" * len(PROFILES) + "---|"]
    for rec in recs:
        winners = " | ".join(result[rec["winners"][p]]["name"] if rec["winners"][p] else "동률"
                             for p in PROFILES)
        verdict = (f"**{result[rec['recommended']]['name']}** ({rec['agree']}/{len(PROFILES)} 프로필 일치)"
                   if rec["recommended"] else f"보류 (동률이 아닌 일치 {rec['agree']}개 < {meta['min_profiles_agree']})")
        lines.append(f"| {rec['label']} | {winners} | {verdict} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default=str(REPO / "settings" / "n2_candidates.yaml"))
    ap.add_argument("--flow", default=str(REPO / "settings" / "flow.yaml"))
    ap.add_argument("--profiles-dir", default=str(REPO / "world" / "profiles"))
    ap.add_argument("--out", default=str(REPO / "docs" / "n2-outcome-compare.md"))
    ap.add_argument("--json", default=str(REPO / "runs" / "n2_compare.json"))
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(open(args.candidates, encoding="utf-8"))
    flow = yaml.safe_load(open(args.flow, encoding="utf-8"))["outcome"]
    worlds = {p: load_world(Path(args.profiles_dir) / f"world_{p}.yaml") for p in PROFILES}
    for p, w in worlds.items():
        if errors := world_errors(w):
            raise SystemExit(f"world_{p}.yaml: {errors}")

    pack = get_pack()
    base = load_params(pack)
    instance, _ = pack.generate(cfg["data"]["seed"], cfg["data"]["faults"])
    result = compare(base, instance, cfg["candidates"], worlds, flow["seeds"], flow["promise_window_min"])
    tie = flow["tie_margin_pp"] / 100
    recs = [{**recommendation(result, list(PROFILES), key, flow["min_profiles_agree"], tie), "label": label}
            for key, label in (("promise_kept_rate", "약속 준수"), ("completed_no_complaint_rate", "불만 없이 완료"))]

    meta = {"date": date.today().isoformat(), "core_ref": core_ref(), "repo_ref": repo_ref(),
            "data": cfg["data"], "params_version": base["version"], "seeds": flow["seeds"],
            "profiles": list(PROFILES), "promise_window_min": flow["promise_window_min"],
            "min_profiles_agree": flow["min_profiles_agree"], "tie_margin_pp": flow["tie_margin_pp"], "llm_model": None, "confirmed_items": [],
            "json": Path(args.json).relative_to(REPO).as_posix() if Path(args.json).is_relative_to(REPO) else args.json}
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps({"meta": meta, "candidates": cfg["candidates"], "result": result,
                                           "recommendations": recs}, ensure_ascii=False, indent=2))
    Path(args.out).write_text(render(result, meta, recs), encoding="utf-8")
    print(Path(args.out).read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
