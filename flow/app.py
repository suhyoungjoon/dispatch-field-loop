"""현장·실적 개선 흐름 화면 (Streamlit). 로직은 flow/service.py에만 있고 이 파일은 그것을 부르고 보여 줄 뿐이다.

    streamlit run flow/app.py
    (흐름 저장 위치: 환경변수 FIELD_FLOW_DIR, 기본 runs/flows)
"""

import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:                     # streamlit run은 스크립트 폴더만 경로에 넣는다
    sys.path.insert(0, str(REPO))

from flow.demo_llm import DEMO_MODEL  # noqa: E402
from flow.service import PROFILES, FlowService  # noqa: E402

PROFILE_KO = {"lenient": "관대", "normal": "보통", "sensitive": "민감"}
STATUS_KO = {"proposed": "제안됨", "confirmed": "확인됨", "rejected": "반려됨", "simulated": "시뮬레이션 완료",
             "approved": "승인됨", "stale": "지난 안", "invalid": "검사 탈락", "checked": "검사 통과",
             "detected": "탐지", "pending": "원인 확인 대기", "missed": "놓침"}
KIND_KO = {"constraint": "제약", "fact": "사실", "check": "확인 필요", "label": "발견 판정"}
AI_MODES = {"off": "끔", "demo": "가상 LLM(데모)", "real": "실제 Claude API (비용 발생)"}
DEMO_BADGE = "데모 결과: 가상 LLM이 미리 정한 응답이다 (실제 AI 판단이 아님)"
ESTIMATE_PATHS = ["weights.difficulty", "weights.building", "duration.base_min", "travel.avg_speed_kmh"]

st.set_page_config(page_title="현장·실적 개선 흐름", layout="wide")


@st.cache_resource
def service(root: str) -> FlowService:
    """저장 위치별로 하나 (위치가 바뀌면 다른 서비스)."""
    return FlowService(root=Path(root))


svc = service(str(os.environ.get("FIELD_FLOW_DIR", REPO / "runs" / "flows")))


def pct(x) -> str:
    return "-" if x is None else f"{x * 100:.1f}%"


def call(fn, *args, success: str | None = None, **kwargs):
    """서비스 호출. 오류는 화면에 보여 주고 None."""
    try:
        out = fn(*args, **kwargs)
        if success:
            st.toast(success)
        return out
    except (ValueError, KeyError) as exc:
        st.error(str(exc))
        return None


def ai_on() -> bool:
    return st.session_state.get("ai_mode", "off") != "off"


def llm_for(role: str):
    """AI 사용 모드에 맞는 (llm, config). 끔이면 None."""
    mode = st.session_state.get("ai_mode", "off")
    if mode == "demo":
        from flow.demo_llm import make_demo_llm
        return make_demo_llm(role)
    if mode == "real":
        from flow.llm import make_llm
        return make_llm(role)
    st.warning("AI 사용이 꺼져 있습니다. 왼쪽에서 가상 LLM(데모) 또는 실제 Claude API를 골라야 이 단계를 실행할 수 있습니다.")
    return None


