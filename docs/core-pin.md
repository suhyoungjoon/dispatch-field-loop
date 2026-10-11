# 코어 고정 이력

코어(`optimization-agent-harness`)는 태그 없이 **커밋 SHA로 고정**한다. 올릴 때는 SHA만 바꾸는 별도 커밋으로 하고, 아래 표에 한 줄 추가한 뒤 `tests/test_baseline.py`가 통과하는지 확인한다.

| 날짜 | SHA | 포함 마일스톤 | 이유 |
|---|---|---|---|
| 2026-10-11 | `de3e755ee50235cb36242b0af8f91e284e9072a2` | M12(a~d), M13 (main, PR #31 병합) | N1 착수. M13까지 main에 병합되어 있어 N3 전에 다시 올릴 필요 없음 |

## 이 SHA에서 확인한 것

- 기준값: seed 42, P1~P4, 기본 params(v1) → 배정 1,040 / 정시(`on_time_rate` × 1,500) 741 / 위반 0.
- API 키: 코어 `AnthropicClient`는 `OAH_ANTHROPIC_API_KEY`를 먼저, 없으면 `ANTHROPIC_API_KEY`를 읽는다. 키 파일 경로는 `env_path`로 넘긴다.
- `analyze(pack, instance, decisions, llm, llm_config, salt, max_calls, memory_text, perspective)`에는 **외부 도구 인자가 없다.** 도구는 `Aggregator(...).tools() + pack.analysis_tools(instance, decisions)`로 정해진다. N4에서 팩 래퍼(`outcome/analysis_pack.py`)로 `analysis_tools`에 실적 도구를 더하기로 했다 (plan 6장 결정 #6).
- `tests/fake_llm.py`는 이 SHA의 `tests/fake_llm.py`를 그대로 복사했다.
