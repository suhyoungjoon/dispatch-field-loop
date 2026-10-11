"""흐름 상태 저장: runs/flows/<flow_id>/ 아래 state.json(상태), items.json(대화 항목), params.yaml(이 흐름의 params)."""

import json
from pathlib import Path


class FlowStore:
    def __init__(self, root):
        self.root = Path(root)

    def dir(self, flow_id: str) -> Path:
        return self.root / flow_id

    def new_id(self) -> str:
        existing = [int(p.name.split("-")[1]) for p in self.root.glob("flow-*") if p.name.split("-")[1].isdigit()] \
            if self.root.exists() else []
        return f"flow-{max(existing, default=0) + 1}"

    def save(self, state: dict) -> None:
        d = self.dir(state["id"])
        d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    def load(self, flow_id: str) -> dict:
        path = self.dir(flow_id) / "state.json"
        if not path.exists():
            raise KeyError(f"없는 흐름: {flow_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        if not self.root.exists():
            return []
        out = []
        for p in sorted(self.root.glob("flow-*/state.json"), key=lambda p: int(p.parent.name.split("-")[1])):
            s = json.loads(p.read_text(encoding="utf-8"))
            out.append({"id": s["id"], "name": s.get("name"), "created_at": s["created_at"],
                        "profile": s["config"]["profile"], "params_version": s["meta"]["params_version"]})
        return out
