"""실적 정답(P5·P6) → 코어 fault_scorer의 faults 형식. 채점은 코어 score()·apply_labels()를 그대로 쓴다."""


def outcome_faults(world: dict) -> dict:
    """현실 모델 설정의 truth에서 채점에 필요한 {name, answer}만 꺼낸다 (detail은 문서용)."""
    return {fid: {"name": t["name"], "answer": t["answer"]} for fid, t in world["truth"].items()}
