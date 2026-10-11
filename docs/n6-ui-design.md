# N6 통합 흐름과 화면 설계

## 1. 구조

```
flow/
  service.py   흐름 서비스. 모든 로직. 입출력은 JSON으로 바꿀 수 있는 dict. Streamlit을 import하지 않는다
  store.py     흐름 상태 저장 (runs/flows/<flow_id>/ 아래 state.json, items.json, params.yaml)
  llm.py       LLM 만들기 (실제 API는 사람이 화면에서 확인했을 때만). 테스트는 가짜 LLM을 넣는다
  app.py       Streamlit 화면. service만 부른다
```

화면 → 서비스 → (코어 함수 + 이 레포의 world / outcome / dialogue) 순으로만 호출한다. 화면에는 로직을 두지 않는다.
그래서 나중에 화면을 코어 웹(React)으로 옮길 때 서비스는 그대로 두고 화면만 바꾸면 된다.

## 2. 흐름과 상태

| 단계 | 서비스 메서드 | 나중의 REST (예정) | 상태 |
|---|---|---|---|
| 흐름 만들기 (계획 + 실적) | `create_flow(config)` | `POST /field/flows` | 계획 지표, 실적 지표 |
| 조회 | `get_flow(id)`, `list_flows()` | `GET /field/flows/{id}`, `GET /field/flows` | |
| 분석 | `run_analysis(id, llm)` | `POST /field/flows/{id}/analysis` | 코어 분석 리포트 형식 |
| 현장 대화 | `dialogue_turn(id, speaker, text, llm)` | `POST /field/flows/{id}/dialogue` | 대화 기록, 항목(proposed) |
| 항목 확인·반려 | `decide_item(id, item_id, action, by, note)` | `POST /field/flows/{id}/items/{item_id}/{confirm\|reject}` | confirmed / rejected |
| 개선안 (AI) | `generate_proposals(id, llm)` | `POST /field/flows/{id}/proposals` | 확인된 제약을 코어 `propose(constraints=)`에 넘김 |
| 개선안 (사람) | `add_manual_proposal(id, proposal, author)` | `POST /field/flows/{id}/proposals/manual` | 코어 `params_errors`로 검사 |
| 전후 시뮬레이션 | `simulate_proposal(id, pid)` | `POST /field/flows/{id}/proposals/{pid}/simulate` | 계획 전후(코어) + 실적 전후(프로필 3개) + 제약 위반 + 추천 표시 |
| 승인·반려 | `decide_proposal(id, pid, action, approver, note)` | `POST /field/flows/{id}/proposals/{pid}/{approve\|reject}` | 승인 시 흐름의 params.yaml에 코어 `write_params` (version +1), 다른 미결 안은 stale |
| 추정값 보정 | `check_calibration(id, proposal)`, `decide_calibration(id, cid, action, approver, note)` | `POST /field/flows/{id}/calibrations`, `.../{cid}/{approve\|reject}` | N3 보정 경로 |

개선안 상태는 코어와 같다: `proposed → simulated → approved / rejected`, 또는 `stale`.

## 3. 코어 화면과 연결할 때

- **데이터 형식이 코어와 같다.** 분석 리포트(`findings`, `calls`), 개선안(`kind`, `params_changes`, `override_rules`),
  제약(`constraint_errors` 형식), 발견 판정(`labels`: cause_ok / cause_wrong / false_positive), 변경 기록(`change_record`).
  코어 웹의 리포트·개선안 컴포넌트를 그대로 쓸 수 있다.
- **연결 방법 (추천)**: 이 레포에 FastAPI 앱을 하나 두고 2장 표대로 서비스 메서드를 감싼다(`/field` 접두사).
  코어 웹에 "현장·실적" 탭을 추가해 이 API를 부른다. 코어 `api/`는 재사용 대상이 아니므로(코어 handoff 9장) 코어 API에 섞지 않는다.
- **params 파일**: 흐름마다 `runs/flows/<id>/params.yaml`(코어 기본 params 사본)에 쓴다. 코어 레포의 params.yaml은 바꾸지 않는다.
- **현실 모델 설정은 화면에도 내보내지 않는다.** 프로필 이름만 보인다. 정답표 채점은 "실험용" 접힌 칸에만 보인다.

## 4. 재현성 (원칙 5)

흐름 상태의 `meta`에 남긴다: 데이터 seed·결함, 실적 seed, 현실 모델 프로필, params 버전, 코어 커밋,
단계별 LLM 모델명, 확인된 항목 id.
