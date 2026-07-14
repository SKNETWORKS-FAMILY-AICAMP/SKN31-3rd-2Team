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

RANKS = ["병사", "간부"]

LEGAL_QUESTIONS = {
    "간부": [
        "장교 의무복무기간 규정은?",
        "부사관 장기복무 전환 절차는?",
        "부사관 근속진급 요건은?",
        "간부 징계의 종류는?",
        "임기 만료 전 보직해임도 가능한가요?",
    ],
    "병사": [
        "꾀병으로 근무 기피 시 처벌은?",
        "초병 근무 중 수면·음주 처벌은?",
        "상관 명령 불복종 시 처벌은?",
        "병사 징계의 종류는?",
        "부상·질병으로 복무 불가 시 절차는?"
    ]
}

FAQS = {
    "간부": [
        "장기/연장복무 선발 절차는?",
        "관사·간부숙소 지원 기준은?",
        "복지포인트 사용 불가 항목은?",
        "육아휴직 등 일·가정 양립 제도는?",
        "전문상담관 상담 신청 방법은?"
    ],
    "병사": [
        "군별 정기휴가 일수는?",
        "장병내일준비적금 혜택은?",
        "민간병원 진료비 환급은?",
        "군 복무 중 학점 취득은?",
        "상근예비역 편입 대상과 요건은?"
    ]
}

def current_category() -> str | None:
    """고충 유형(카테고리) 선택 기능이 삭제되었으므로 None을 반환하여 에러를 방지합니다."""
    return None

INPUT_PLACEHOLDER = "병영생활 중 궁금한 군 규정이나 상황을 입력하세요…"


def init() -> None:
    ss = st.session_state
    ss.setdefault("mode", "grievance")
    ss.setdefault("rank", "병사")              # 기본: 병사
    ss.setdefault("messages", [])            # [{role, ...}] 대화 기록
    ss.setdefault("thread_id", uuid.uuid4().hex[:12])  # LangGraph 대화 스레드 id
    ss.setdefault("pending_question", None)  # FAQ 버튼 클릭 시 자동 질문
    ss.setdefault("role_selected", False)


def current_category() -> str | None:
    """현재 모드의 카테고리 선택값 (없으면 None)."""
    return st.session_state.get(f"cat_{st.session_state.mode}")


def new_conversation() -> None:
    """새 대화 시작: 기록과 LangGraph 스레드를 함께 초기화."""
    st.session_state.messages = []
    st.session_state.thread_id = uuid.uuid4().hex[:12]
    st.session_state.pending_question = None
