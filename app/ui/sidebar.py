import streamlit as st

from state import session
# CATEGORIES 대신 LEGAL_QUESTIONS를 불러옵니다.
from state.session import FAQS, LEGAL_QUESTIONS

def _eyebrow(text: str) -> None:
    st.markdown(f'<div class="eyebrow">{text}</div>', unsafe_allow_html=True)

def render() -> None:
    ss = st.session_state
    with st.sidebar:
        # 1. 시작화면(신분 선택)으로 돌아가는 버튼 (왼쪽 상단 배치)
        if st.button("← 신분 다시 선택하기", key="back_to_welcome", use_container_width=True):
            ss.role_selected = False       
            session.new_conversation()     
            st.rerun()                     

        # 현재 사용자의 신분 (병사 또는 간부)
        rank = ss.rank
        
        # 2. 법률 질문 (버튼 클릭 시 챗봇으로 질문 전달)
        _eyebrow(f"법률 질문 · {rank}")
        for i, q in enumerate(LEGAL_QUESTIONS.get(rank, [])):
            if st.button(f"› {q}", key=f"legal_{rank}_{i}"):
                ss.pending_question = q

        # 3. 자주 묻는 질문 (기존 FAQ 유지)
        _eyebrow("자주 묻는 질문 · FAQ")
        for i, q in enumerate(FAQS.get(rank, [])):
            if st.button(f"› {q}", key=f"faq_{rank}_{i}"):
                ss.pending_question = q

        st.divider()
        if st.button("⟳ 새 대화 시작", key="new_chat", use_container_width=True):
            session.new_conversation()
            st.rerun()

        # 긴급신고는 고정
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