# --- 사이드바: 흐름 선택·생성, API 사용 ---------------------------------------------------------
with st.sidebar:
    st.header("흐름")
    flows = svc.list_flows()
    labels = {f["id"]: f"{f['id']} · {f['name']} (현실 모델 {PROFILE_KO[f['profile']]}, params v{f['params_version']})"
              for f in flows}
    ids = list(labels)
    default = ids.index(st.session_state["flow_id"]) if st.session_state.get("flow_id") in ids else len(ids) - 1
    if ids:
        st.session_state["flow_id"] = st.selectbox("흐름 선택", ids, index=max(default, 0), format_func=labels.get)

    with st.expander("새 흐름 만들기", expanded=not ids):
        with st.form("new_flow"):
            name = st.text_input("이름", "")
            data_seed = st.number_input("데이터 seed", value=42, step=1)
            faults = st.multiselect("심은 결함 (계획 쪽)", ["P1", "P2", "P3", "P4"], default=["P1", "P2", "P3", "P4"])
            profile = st.selectbox("현실 모델 프로필", PROFILES, index=1, format_func=PROFILE_KO.get)
            outcome_seed = st.number_input("실적 seed", value=1, step=1)
            if st.form_submit_button("만들기 (계획 + 실적 계산)"):
                with st.spinner("계획과 실적을 계산하는 중"):
                    created = call(svc.create_flow, {"name": name, "data_seed": int(data_seed), "faults": faults,
                                                     "profile": profile, "outcome_seed": int(outcome_seed)},
                                   success="흐름을 만들었습니다")
                if created:
                    st.session_state["flow_id"] = created["id"]
                    st.rerun()

    st.header("AI 사용")
    st.session_state["ai_mode"] = st.radio(
        "분석·현장 대화·AI 개선안 단계", list(AI_MODES), format_func=AI_MODES.get, key="ai_mode_choice",
        help="끔: 그 단계만 막힌다. 가상 LLM(데모): API 키 없이 미리 정한 응답으로 흐름을 돌려 본다. "
             "실제 Claude API: settings/llm.yaml의 모델을 부른다 (비용 발생).")
    st.session_state["person"] = st.text_input("내 이름 (확인·승인자)", st.session_state.get("person", ""))

flow_id = st.session_state.get("flow_id")
if not flow_id:
    st.title("현장·실적 개선 흐름")
    st.info("왼쪽에서 새 흐름을 만드세요. 흐름 = 계획 → 실적 → 분석 → 현장 대화 → 개선안 → 전후 시뮬레이션 → 승인")
    st.stop()

state = svc.get_flow(flow_id)
person = st.session_state.get("person", "")
st.title(f"{state['name']}")
st.caption(f"{state['id']} · 현실 모델 {PROFILE_KO[state['config']['profile']]} · params v{state['meta']['params_version']} "
           f"· 확인된 항목 {len(state['meta']['confirmed_items'])}개")
if st.session_state.get("ai_mode") == "demo":
    st.info("가상 LLM(데모) 모드: 분석·현장 대화·AI 개선안은 미리 정한 응답이다. 흐름을 돌려 보는 용도이며, "
            f"실행 메타데이터에 모델명 '{DEMO_MODEL}'로 남는다.")

tabs = st.tabs(["① 계획·실적", "② 분석", "③ 현장 대화", "④ 개선안·시뮬레이션", "⑤ 승인·이력", "⑥ 실행 정보"])

# --- ① 계획·실적 ---------------------------------------------------------------------------------
with tabs[0]:
    plan, out = state["plan"], state["outcome"]
    st.subheader("계획 (규칙 엔진)")
    c = st.columns(4)
    c[0].metric("배정", f"{plan['assigned']:,}")
    c[1].metric("정시 배정", f"{plan['on_time']:,}")
    c[2].metric("필수조건 위반", plan["violations"])
    c[3].metric("평균 이동", f"{plan['avg_travel_min']:.1f}분")
    st.subheader("실적 (가상)")
    c = st.columns(5)
    c[0].metric(f"약속 준수 (±{state['meta']['promise_window_min']}분)", pct(out["promise_kept_rate"]))
    c[1].metric("불만율", pct(out["complaint_rate"]))
    c[2].metric("취소율", pct(out["cancel_rate"]))
    c[3].metric("미처리", pct(out["unserved_rate"]))
    c[4].metric("도착 지연 평균 / 상위10%", f"{out['avg_arrival_delay_min']:.1f} / {out['p90_arrival_delay_min']:.0f}분")
    group_by = st.multiselect("실적을 묶어 보기", ["work_type", "branch", "hour", "difficulty", "building_type",
                                                   "media", "area_zone", "time_diff_band"], default=["work_type"])
    if group_by:
        table = call(svc.outcome_table, flow_id, group_by)
        if table:
            st.dataframe(pd.DataFrame(table["rows"]), width="stretch", hide_index=True)

