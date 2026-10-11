"""실적 정답(P5·P6) → 코어 fault_scorer의 faults 형식. 채점은 코어 score()·apply_labels()를 그대로 쓴다."""


def outcome_faults(world: dict, confirm_cause: bool = False) -> dict:
    """현실 모델 설정의 truth에서 채점에 필요한 {name, answer}만 꺼낸다 (detail은 문서용).
    confirm_cause: 켜면 자동으로 맞아도 사람의 원인 확인(labels의 cause_ok) 전까지 대기(pending)다."""
    out = {}
    for fid, t in world["truth"].items():
        answer = dict(t["answer"])
        if confirm_cause:
            answer["confirm_cause"] = True
        out[fid] = {"name": t["name"], "answer": answer}
    return out
