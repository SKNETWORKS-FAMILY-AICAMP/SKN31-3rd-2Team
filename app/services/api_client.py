"""백엔드(run_chatbot.LangGraphChatbot) 연결 브리지.

- 백엔드 파일(run_chatbot.py / graphdb_retriever.py / vectordb_retriever.py)은
  이 프로젝트 루트에 그대로 있고, 여기서는 '수정 없이' 임포트해서 쓴다.
- bot.ask() 대신 workflow.invoke()를 직접 호출해 최종 state 전체를 받는다.
  → answer뿐 아니라 source(neo4j/qdrant), search_data(실제 검색된 근거)까지
    화면에 표시할 수 있다.
- 답변 끝의 "[근거: ...]" 줄은 분리해서 근거 태그로 렌더링한다.

환경변수(.env — 백엔드와 동일):
  OPENAI_API_KEY, NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD,
  QDRANT_URL, QDRANT_API_KEY(선택), QDRANT_COLLECTION(선택)

UI 점검용: 환경변수 MLA_FAKE_BACKEND=1 이면 DB·LLM 없이
'샘플 응답'이라고 명시된 고정 응답을 돌려준다. (화면 개발/디자인 확인 전용)
"""
from __future__ import annotations

import os, sys
import re
from typing import Any

import streamlit as st

# 답변 맨 끝의 [근거: ...] 줄 추출용
_EVIDENCE_RE = re.compile(r"\[\s*근거\s*:\s*(.+?)\s*\]\s*$", re.DOTALL)

_d = os.path.dirname(os.path.abspath(__file__))
while _d != os.path.dirname(_d):  # 파일시스템 최상단까지
    if os.path.exists(os.path.join(_d, "run_chatbot.py")):
        if _d not in sys.path:
            sys.path.insert(0, _d)
        break
    _d = os.path.dirname(_d)

@st.cache_resource(show_spinner=False)
def _get_bot():
    """봇을 프로세스당 1회만 생성 (Streamlit rerun마다 재생성 방지)."""
    from run_chatbot import LangGraphChatbot
    return LangGraphChatbot(verbose=False)


def _split_evidence(answer: str) -> tuple[str, str | None]:
    """답변 본문과 마지막 '[근거: ...]' 줄을 분리."""
    m = _EVIDENCE_RE.search(answer)
    if not m:
        return answer.strip(), None
    body = answer[: m.start()].rstrip()
    return body, m.group(1).strip()


# 도구 이름 → 화면 출처(배지) 매핑
_TOOL_SOURCE = {
    "search_law_knowledge_graph": "neo4j",
    "search_guidance_knowledge_base": "qdrant",
}

# 법령 도구 출력의 조문 헤더: "[조문] 군인사법 제31조 (ID: ...::제31조)"
_LAW_LINE_RE = re.compile(r"\[조문\]\s*(?P<name>.*?)\s*\(ID:\s*(?P<id>.*?)\)")


def _refs_from_messages(messages) -> tuple[str | None, list[dict]]:
    """에이전트 메시지에서 (출처, 근거 pill 목록)을 파생.

    - 어떤 @tool이 호출됐는지로 출처(neo4j/qdrant)를 판별.
    - 법령 도구 출력의 '[조문] 이름 (ID:...)' 헤더를 파싱해 조문 pill 생성.
    - 길라잡이 도구는 현재 text만 반환하므로 '참조 문서 N' 단위 pill로만 표기.
    """
    source: str | None = None
    refs: list[dict] = []

    for m in messages:
        is_tool = getattr(m, "type", None) == "tool" or m.__class__.__name__ == "ToolMessage"
        if not is_tool:
            continue

        tool_name = getattr(m, "name", "") or ""
        source = _TOOL_SOURCE.get(tool_name, source)
        content = m.content if isinstance(m.content, str) else str(m.content)

        if tool_name == "search_law_knowledge_graph":
            for mt in _LAW_LINE_RE.finditer(content):
                name = (mt.group("name") or "").strip()
                article_no = (mt.group("id") or "").strip().split("::")[-1]
                label = f"{name} · {article_no}" if article_no and article_no != name else (name or article_no)
                if label:
                    refs.append({"tag": "LAW", "label": label})
        elif tool_name == "search_guidance_knowledge_base":
            for i in range(1, content.count("[참조 문서") + 1):
                refs.append({"tag": "PDF", "label": f"길라잡이 참조 {i}"})

    return source, refs


def _fake_response(question: str) -> dict[str, Any]:
    """MLA_FAKE_BACKEND=1 전용. 화면 확인용 샘플이며 실제 규정 정보가 아님."""
    return {
        "ok": True,
        "answer": (
            "⚠️ (UI 점검용 샘플 응답입니다 — 실제 규정 답변이 아닙니다.)\n\n"
            f"질문 잘 받았다: \"{question}\"\n"
            "실제 실행에서는 이 자리에 박병장의 답변이 검색된 규정을 근거로 표시됩니다."
        ),
        "evidence_line": "샘플 — 실제 근거 아님",
        "source": "neo4j",
        "needs_reference": True,
        "refs": [
            {"tag": "LAW", "label": "샘플 조문 표시 위치 · 제N조"},
            {"tag": "PDF", "label": "샘플 문서 표시 위치 · p.0"},
        ],
    }


def ask_bot(
    question: str,
    rank: str,
    mode_label: str,
    category: str | None,
    thread_id: str,
    top_k: int = 3,
) -> dict[str, Any]:
    """질문을 백엔드 봇에 보내고 화면 렌더링용 dict를 반환.

    질문 앞에 신분/분야 태그를 붙이는 이유:
    - GENERATE_PROMPT(박병장)가 질문자 신분(간부 vs 병사)에 따라 말투를 바꾸므로,
      사이드바에서 고른 계급을 봇이 알 수 있게 전달한다.
    - 카테고리는 검색·답변의 초점을 좁히는 힌트가 된다.
    반환: {ok, answer, evidence_line, source, needs_reference, refs} 또는 {ok:False, error}
    """
    if os.getenv("MLA_FAKE_BACKEND") == "1":
        return _fake_response(question)

    try:
        from langchain_core.messages import HumanMessage

        bot = _get_bot()

        tags = [f"[질문자 신분: {rank}]"]
        if category:
            tags.append(f"[상담 분야: {mode_label} · {category}]")
        user_query = " ".join(tags) + " " + question

        config = {"configurable": {"thread_id": thread_id}}
        result = bot.agent.invoke(
            {"messages": [HumanMessage(content=user_query)]},
            config=config,
        )
        messages = result["messages"]

        answer = messages[-1].content if messages else "답변을 생성하지 못했습니다."
        if isinstance(answer, list):  # content가 블록 리스트로 올 때 방어
            answer = "".join(p.get("text", "") for p in answer if isinstance(p, dict))
        body, evidence_line = _split_evidence(answer or "")

        source, refs = _refs_from_messages(messages)
        needs_reference = bool(refs)

        return {
            "ok": True,
            "answer": body,
            "evidence_line": evidence_line,
            "source": source if needs_reference else None,
            "needs_reference": needs_reference,
            "refs": refs,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": (
                f"백엔드 호출 실패: {type(exc).__name__} — {exc}\n"
                ".env의 OPENAI_API_KEY / NEO4J_* / QDRANT_* 설정과 "
                "DB 실행 상태를 확인하세요."
            ),
        }
