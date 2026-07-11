"""재사용 HTML 조각: 상단 바, 메시지 버블, 근거 pill, 도장, 웰컴 카드.

백엔드가 자유 텍스트 답변 + 실제 검색 결과(search_data)를 주므로,
근거 pill은 '진짜로 검색된 문서'만 표시한다. (프론트에서 지어내지 않음)
"""
import html

import streamlit as st

SOURCE_LABEL = {"neo4j": "NEO4J · 조문", "qdrant": "QDRANT · 원문"}


def _esc(text: str) -> str:
    return html.escape(text or "").replace("\n", "<br>")


def topbar() -> None:
    st.markdown(
        """
<div class="topbar">
  <div class="crest"><span>軍</span></div>
  <div>
    <div class="kr">병영생활 법률·규정 도우미</div>
    <div class="en">MILITARY LIFE ASSISTANT</div>
  </div>
  <div class="spacer"></div>
  <div class="classification">참고용 · 법률자문 아님</div>
</div>
""",
        unsafe_allow_html=True,
    )



def welcome(mode_label: str) -> str:
    return f"""
<div class="welcome">
  <h3>박병장 대기 중.</h3>
  <p>현재 모드는 <b>{_esc(mode_label)}</b>입니다.<br>
  사이드바에서 신분·분야를 고르고 궁금한 상황을 적어보세요.
  답변에는 실제 검색된 규정 근거가 함께 표시됩니다.<br><br>
  ※ 답변은 참고용이며, 정확한 판단은 부대 법무관·국선변호사에게 확인하세요.</p>
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
    if not refs and not evidence_line:
        return ""
    pills = []
    if evidence_line:
        pills.append(
            f'<span class="pill law"><span class="t">근거</span>{_esc(evidence_line)}</span>'
        )
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
    note = (
        '<div class="note"><b>안내</b> · 본 답변은 참고용입니다. '
        "정확한 판단은 소속 부대 법무관·국선변호사에게 확인하세요.</div>"
        if msg.get("needs_reference")
        else ""
    )

    return f"""
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
"""
