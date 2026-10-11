"""LLM 만들기. 실제 API 호출은 사람이 화면에서 요청·확인했을 때만 만든다 (CLAUDE.md). 테스트는 가짜 LLM을 직접 넣는다."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def make_llm(role: str, llm_settings=REPO / "settings" / "llm.yaml", cache_path=REPO / "runs" / "llm_cache.sqlite",
             env_path=REPO / ".env"):
    """(AnthropicClient, config). role: analysis | dialogue | proposals (settings/llm.yaml의 roles)."""
    from core.llm.client import AnthropicClient, ResponseCache, load_config
    config = load_config(Path(llm_settings), role=role)
    return AnthropicClient(config, cache=ResponseCache(Path(cache_path)), env_path=Path(env_path)), config