# --- ② 분석 --------------------------------------------------------------------------------------
with tabs[1]:
    st.write("분석 agent가 계획 집계와 실적 집계 도구로 패턴을 찾는다. 수치 근거가 없는 발견은 코드가 뺀다.")
    if st.button("분석 실행", disabled=not ai_on()):
        made = llm_for("analysis")
        if made:
            with st.spinner("분석 중"):
                call(svc.run_analysis, flow_id, *made, success="분석을 마쳤습니다")
            st.rerun()
    report = state.get("report")
    if report:
        if state["meta"]["llm_models"].get("analysis") == DEMO_MODEL:
            st.warning(DEMO_BADGE)
        st.markdown(f"**요약**: {report.get('summary', '')}")
        st.dataframe(pd.DataFrame([{"id": f["id"], "제목": f["title"], "설명": f["description"],
                                    "구간": json.dumps(f.get("slice") or {}, ensure_ascii=False),
                                    "원인 가설": f.get("hypothesis", "")} for f in report["findings"]]),
                     width="stretch", hide_index=True)
        if report.get("dropped"):
            with st.expander(f"근거 부족으로 뺀 발견 {len(report['dropped'])}개"):
                st.json(report["dropped"])
        if state.get("score"):
            with st.expander("채점 (실험용: 심어 둔 정답과 대조, 원인은 현장 대화의 판정으로 확정)"):
                s = state["score"]
                st.write(f"탐지 {s['detected']} / {s['total']}, 원인 확인 대기 {s['pending']}")
                st.dataframe(pd.DataFrame([{"정답": fid, "이름": f["name"], "상태": STATUS_KO.get(f["status"], f["status"]),
                                            "맞힌 발견": ", ".join(f["matched_findings"])} for fid, f in s["faults"].items()]),
                             hide_index=True)
    else:
        st.info("아직 분석 리포트가 없습니다.")

# --- ③ 현장 대화 ---------------------------------------------------------------------------------
with tabs[2]:
    left, right = st.columns([3, 2])
    with left:
        st.write("현장 의견을 말하면 AI가 데이터와 대조해 '이렇게 이해했습니다'로 정리합니다. 정리된 항목은 제안일 뿐이고 확인해야 반영됩니다.")
        for t in state["transcript"]:
            with st.chat_message("user" if t["role"] == "field" else "assistant"):
                st.markdown(f"**{t['speaker']}**: {t['text']}")
                if t.get("model") == DEMO_MODEL:
                    st.caption(DEMO_BADGE)
                if t.get("reply_problems"):
                    st.warning("근거 확인 필요: " + "; ".join(t["reply_problems"]))
        speaker = st.text_input("말하는 사람", "현장 담당자", key="speaker")
        text = st.chat_input("현장 의견", disabled=not ai_on())
        if text:
            made = llm_for("dialogue")
            if made:
                with st.spinner("정리하는 중"):
                    call(svc.dialogue_turn, flow_id, speaker, text, *made)
                st.rerun()
    with right:
        st.subheader("정리된 항목")
        for item in state["items"]:
            body = item.get(item["kind"]) or {}
            with st.container(border=True):
                st.markdown(f"**{item['id']} · {KIND_KO[item['kind']]}** · {STATUS_KO[item['status']]} · {item['speaker']}")
                st.write(item["summary"])
                st.caption(f"발언: \"{item['utterance']}\"")
                st.code(json.dumps(body, ensure_ascii=False), language="json")
                if item["status"] == "proposed":
                    a, b = st.columns(2)
                    if a.button("확인", key=f"ok-{item['id']}", disabled=not person):
                        call(svc.decide_item, flow_id, item["id"], "confirm", by=person)
                        st.rerun()
                    if b.button("반려", key=f"no-{item['id']}", disabled=not person):
                        call(svc.decide_item, flow_id, item["id"], "reject", by=person)
                        st.rerun()
                elif item.get("decided_by"):
                    st.caption(f"{STATUS_KO[item['status']]}: {item['decided_by']} ({item['decided_at']})")
        if not person:
            st.caption("확인·반려하려면 왼쪽에 이름을 적으세요.")

