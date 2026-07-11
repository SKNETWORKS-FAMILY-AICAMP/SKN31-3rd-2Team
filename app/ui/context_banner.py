"""채팅 상단 컨텍스트 배너: 현재 MODE · ROLE · FILTER · 대화 번호."""
import streamlit as st

from state import session
from state.session import MODES


def render() -> None:
    ss = st.session_state
    category = session.current_category() or "전체"
    case_no = f"CASE-{ss.thread_id[:6].upper()}"
    st.markdown(
        f"""
<div class="ctx">
  <div class="seg"><span class="k">MODE</span><span class="v amber">{MODES[ss.mode]}</span></div>
  <div class="seg"><span class="k">ROLE</span><span class="v">{ss.rank}</span></div>
  <div class="seg"><span class="k">FILTER</span><span class="v">{category}</span></div>
  <div class="spacer"></div>
  <div class="file">{case_no}</div>
</div>
""",
        unsafe_allow_html=True,
    )
