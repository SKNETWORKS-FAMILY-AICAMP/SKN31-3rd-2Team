"""시작화면: 병사 / 간부를 선택하는 첫 진입 화면 (간단 버전).

앱을 처음 켜거나 아직 신분을 안 고른 상태(role_selected=False)일 때 이 화면을 보여준다.
'병사' 또는 '간부' 버튼을 누르면 st.session_state에 저장하고 채팅 화면으로 넘어간다.
백엔드(박병장 페르소나)는 '간부 vs 병사'로 말투를 나누므로 이 큰 구분만 정하면 된다.
"""
import streamlit as st


def _pick(rank_label: str) -> None:
    """선택 확정: 신분을 저장하고 채팅 화면으로 전환."""
    st.session_state.rank = rank_label
    st.session_state.role_selected = True
    st.rerun()


def render() -> None:
    st.markdown(
        """
<div class="ws-hero">
  <div class="ws-crest"><span>軍</span></div>
  <div class="ws-title">병영생활 법률·규정 도우미</div>
  <div class="ws-sub">MILITARY LIFE ASSISTANT</div>
  <div class="ws-desc">먼저 당신의 신분을 선택하세요.<br>신분에 따라 박병장이 응대 방식을 맞춥니다.</div>
</div>
""",
        unsafe_allow_html=True,
    )

    col_left, col_right = st.columns(2, gap="large")

    with col_left:
        st.markdown(
            '<div class="ws-card ws-card-enlisted">'
            '<div class="ws-ic">🪖</div>'
            '<div class="ws-ct">병사</div>'
            '<div class="ws-cs">이병 · 일병 · 상병 · 병장</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        if st.button("병사로 시작", key="ws_btn_enlisted", use_container_width=True):
            _pick("병사")

    with col_right:
        st.markdown(
            '<div class="ws-card ws-card-officer">'
            '<div class="ws-ic">🎖</div>'
            '<div class="ws-ct">간부</div>'
            '<div class="ws-cs">부사관 · 장교</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        if st.button("간부로 시작", key="ws_btn_officer", use_container_width=True):
            _pick("간부")
