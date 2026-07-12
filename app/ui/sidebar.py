"""사이드바: 모드 토글 · 신분/계급 · 카테고리 · FAQ · 새 대화 · 긴급 신고."""
import streamlit as st

from state import session
from state.session import CATEGORIES, FAQS, MODES, MODE_SUB, RANKS


def _eyebrow(text: str) -> None:
    st.markdown(f'<div class="eyebrow">{text}</div>', unsafe_allow_html=True)


def render() -> None:
    ss = st.session_state
    with st.sidebar:
        _eyebrow("임무 선택 · MODE")
        st.radio(
            "임무 선택",
            options=list(MODES.keys()),
            format_func=lambda k: f"{MODES[k]}  ·  {MODE_SUB[k]}",
            key="mode",
            label_visibility="collapsed",
        )


        mode = ss.mode
        _eyebrow("고충 유형 · GRIEVANCE" if mode == "grievance" else "혜택 분야 · BENEFIT")
        # 모드별 key → 모드를 바꾸면 그 모드의 선택 상태로 자동 전환
        st.pills(
            "분야",
            options=CATEGORIES[mode],
            selection_mode="single",
            key=f"cat_{mode}",
            label_visibility="collapsed",
        )

        _eyebrow("자주 묻는 질문 · FAQ")
        for i, q in enumerate(FAQS[mode]):
            if st.button(f"› {q}", key=f"faq_{mode}_{i}"):
                ss.pending_question = q

        st.divider()
        if st.button("⟳ 새 대화 시작", key="new_chat"):
            session.new_conversation()
            st.rerun()

        st.markdown(
            """
<div class="report">
  <div class="rt">긴급 신고 · 국방헬프콜</div>
  <div class="num">1303</div>
  <p>부조리·인권침해·성폭력은 챗봇 답변보다 실제 신고가 우선입니다.
  본 서비스의 답변은 참고용이며 법률 자문이 아닙니다.</p>
</div>
""",
            unsafe_allow_html=True,
        )
