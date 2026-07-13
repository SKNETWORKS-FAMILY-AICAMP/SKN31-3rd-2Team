"""병영생활 법률·규정 도우미 — Streamlit 진입점.

역할: 조립만. (스타일 주입 → 사이드바 → 상단바 → 배너 → 채팅)
백엔드는 같은 폴더의 run_chatbot.py(LangGraphChatbot)를 그대로 사용한다.
실행: streamlit run streamlit_app.py
UI만 점검: MLA_FAKE_BACKEND=1 streamlit run streamlit_app.py
"""
import streamlit as st

st.set_page_config(
    page_title="병영생활 법률·규정 도우미",
    page_icon="🎖",
    layout="wide",
    initial_sidebar_state="expanded",
)

from state import session
from ui import chat, components, sidebar, styles, welcome_screen

session.init()
styles.inject()

if not st.session_state.role_selected:
    welcome_screen.render()
    st.stop()

sidebar.render()
components.topbar()
chat.render()