# --- ④ 개선안·시뮬레이션 -------------------------------------------------------------------------
with tabs[3]:
    a, b = st.columns(2)
    with a:
        st.write("AI 개선안: 분석 리포트와 **확인된 제약**을 넣어 코어 개선 agent를 부른다.")
        if st.button("AI 개선안 받기", disabled=not ai_on() or not state.get("report")):
            made = llm_for("proposals")
            if made:
                with st.spinner("개선안을 만드는 중"):
                    call(svc.generate_proposals, flow_id, *made, success="개선안을 받았습니다")
                st.rerun()
    with b:
        with st.form("manual"):
            st.write("사람 개선안 (규칙 파라미터)")
            title = st.text_input("제목", "관할 4km")
            changes = st.text_area("params_changes (JSON)", '[{"path": "matching.area_extension_km[2]", "value": 4}]')
            rules = st.text_area("override_rules (JSON, 선택)", "[]")
            if st.form_submit_button("등록", disabled=not person):
                try:
                    proposal = {"title": title, "params_changes": json.loads(changes),
                                "override_rules": json.loads(rules or "[]")}
                except json.JSONDecodeError as exc:
                    st.error(f"JSON 오류: {exc}")
                else:
                    call(svc.add_manual_proposal, flow_id, proposal, author=person, success="등록했습니다")
                    st.rerun()

    for p in reversed(state["proposals"]):
        body = p["body"]
        with st.expander(f"{p['id']} · {body.get('title', '')} · {STATUS_KO.get(p['status'], p['status'])} · {p['source']}",
                         expanded=p["status"] in ("proposed", "simulated")):
            if DEMO_MODEL in p["source"]:
                st.caption(DEMO_BADGE)
            st.code(json.dumps({k: body.get(k) for k in ("params_changes", "override_rules", "rationale") if body.get(k)},
                               ensure_ascii=False, indent=1), language="json")
            if p["errors"]:
                st.error("검사 탈락: " + "; ".join(p["errors"]))
            if p["constraints"]:
                st.caption("적용 제약: " + "; ".join(json.dumps(c, ensure_ascii=False) for c in p["constraints"]))
            if p["status"] in ("proposed", "simulated") and st.button("전후 시뮬레이션 (계획 + 실적)", key=f"sim-{p['id']}"):
                with st.spinner("규칙 엔진과 현실 모델 3개로 시뮬레이션하는 중"):
                    call(svc.simulate_proposal, flow_id, p["id"])
                st.rerun()
            sim = p.get("simulation")
            if sim:
                before, after = sim["plan"]["before"], sim["plan"]["after"]
                st.markdown("**계획 지표 전후**")
                st.dataframe(pd.DataFrame([{"지표": k, "전": round(before[k], 4), "후": round(after[k], 4)} for k in before]),
                             hide_index=True)
                if sim["constraint_violations"]:
                    st.error("제약 위반: " + "; ".join(v["message"] for v in sim["constraint_violations"]))
                else:
                    st.success("확인된 제약 위반 없음")
                st.markdown("**실적 지표 전후 (현실 모델 3개, 실적 seed 평균)**")
                rows = []
                for prof in PROFILES:
                    cur, new = sim["outcome"]["current"][prof], sim["outcome"][p["id"]][prof]
                    for key, label in (("promise_kept_rate", "약속 준수"), ("completed_no_complaint_rate", "불만 없이 완료"),
                                       ("complaint_rate", "불만율"), ("cancel_rate", "취소율")):
                        rows.append({"현실 모델": PROFILE_KO[prof], "지표": label, "현재": pct(cur[key]), "개선안": pct(new[key])})
                st.dataframe(pd.DataFrame(rows), hide_index=True)
                for rec in sim["recommendations"]:
                    label = {"promise_kept_rate": "약속 준수", "completed_no_complaint_rate": "불만 없이 완료"}[rec["key"]]
                    verdict = ("추천: " + ("개선안" if rec["recommended"] == p["id"] else "현재 유지")) if rec["recommended"] \
                        else "보류 (현실 모델 2개 이상에서 같은 결론이 아니거나 동률)"
                    st.write(f"- {label} 기준: {verdict}")

