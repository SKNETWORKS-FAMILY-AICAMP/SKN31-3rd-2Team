"""재사용 HTML 조각: 상단 바, 메시지 버블, 근거 pill, 도장, 웰컴 카드.

백엔드가 자유 텍스트 답변 + 실제 검색 결과(search_data)를 주므로,
근거 pill은 '진짜로 검색된 문서'만 표시한다. (프론트에서 지어내지 않음)
"""
import html

import streamlit as st

import base64
import functools
from pathlib import Path


@functools.lru_cache(maxsize=1)
def _bot_avatar_src() -> str:
    """박병장 아바타 PNG(루트/image/dg.png)를 base64 data URI로 인코딩(1회만).

    components.py 위치: app/ui/components.py
    이미지 위치:        (루트)/image/dg.png  → 부모를 3번 올라가면 루트.
    로컬 경로를 <img src>에 직접 쓰면 브라우저가 못 불러오므로 data URI로 심는다.
    파일이 없으면 "" 반환 → 호출부에서 '박' 텍스트로 폴백.
    """
    png_path = Path(__file__).resolve().parent.parent.parent / "images" / "park2.png"
    if png_path.exists():
        data = base64.b64encode(png_path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{data}"
    return ""


def _bot_avatar_img() -> str:
    """아바타 자리에 넣을 HTML. png를 못 찾으면 기존 '박' 텍스트로 폴백."""
    src = _bot_avatar_src()
    if not src:
        return "박"
    return f'<img class="avatar-img" src="{src}" alt="박병장">'

SOURCE_LABEL = {"neo4j": "NEO4J · 조문", "qdrant": "QDRANT · 원문"}


import re

# **굵게** 패턴 (한 줄 안에서 쌍으로 닫힌 것만, 최소 매칭)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _esc(text: str) -> str:
    return html.escape(text or "").replace("\n", "<br>")


def _esc_body(text: str) -> str:
    """답변 본문 전용 이스케이프.

    _esc()로 안전하게 이스케이프한 뒤(=태그 주입 방지), 그 '이후에'만
    **굵게** 패턴을 <strong>으로 바꾼다. escape 이후에 치환하므로
    사용자/모델이 넣은 진짜 태그가 실행될 위험은 없다.
    """
    safe = _esc(text)
    return _BOLD_RE.sub(r"<strong>\1</strong>", safe)


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
        _no_blank_lines("""
<div class="topbar">
<div class="crest"><span>軍</span></div>
<div>
<div class="kr">병영 생활 법률 · 규정 도우미</div>
<div class="en">MILITARY LIFE ASSISTANT</div>
</div>
<div class="spacer"></div>
</div>
"""),
        unsafe_allow_html=True,
    )


def welcome(mode_label: str) -> str:
    return _no_blank_lines("""
<div class="welcome">
<h3>박병장 대기 중.</h3>
<p>※ 답변은 참고용이며, 정확한 판단은 부대 법무관·국선변호사에게 확인하세요.</p>
</div>
""")


def loading_bubble(text: str = "박병장이 캐비닛 깊숙이 규정집 들추는 중…") -> str:
    """답변 생성 중 좌측에 표시하는 박병장 형태의 로딩 버블."""
    return _no_blank_lines(f"""
<div class="msg loading">
<div class="avatar bot">{_bot_avatar_img()}</div>
<div class="bubble">
<div class="b-body"><span class="dots"><i></i><i></i><i></i></span>{_esc(text)}</div>
</div>
</div>
""")


def user_bubble(text: str) -> str:
    return _no_blank_lines(f"""
<div class="msg user">
<div class="bubble"><div class="b-body">{_esc(text)}</div></div>
</div>
""")


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
    return _no_blank_lines(f"""
<div class="refs">
<div class="rlabel">참조 근거 · 검색된 문서</div>
{''.join(pills)}
</div>
""")


def bot_bubble(msg: dict, mode_code: str) -> str:
    """assistant 메시지 dict → HTML.

    msg: api_client.ask_bot() 반환값에 role이 추가된 dict.
    """
    if not msg.get("ok", True):
        return _no_blank_lines(f"""
<div class="msg">
<div class="avatar bot">{_bot_avatar_img()}</div>
<div class="bubble">
<div class="b-head"><span class="name">시스템</span>
<span class="badge err">연결 오류</span></div>
<div class="b-body">{_esc(msg.get('error', '알 수 없는 오류'))}</div>
</div>
</div>
""")

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
<div class="avatar bot">{_bot_avatar_img()}</div>
<div class="bubble">
<div class="b-head">
<span class="name">박병장</span>
{src_badge}
<span class="code">{_esc(mode_code)}</span>
</div>
<div class="b-body">{_esc_body(msg.get('answer', ''))}</div>
{refs_block}
{note}
</div>
</div>
""")