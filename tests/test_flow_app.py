"""[N6] Streamlit 화면 연기 테스트: 실제 API 없이 흐름을 만들고 탭이 오류 없이 그려지는지."""

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from tests.conftest import REPO  # noqa: E402

APP = str(REPO / "flow" / "app.py")


def test_app_creates_flow_and_renders_tabs(tmp_path, monkeypatch):
    monkeypatch.setenv("FIELD_FLOW_DIR", str(tmp_path))
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception
    assert any("새 흐름" in i.value for i in at.info)

    at.sidebar.text_input[0].set_value("화면 테스트")
    at.sidebar.button[0].click()                 # 만들기 (form submit)
    at.run()
    assert not at.exception
    assert at.title[0].value == "화면 테스트"
    assert [t.label for t in at.tabs][:3] == ["① 계획·실적", "② 분석", "③ 현장 대화"]
    assert any(m.label == "배정" and m.value == "1,040" for m in at.metric)
    # API를 켜지 않았으니 분석 버튼은 꺼져 있다
    assert next(b for b in at.button if b.label == "분석 실행").disabled
