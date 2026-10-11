"""항목 저장소: JSON 파일 하나 (경로는 인자로). 확인·반려는 사람 이름이 있어야 한다."""

import json
from pathlib import Path

from dialogue.items import now


class ItemStore:
    def __init__(self, path):
        self.path = Path(path)
        self.items: list[dict] = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.items, ensure_ascii=False, indent=1), encoding="utf-8")

    def add(self, item: dict) -> dict:
        item = {**item, "id": f"I{len(self.items) + 1}", "status": "proposed"}
        self.items.append(item)
        self._save()
        return item

    def get(self, item_id: str) -> dict:
        found = next((i for i in self.items if i["id"] == item_id), None)
        if found is None:
            raise KeyError(f"없는 항목: {item_id}")
        return found

    def _decide(self, item_id: str, status: str, by: str, note: str | None) -> dict:
        if not str(by or "").strip():
            raise ValueError("확인·반려한 사람(by)이 필요하다")
        item = self.get(item_id)
        if item["status"] != "proposed":
            raise ValueError(f"{item_id}는 이미 {item['status']} 상태다")
        item.update({"status": status, "decided_by": by, "decided_at": now(), "note": note})
        self._save()
        return item

    def confirm(self, item_id: str, by: str, note: str | None = None) -> dict:
        return self._decide(item_id, "confirmed", by, note)

    def reject(self, item_id: str, by: str, note: str | None = None) -> dict:
        return self._decide(item_id, "rejected", by, note)

    def find(self, status: str | None = None, kind: str | None = None) -> list[dict]:
        return [i for i in self.items if (status is None or i["status"] == status) and (kind is None or i["kind"] == kind)]

    def constraints(self) -> list[dict]:
        """확인된 제약만 (코어 제약 형식) → core propose(constraints=...)."""
        return [i["constraint"] for i in self.find("confirmed", "constraint")]

    def labels(self) -> dict[str, str]:
        """확인된 발견 판정 → core apply_labels(labels)."""
        return {i["label"]["finding_id"]: i["label"]["label"] for i in self.find("confirmed", "label")}

    def confirmed_ids(self) -> list[str]:
        """실행 메타데이터에 남길 확정 항목 id (원칙 5)."""
        return [i["id"] for i in self.find("confirmed")]
