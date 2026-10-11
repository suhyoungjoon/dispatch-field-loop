"""[N5] 구조화 항목: 형식 검사, 제약 변환, 상태 전이, 저장소."""

import pytest

from dialogue.items import item_errors, new_item
from dialogue.store import ItemStore

METRICS = ["assignment_rate", "on_time_rate", "avg_travel_min"]
FINDINGS = {"F1", "F2"}
FIELD = "강남 현장 담당자"


def constraint_item(**over):
    c = {"type": "param", "path": "matching.area_extension_km[2]", "max": 4}
    c.update(over)
    return new_item("constraint", speaker=FIELD, utterance="관할 밖 4km 넘으면 출동 못 해요",
                    summary="3단계 관할 확장은 4km까지", constraint=c)


def test_constraint_item_gets_source_from_speaker(scenario):
    _, params, _ = scenario
    item = constraint_item()
    assert item["status"] == "proposed" and item["constraint"]["source"] == FIELD
    assert item_errors(item, params, METRICS, FINDINGS) == []


def test_bad_constraint_rejected_by_core_check(scenario):
    _, params, _ = scenario
    assert item_errors(constraint_item(path="matching.nope[0]"), params, METRICS, FINDINGS)
    bad_metric = new_item("constraint", speaker=FIELD, utterance="u", summary="s",
                          constraint={"type": "metric", "metric": "happiness", "max_drop": 0.03})
    assert item_errors(bad_metric, params, METRICS, FINDINGS)


def test_label_item_must_point_to_report_finding(scenario):
    _, params, _ = scenario
    ok = new_item("label", speaker=FIELD, utterance="u", summary="s", label={"finding_id": "F1", "label": "cause_ok"})
    assert item_errors(ok, params, METRICS, FINDINGS) == []
    assert item_errors({**ok, "label": {"finding_id": "F9", "label": "cause_ok"}}, params, METRICS, FINDINGS)
    assert item_errors({**ok, "label": {"finding_id": "F1", "label": "maybe"}}, params, METRICS, FINDINGS)


def test_fact_and_check_items(scenario):
    _, params, _ = scenario
    fact = new_item("fact", speaker=FIELD, utterance="고객한테는 30분 안에 간다고 약속해요",
                    summary="약속 기준은 희망 시각 ±30분", fact={"statement": "약속 기준 ±30분",
                                                          "topic": "promise_window_min", "value": 30})
    assert item_errors(fact, params, METRICS, FINDINGS) == []
    check = new_item("check", speaker=FIELD, utterance="u", summary="s",
                     check={"field_claim": "장애 고객은 불만이 적다", "data_summary": "장애 불만율이 더 높음"})
    assert any("cited_calls" in e for e in item_errors(check, params, METRICS, FINDINGS))
    assert item_errors({**check, "cited_calls": ["t1"]}, params, METRICS, FINDINGS) == []
    with pytest.raises(ValueError):
        new_item("wish", speaker=FIELD, utterance="u", summary="s")


def test_store_status_flow(tmp_path, scenario):
    _, params, _ = scenario
    store = ItemStore(tmp_path / "items.json")
    c = store.add(constraint_item())
    m = store.add(new_item("constraint", speaker="운영팀", utterance="정시 손실은 3%p까지",
                           summary="정시 배정 비율 감소 3%p까지",
                           constraint={"type": "metric", "metric": "on_time_rate", "max_drop": 0.03}))
    lab = store.add(new_item("label", speaker=FIELD, utterance="u", summary="s",
                             label={"finding_id": "F1", "label": "cause_ok"}))
    assert [c["id"], m["id"], lab["id"]] == ["I1", "I2", "I3"]
    assert store.constraints() == [] and store.labels() == {}          # 확인 전에는 아무것도 넘기지 않는다

    with pytest.raises(ValueError):
        store.confirm(c["id"], by="")                                 # 사람 이름 필수
    store.confirm(c["id"], by="김 팀장")
    store.reject(m["id"], by="김 팀장", note="운영팀과 다시 확인")
    store.confirm(lab["id"], by="김 팀장")
    with pytest.raises(ValueError):
        store.confirm(m["id"], by="김 팀장")                          # 반려된 항목은 확인 불가

    again = ItemStore(tmp_path / "items.json")                        # 파일에서 다시 읽기
    assert again.constraints() == [c["constraint"]]
    assert again.labels() == {"F1": "cause_ok"}
    assert again.confirmed_ids() == ["I1", "I3"]
    assert again.get("I2")["status"] == "rejected" and again.get("I1")["decided_by"] == "김 팀장"
