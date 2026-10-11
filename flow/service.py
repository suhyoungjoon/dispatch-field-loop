"""통합 흐름 서비스 (N6): 계획 → 실적 → 분석 → 현장 대화 → 개선안 → 전후 시뮬레이션(계획 + 실적) → 승인.

모든 로직은 여기에 있고 화면(flow/app.py)은 이것만 부른다. 입출력은 JSON으로 바꿀 수 있는 dict다.
나중에 코어 웹과 연결할 때는 메서드를 REST로 감싼다 (docs/n6-ui-design.md 2장).
"""

import copy
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml
from core import apply_params, params_errors, simulate_params
from core.analysis.agent import analyze
from core.evaluation.fault_scorer import apply_labels, score
from core.improvement.constraints import constraint_violations
from core.improvement.history import change_record
from core.improvement.approval import write_params
from core.improvement.proposer import finding_slices, propose
from core.storage.store import to_jsonable
from domains.dispatch import get_pack

from dialogue.agent import DialogueContext
from dialogue.agent import dialogue_turn as run_dialogue_turn
from dialogue.store import ItemStore
from flow.store import FlowStore
from outcome.analysis_pack import OUTCOME_PERSPECTIVE, OutcomePack
from outcome.calibration import apply_calibration, approve as approve_calibration, check as check_calib
from outcome.calibration import reject as reject_calibration
from outcome.compare import compare, plan_summary, recommendation
from outcome.metrics import compute
from outcome.report import core_ref
from outcome.scoring import outcome_faults
from outcome.tools import outcome_tools
from world.carryover import simulate_outcomes
from world.config import load_world, world_errors