# --- ⑤ 승인·이력 ---------------------------------------------------------------------------------
with tabs[4]:
    st.subheader("개선안 승인")
    pending = [p for p in state["proposals"] if p["status"] == "simulated"]
    if not pending:
        st.info("시뮬레이션을 마친 개선안이 없습니다.")
    for p in pending:
        with st.container(border=True):
            st.markdown(f"**{p['id']} · {p['body'].get('title', '')}**")
            note = st.text_input("메모", key=f"note-{p['id']}")
            a, b = st.columns(2)
            if a.button("승인 (params 버전 +1)", key=f"ap-{p['id']}", disabled=not person):
                call(svc.decide_proposal, flow_id, p["id"], "approve", approver=person, note=note, success="승인했습니다")
                st.rerun()
            if b.button("반려", key=f"rj-{p['id']}", disabled=not person):
                call(svc.decide_proposal, flow_id, p["id"], "reject", approver=person, note=note)
                st.rerun()

    st.subheader("추정값 보정 (실적 근거 필수)")
    with st.form("calib"):
        cols = st.columns(4)
        path = cols[0].selectbox("추정값", ESTIMATE_PATHS)
        key = cols[1].text_input("키 (예: pole, 없으면 비움)", "pole")
        value = cols[2].number_input("새 값", value=1.9, step=0.05)
        group_by = cols[3].text_input("근거 구간 차원 (difficulty, building_type, work_type, depart_hour)", "difficulty")
        table = st.selectbox("근거 집계", ["duration_ratio", "travel_ratio"])
        if st.form_submit_button("검사", disabled=not person):
            proposal = {"path": path, "key": key or None, "value": value, "source": person,
                        "evidence": {"table": table, "group_by": group_by, "group": key or "all"}}
            call(svc.check_calibration, flow_id, proposal)
            st.rerun()
    for cal in reversed(state["calibrations"]):
        prop = cal["proposal"]
        with st.container(border=True):
            st.markdown(f"**{cal['id']}** `{prop['path']}.{prop.get('key')}` {cal['current_value']} → {prop['value']} · "
                        f"{STATUS_KO.get(cal['status'], cal['status'])}")
            if cal.get("evidence_result"):
                st.caption(f"실적 근거: 실제/추정 평균 {cal['evidence_result']['mean_ratio']} (n={cal['evidence_result']['n']})")
            if cal["errors"]:
                st.error("; ".join(cal["errors"]))
            if cal["status"] == "checked":
                a, b = st.columns(2)
                if a.button("승인", key=f"cap-{cal['id']}", disabled=not person):
                    call(svc.decide_calibration, flow_id, cal["id"], "approve", approver=person)
                    st.rerun()
                if b.button("반려", key=f"crj-{cal['id']}", disabled=not person):
                    call(svc.decide_calibration, flow_id, cal["id"], "reject", approver=person, note="화면에서 반려")
                    st.rerun()

    st.subheader("변경 이력")
    if state["history"]:
        st.dataframe(pd.DataFrame([{"종류": h["type"], "id": h["id"], "승인자": h["approver"], "메모": h["note"],
                                    "버전": f"v{h['version_before']} → v{h['version_after']}",
                                    "변경": json.dumps(h["changes"].get("changes"), ensure_ascii=False), "시각": h["at"]}
                                   for h in state["history"]]), hide_index=True, width="stretch")
    else:
        st.info("아직 승인된 변경이 없습니다.")

# --- ⑥ 실행 정보 ---------------------------------------------------------------------------------
with tabs[5]:
    st.write("재현에 필요한 실행 메타데이터 (CLAUDE.md 원칙 5)")
    st.json(state["meta"])
    st.download_button("흐름 상태 내려받기 (JSON)", json.dumps(state, ensure_ascii=False, indent=1),
                       file_name=f"{flow_id}.json", mime="application/json")
