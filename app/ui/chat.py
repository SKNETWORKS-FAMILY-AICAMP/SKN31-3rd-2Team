"""채팅 영역: 대화 기록 렌더링 + 입력 처리 + 백엔드 호출.

흐름:
  1) 기록 렌더링 (user/bot 버블 HTML)
  2) st.chat_input 또는 FAQ 클릭(pending_question)으로 질문 수신
  3) 질문을 기록에 추가 → 스피너 표시하며 api_client.ask_bot 호출
  4) 응답을 기록에 추가하고 rerun (기록 렌더링으로 화면 갱신)
"""
import streamlit as st

from services import api_client
from state import session
from state.session import INPUT_PLACEHOLDER, MODES
from ui import components

MODE_CODE = {"grievance": "GRIEVANCE", "benefit": "BENEFIT"}


def _mode_code(msg: dict) -> str:
    code = MODE_CODE.get(msg.get("mode", ""), "")
    cat = msg.get("category")
    return f"{code} ▸ {cat}" if cat else code


def render() -> None:
    ss = st.session_state

    # 1) 대화 기록
    if not ss.messages:
        st.markdown(components.welcome(MODES[ss.mode]), unsafe_allow_html=True)
    else:
        blocks = []
        for m in ss.messages:
            if m["role"] == "user":
                blocks.append(components.user_bubble(m["content"]))
            else:
                blocks.append(components.bot_bubble(m, _mode_code(m)))
        st.markdown("".join(blocks), unsafe_allow_html=True)


    # 2) 질문 수신 (입력창 우선, FAQ 클릭은 pending으로)
    question = st.chat_input(INPUT_PLACEHOLDER[ss.mode])
    if not question and ss.pending_question:
        question = ss.pending_question
        ss.pending_question = None

    if not question:
        return

    # 3) 사용자 메시지 기록 + 백엔드 호출
    ss.messages.append({"role": "user", "content": question})
    category = session.current_category()

    with st.spinner("박병장이 규정집 뒤지는 중…"):
        result = api_client.ask_bot(
            question=question,
            rank=ss.rank,
            mode_label=MODES[ss.mode],
            category=category,
            thread_id=ss.thread_id,
        )

    # 4) 응답 기록 (표시용 컨텍스트 포함) 후 갱신
    ss.messages.append(
        {"role": "assistant", "mode": ss.mode, "category": category, **result}
    )
    st.rerun()