REPO = Path(__file__).resolve().parents[1]
PROFILES = ("lenient", "normal", "sensitive")
DEFAULT_CONFIG = {"name": "", "data_seed": 42, "faults": ["P1", "P2", "P3", "P4"], "profile": "normal", "outcome_seed": 1}
OPEN = ("proposed", "simulated")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FlowService:
    def __init__(self, root=REPO / "runs" / "flows", settings_dir=REPO / "settings",
                 profiles_dir=REPO / "world" / "profiles"):
        self.store = FlowStore(root)
        self.settings = yaml.safe_load((Path(settings_dir) / "flow.yaml").read_text(encoding="utf-8"))
        self.profiles_dir = Path(profiles_dir)
        self._cache: dict = {}

    # --- 내부: 상태에서 계산 재료를 다시 만든다 (결정적이라 저장하지 않는다) -------------------
    def _world(self, profile: str) -> dict:
        world = load_world(self.profiles_dir / f"world_{profile}.yaml")
        if errors := world_errors(world):
            raise ValueError(f"world_{profile}.yaml: {errors}")
        return world

    def _params_path(self, flow_id: str) -> Path:
        return self.store.dir(flow_id) / "params.yaml"

    def _items(self, flow_id: str) -> ItemStore:
        return ItemStore(self.store.dir(flow_id) / "items.json")

    def _ctx(self, state: dict) -> dict:
        key = (state["id"], state["meta"]["params_version"])
        if key not in self._cache:
            cfg = state["config"]
            params = yaml.safe_load(self._params_path(state["id"]).read_text(encoding="utf-8"))
            pack = get_pack(params)
            instance, _ = pack.generate(cfg["data_seed"], cfg["faults"])
            decisions = pack.solve(instance, params)
            records = simulate_outcomes(instance, decisions, params, self._world(cfg["profile"]),
                                        cfg["outcome_seed"], pack.solve)
            self._cache = {key: {"params": params, "pack": pack, "instance": instance,
                                 "decisions": decisions, "records": records}}
        return self._cache[key]

    @property
    def window(self) -> int:
        return self.settings["outcome"]["promise_window_min"]

    def _summaries(self, state: dict) -> None:
        c = self._ctx(state)
        state["plan"] = plan_summary(c["pack"], c["instance"], c["decisions"])
        state["outcome"] = {k: round(v, 4) for k, v in compute(c["records"], self.window).items()}

    def _confirmed_ids(self, state: dict) -> None:
        state["meta"]["confirmed_items"] = self._items(state["id"]).confirmed_ids()

    def _rescore(self, state: dict) -> None:
        report = state.get("report")
        if not report:
            return
        faults = outcome_faults(self._world(state["config"]["profile"]), confirm_cause=True)
        scored = score(report["findings"], faults, report["calls"])
        state["score"] = apply_labels(scored, self._items(state["id"]).labels())

    def _get(self, state: dict, kind: str, item_id: str) -> dict:
        found = next((p for p in state[kind] if p["id"] == item_id), None)
        if found is None:
            raise KeyError(f"없는 {kind}: {item_id}")
        return found

    # --- 흐름 -------------------------------------------------------------------------------
    def create_flow(self, config: dict | None = None) -> dict:
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        if cfg["profile"] not in PROFILES:
            raise ValueError(f"profile은 {PROFILES} 중 하나")
        flow_id = self.store.new_id()
        self.store.dir(flow_id).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(get_pack().params_path(), self._params_path(flow_id))   # 코어 기본 params 사본
        params = yaml.safe_load(self._params_path(flow_id).read_text(encoding="utf-8"))
        state = {"id": flow_id, "name": cfg.pop("name") or flow_id, "created_at": _now(), "config": cfg,
                 "meta": {"data_seed": cfg["data_seed"], "faults": cfg["faults"], "outcome_seed": cfg["outcome_seed"],
                          "profile": cfg["profile"], "params_version": params["version"], "core_ref": core_ref(),
                          "promise_window_min": self.window, "llm_models": {}, "confirmed_items": []},
                 "plan": None, "outcome": None, "report": None, "score": None, "transcript": [],
                 "proposals": [], "calibrations": [], "history": []}
        self._summaries(state)
        self.store.save(state)
        return state

    def get_flow(self, flow_id: str) -> dict:
        state = self.store.load(flow_id)
        state["items"] = self._items(flow_id).items
        return state

    def list_flows(self) -> list[dict]:
        return self.store.list()

    def outcome_table(self, flow_id: str, group_by: list[str]) -> dict:
        """화면용 실적 집계 (분석 agent가 쓰는 것과 같은 도구)."""
        c = self._ctx(self.store.load(flow_id))
        tools = {t["name"]: t for t in outcome_tools(c["records"], self.window)}
        return tools["outcome_by_group"]["handler"]({"group_by": group_by, "min_items": 1})

    # --- 분석 -------------------------------------------------------------------------------
    def run_analysis(self, flow_id: str, llm, llm_config: dict, max_calls: int = 30) -> dict:
        state = self.store.load(flow_id)
        c = self._ctx(state)
        report = analyze(OutcomePack(c["pack"], c["records"], self.window), c["instance"], c["decisions"], llm,
                         llm_config, max_calls=max_calls, perspective=OUTCOME_PERSPECTIVE)
        state["report"] = to_jsonable(report)
        state["meta"]["llm_models"]["analysis"] = llm.model
        self._rescore(state)
        self.store.save(state)
        return state["report"]

    # --- 현장 대화 ----------------------------------------------------------------------------
    def dialogue_turn(self, flow_id: str, speaker: str, text: str, llm, llm_config: dict) -> dict:
        if not str(speaker).strip() or not str(text).strip():
            raise ValueError("말한 사람과 내용이 필요하다")
        state = self.store.load(flow_id)
        c = self._ctx(state)
        state["transcript"].append({"role": "field", "speaker": speaker, "text": text, "ts": _now()})
        ctx = DialogueContext(pack_factory=get_pack, instance=c["instance"], params=c["params"],
                              decisions=c["decisions"], records=c["records"],
                              report=state.get("report") or {"findings": []}, promise_window_min=self.window)
        turn = run_dialogue_turn(ctx, state["transcript"], llm, llm_config, store=self._items(flow_id))
        state["transcript"].append({"role": "agent", "speaker": "AI", "text": turn["reply"], "ts": _now(), "model": llm.model,
                                    "item_ids": [i["id"] for i in turn["items"]],
                                    "reply_problems": turn["reply_problems"], "dropped_items": turn["dropped_items"]})
        state["meta"]["llm_models"]["dialogue"] = llm.model
        self.store.save(state)
        return to_jsonable({k: turn[k] for k in ("reply", "reply_problems", "items", "dropped_items", "stop", "usage")})

    def decide_item(self, flow_id: str, item_id: str, action: str, by: str, note: str | None = None) -> dict:
        items = self._items(flow_id)
        if action == "confirm":
            item = items.confirm(item_id, by, note)
        elif action == "reject":
            item = items.reject(item_id, by, note)
        else:
            raise ValueError("action은 confirm | reject")
        state = self.store.load(flow_id)
        self._confirmed_ids(state)
        self._rescore(state)
        self.store.save(state)
        return item

    # --- 개선안 ------------------------------------------------------------------------------
    def generate_proposals(self, flow_id: str, llm, llm_config: dict, max_calls: int = 20) -> list[dict]:
        state = self.store.load(flow_id)
        if not state.get("report"):
            raise ValueError("분석 리포트가 먼저 필요하다")
        c = self._ctx(state)
        spec_text = Path(c["pack"].spec_path()).read_text(encoding="utf-8")
        constraints = self._items(flow_id).constraints()
        out = propose(get_pack, c["instance"], c["params"], spec_text, c["pack"].dimensions(), state["report"],
                      llm, llm_config, max_calls=max_calls, constraints=constraints)
        added = [self._add_proposal(state, p["proposal"], p["errors"], source=f"ai ({llm.model})") for p in out["proposals"]]
        state["meta"]["llm_models"]["proposals"] = llm.model
        self.store.save(state)
        return added

    def add_manual_proposal(self, flow_id: str, proposal: dict, author: str) -> dict:
        if not str(author).strip():
            raise ValueError("작성자가 필요하다")
        state = self.store.load(flow_id)
        c = self._ctx(state)
        proposal = {"kind": "params", **proposal}
        errors = params_errors(c["params"], proposal, c["pack"].dimensions()) if proposal["kind"] == "params" \
            else ["사람 개선안은 params만 지원한다"]
        added = self._add_proposal(state, proposal, errors, source=f"사람: {author}")
        self.store.save(state)
        return added

    def _add_proposal(self, state: dict, proposal: dict, errors: list[str], source: str) -> dict:
        entry = {"id": f"P{len(state['proposals']) + 1}", "source": source, "body": to_jsonable(proposal),
                 "errors": errors, "status": "invalid" if errors else "proposed", "params_version": state["meta"]["params_version"],
                 "constraints": self._items(state["id"]).constraints(), "simulation": None, "decision": None,
                 "created_at": _now()}
        state["proposals"].append(entry)
        return entry

    def simulate_proposal(self, flow_id: str, proposal_id: str) -> dict:
        """계획 전후(코어 simulate_params) + 제약 위반(코어) + 실적 전후(현실 모델 프로필 3개) + 추천 표시(원칙 6)."""
        state = self.store.load(flow_id)
        p = self._get(state, "proposals", proposal_id)
        if p["status"] not in OPEN:
            raise ValueError(f"{proposal_id}는 {p['status']} 상태라 시뮬레이션할 수 없다")
        if p["params_version"] != state["meta"]["params_version"]:
            raise ValueError("params가 바뀐 뒤의 개선안이다 (stale)")
        c = self._ctx(state)
        body = p["body"]
        candidate = apply_params(c["params"], body)
        plan = simulate_params(get_pack, c["instance"], c["params"], candidate, finding_slices(state.get("report") or {}))
        violations = constraint_violations(p["constraints"], candidate, plan) if p["constraints"] else []
        worlds = {prof: self._world(prof) for prof in PROFILES}
        outcome = compare(c["params"], c["instance"],
                          [{"id": "current", "name": "현재", "proposal": {}}, {"id": p["id"], "name": p["id"], "proposal": body}],
                          worlds, self.settings["outcome"]["seeds"], self.window)
        tie = self.settings["outcome"]["tie_margin_pp"] / 100
        recs = [recommendation(outcome, list(PROFILES), key, self.settings["outcome"]["min_profiles_agree"], tie)
                for key in ("promise_kept_rate", "completed_no_complaint_rate")]
        p["simulation"] = to_jsonable({"plan": plan, "constraint_violations": violations,
                                       "outcome": {cid: r["outcome"] for cid, r in outcome.items()},
                                       "recommendations": recs, "simulated_at": _now()})
        p["status"] = "simulated"
        self.store.save(state)
        return p

    def decide_proposal(self, flow_id: str, proposal_id: str, action: str, approver: str, note: str = "") -> dict:
        if not str(approver).strip():
            raise ValueError("승인·반려한 사람(approver)이 필요하다")
        state = self.store.load(flow_id)
        p = self._get(state, "proposals", proposal_id)
        if p["status"] not in OPEN:
            raise ValueError(f"{proposal_id}는 {p['status']} 상태다")
        if action == "reject":
            p.update(status="rejected", decision={"approver": approver, "note": note, "at": _now()})
        elif action == "approve":
            if p["status"] != "simulated":
                raise ValueError("시뮬레이션을 마친 개선안만 승인할 수 있다")
            c = self._ctx(state)
            record = change_record(c["params"], p["body"])
            before, after = write_params(self._params_path(flow_id), p["body"])
            p.update(status="approved", decision={"approver": approver, "note": note, "at": _now(),
                                                  "params_version_before": before, "params_version_after": after, **record})
            for other in state["proposals"]:
                if other["id"] != p["id"] and other["status"] in OPEN:
                    other["status"] = "stale"
            self._after_params_change(state, after)
            state["history"].append({"type": "proposal", "id": p["id"], "approver": approver, "note": note,
                                     "version_before": before, "version_after": after, "changes": record, "at": _now()})
        else:
            raise ValueError("action은 approve | reject")
        self.store.save(state)
        return p

    def _after_params_change(self, state: dict, version: int) -> None:
        state["meta"]["params_version"] = version
        self._cache = {}
        self._summaries(state)

    # --- 추정값 보정 (N3 경로) ----------------------------------------------------------------
    def check_calibration(self, flow_id: str, proposal: dict) -> dict:
        state = self.store.load(flow_id)
        c = self._ctx(state)
        item = check_calib(c["params"], proposal, c["records"], self.settings["calibration"])
        entry = {"id": f"C{len(state['calibrations']) + 1}", **to_jsonable(item),
                 "params_version": state["meta"]["params_version"], "created_at": _now()}
        state["calibrations"].append(entry)
        self.store.save(state)
        return entry

    def decide_calibration(self, flow_id: str, calibration_id: str, action: str, approver: str, note: str = "") -> dict:
        state = self.store.load(flow_id)
        entry = self._get(state, "calibrations", calibration_id)
        if entry["params_version"] != state["meta"]["params_version"]:
            raise ValueError("params가 바뀐 뒤의 보정 제안이다. 다시 검사한다")
        if action == "reject":
            entry.update(reject_calibration(entry, approver, note))
        elif action == "approve":
            approved = approve_calibration(entry, approver, note)
            c = self._ctx(state)
            new_params = apply_calibration(c["params"], approved)
            path = approved["proposal"]["path"]
            section, key = path.split(".", 1)
            change = {"params_changes": [{"path": path, "value": copy.deepcopy(new_params[section][key])}]}
            record = change_record(c["params"], change)
            before, after = write_params(self._params_path(flow_id), change)
            entry.update({**approved, "decision": {"approver": approver, "note": note, "at": _now(),
                                                   "params_version_before": before, "params_version_after": after}})
            self._after_params_change(state, after)
            state["history"].append({"type": "calibration", "id": entry["id"], "approver": approver, "note": note,
                                     "version_before": before, "version_after": after, "changes": record, "at": _now()})
        else:
            raise ValueError("action은 approve | reject")
        self.store.save(state)
        return entry
