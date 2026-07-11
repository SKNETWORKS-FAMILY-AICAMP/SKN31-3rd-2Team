"""세션 상태 초기화·상수 정의.

모드/계급/카테고리/FAQ 목록과 st.session_state 기본값을 한 곳에서 관리한다.
카테고리 위젯은 모드별 key(cat_grievance / cat_benefit)를 쓰므로
모드를 바꾸면 자동으로 해당 모드의 선택 상태로 전환된다.
"""
import uuid

import streamlit as st

MODES = {
    "grievance": "🛡 고충 해결",
    "benefit": "🎖 혜택 안내",
}

MODE_SUB = {
    "grievance": "GRIEVANCE · 위법 판단",
    "benefit": "BENEFIT · 복지 탐색",
}

RANKS = [
    "병사 — 이병",
    "병사 — 일병",
    "병사 — 상병",
    "병사 — 병장",
    "부사관",
    "장교",
]

CATEGORIES = {
    "grievance": ["사적 심부름", "전투휴무 미지급", "언어폭력", "부당 징계", "휴가 통제"],
    "benefit": ["자기계발", "휴가·외출", "의료 지원", "급여·수당", "전역 후 지원"],
}

FAQS = {
    "grievance": [
        "사적 심부름, 거부해도 되나요?",
        "휴가 잘린 거 신고할 수 있나요?",
        "익명 신고는 어떻게 하나요?",
    ],
    "benefit": [
        "병장이 받을 수 있는 자기계발 지원은?",
        "민간병원 진료도 되나요?",
        "전역 후 취업 지원 뭐가 있죠?",
    ],
}

INPUT_PLACEHOLDER = {
    "grievance": "부당하다고 느낀 상황을 편하게 적어보세요…",
    "benefit": "받을 수 있는 혜택이 궁금한 걸 물어보세요…",
}


def init() -> None:
    ss = st.session_state
    ss.setdefault("mode", "grievance")
    ss.setdefault("rank", RANKS[3])          # 기본: 병사 — 병장
    ss.setdefault("messages", [])            # [{role, ...}] 대화 기록
    ss.setdefault("thread_id", uuid.uuid4().hex[:12])  # LangGraph 대화 스레드 id
    ss.setdefault("pending_question", None)  # FAQ 버튼 클릭 시 자동 질문


def current_category() -> str | None:
    """현재 모드의 카테고리 선택값 (없으면 None)."""
    return st.session_state.get(f"cat_{st.session_state.mode}")


def new_conversation() -> None:
    """새 대화 시작: 기록과 LangGraph 스레드를 함께 초기화."""
    st.session_state.messages = []
    st.session_state.thread_id = uuid.uuid4().hex[:12]
    st.session_state.pending_question = None
