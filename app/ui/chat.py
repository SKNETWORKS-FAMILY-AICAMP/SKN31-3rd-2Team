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


def _history_html(ss) -> str:
    """현재까지의 대화 기록을 버블 HTML 문자열로 조립."""
    blocks = []
    for m in ss.messages:
        if m["role"] == "user":
            blocks.append(components.user_bubble(m["content"]))
        else:
            blocks.append(components.bot_bubble(m, _mode_code(m)))
    return "".join(blocks)


def render() -> None:
    ss = st.session_state

    # 1) 대화 기록을 흰 카드(.chatcard) 안에 렌더.
    #    로딩 중에는 이 카드 자리에 기록 + 로딩 버블을 함께 그려 넣으므로
    #    placeholder(st.empty)로 잡아둔다.
    card = st.empty()
    if not ss.messages:
        card.markdown(
            f'<div class="chatcard">{components.welcome(MODES[ss.mode])}</div>',
            unsafe_allow_html=True,
        )
    else:
        card.markdown(
            f'<div class="chatcard">{_history_html(ss)}</div>',
            unsafe_allow_html=True,
        )

    # 2) 질문 수신 (입력창 우선, FAQ 클릭은 pending으로)
    question = st.chat_input(INPUT_PLACEHOLDER)
    if not question and ss.pending_question:
        question = ss.pending_question
        ss.pending_question = None

    if not question:
        return

    # 3) 사용자 메시지 기록 + 백엔드 호출
    ss.messages.append({"role": "user", "content": question})
    category = session.current_category()

    # 로딩 중: 카드 안에 '기록 + 좌측 박병장 로딩 버블'을 함께 그려
    #          레이아웃이 흔들리지 않게 한다.
    card.markdown(
        f'<div class="chatcard">{_history_html(ss)}{components.loading_bubble()}</div>',
        unsafe_allow_html=True,
    )

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
