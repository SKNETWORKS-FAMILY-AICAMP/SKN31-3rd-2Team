"""재사용 HTML 조각: 상단 바, 메시지 버블, 근거 pill, 도장, 웰컴 카드.

백엔드가 자유 텍스트 답변 + 실제 검색 결과(search_data)를 주므로,
근거 pill은 '진짜로 검색된 문서'만 표시한다. (프론트에서 지어내지 않음)
"""
import html

import streamlit as st

SOURCE_LABEL = {"neo4j": "NEO4J · 조문", "qdrant": "QDRANT · 원문"}


def _esc(text: str) -> str:
    return html.escape(text or "").replace("\n", "<br>")


def _no_blank_lines(s: str) -> str:
    """빈 줄(공백만 있는 줄 포함)을 제거.

    src_badge/refs_block/note처럼 값이 없을 때 "" 로 채워지는 자리가
    템플릿 안에서 빈 줄이 되면, 마크다운이 그 지점에서 raw HTML 블록을
    끊어버리고 이후 내용을 들여쓰기 코드블록(문자 그대로 표시)으로
    오인하는 문제가 있다. (Neo4j/Qdrant 근거가 없는 질문에서 답변이
    HTML 태그째로 화면에 새어나오던 버그의 원인)
    빈 줄을 없애 HTML 블록이 끊기지 않게 한다.
    """
    return "\n".join(line for line in s.split("\n") if line.strip() != "")


def topbar() -> None:
    st.markdown(
        """
<div class="topbar">
  <div class="crest"><span>軍</span></div>
  <div>
    <div class="kr">병영 생활 법률 · 규정 도우미</div>
    <div class="en">MILITARY LIFE ASSISTANT</div>
  </div>
  <div class="spacer"></div>
</div>
""",
        unsafe_allow_html=True,
    )


def welcome(mode_label: str) -> str:
    return f"""
<div class="welcome">
  <h3>박병장 대기 중.</h3>
  <p>※ 답변은 참고용이며, 정확한 판단은 부대 법무관·국선변호사에게 확인하세요.</p>
</div>
"""


def user_bubble(text: str) -> str:
    return f"""
<div class="msg user">
  <div class="avatar me">나</div>
  <div class="bubble"><div class="b-body">{_esc(text)}</div></div>
</div>
"""


def _refs_html(refs: list[dict], evidence_line: str | None) -> str:
    # 실제 검색된 문서(refs)가 있을 때만 블록을 표시한다.
    if not refs:
        return ""
    pills = []
    # 주: evidence_line("근거 …" pill)은 LLM이 답변 끝에 쓴 [근거:] 줄에서
    # 온 것으로, 실제 검색된 문서가 아니므로 표시하지 않는다.
    # (LAW/PDF pill = Qdrant/Neo4j 검색 결과만 근거로 표기)
    for r in refs:
        cls = "pdf" if r.get("tag") == "PDF" else "law"
        pills.append(
            f'<span class="pill {cls}"><span class="t">{_esc(r.get("tag", ""))}</span>'
            f'{_esc(r.get("label", ""))}</span>'
        )
    return f"""
<div class="refs">
  <div class="rlabel">참조 근거 · 검색된 문서</div>
  {''.join(pills)}
</div>
"""


def bot_bubble(msg: dict, mode_code: str) -> str:
    """assistant 메시지 dict → HTML.

    msg: api_client.ask_bot() 반환값에 role이 추가된 dict.
    """
    if not msg.get("ok", True):
        return f"""
<div class="msg">
  <div class="avatar bot">!</div>
  <div class="bubble">
    <div class="b-head"><span class="name">시스템</span>
      <span class="badge err">연결 오류</span></div>
    <div class="b-body">{_esc(msg.get('error', '알 수 없는 오류'))}</div>
  </div>
</div>
"""

    source = msg.get("source")
    src_badge = (
        f'<span class="badge src">{_esc(SOURCE_LABEL.get(source, source))}</span>'
        if source
        else ""
    )
    refs_block = _refs_html(msg.get("refs") or [], msg.get("evidence_line"))
    note = ""

    return _no_blank_lines(f"""
<div class="msg">
  <div class="avatar bot">박</div>
  <div class="bubble">
    <div class="b-head">
      <span class="name">박병장</span>
      {src_badge}
      <span class="code">{_esc(mode_code)}</span>
    </div>
    <div class="b-body">{_esc(msg.get('answer', ''))}</div>
    {refs_block}
    {note}
  </div>
</div>
""")