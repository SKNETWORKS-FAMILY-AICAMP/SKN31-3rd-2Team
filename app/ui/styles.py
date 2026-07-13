"""야전교범(Field Manual) 테마 CSS - 프레시 아미(Fresh Army) 컨셉.

시안의 색 토큰을 Streamlit 위에 입힌다.
- 사이드바: 산뜻한 포레스트 그린 / 본문: 쾌적한 화이트
- 시그니처: 우측 하단 '참고용 REFERENCE ONLY' 도장
- 근거 pill(LAW 앰버 / PDF 그린), 컨텍스트 배너, 메시지 버블
Streamlit 내부 DOM 셀렉터는 버전에 따라 바뀔 수 있으므로,
깨져도 기능엔 영향 없는 '장식' 위주로만 건드린다.
"""
import streamlit as st

CSS = """
<style>
:root{
  /* 메인 색상: 프레시 아미 (산뜻한 숲의 색) */
  --shell:#1A2421;        /* 가장 어두운 흑녹색 */
  --od:#2F5233;           /* 메인 사이드바 바탕: 산뜻하고 짙은 그린 */
  --od-2:#3B6940;         /* 활성화된 버튼 등: 조금 더 밝은 그린 */
  --od-line:#7A9D79;      /* 사이드바 테두리 및 구분선 */
  
  /* 보조 포인트 색상 */
  --khaki:#B4C5B0;        /* 칙칙한 카키 대신 맑고 은은한 세이지 그린 */
  --khaki-dim:#84A587;
  
  /* 배경 색상: 누런 종이(paper)를 깨끗한 무채색 베이스로 교체 */
  --paper:#F4F7F4;        /* 전체 배경: 아주 옅은 민트/그레이 톤 화이트 */
  --paper-2:#FFFFFF;      /* 메시지 버블 및 카드: 순백색 */
  --paper-line:#D1DBD4;   /* 연한 구분선 */
  
  /* 텍스트 색상 */
  --ink:#1A2421;          /* 기본 텍스트 (눈이 편안한 짙은 흑녹색) */
  --ink-soft:#5C6B64;     /* 설명 텍스트 */
  
  /* 포인트 뱃지 색상 (경고, 성공 등은 기존의 눈에 띄는 색 유지) */
  --amber:#E79E24;        
  --amber-soft:#F5B942;
  --red:#D93838;          
  --red-soft:#E85D5D; 
  --green-ok:#388E3C;     
}

/* ---------- 앱 배경: 종이 질감 제거 및 모던한 배경 ---------- */
.stApp{
  background-color:var(--paper);
  /* 칙칙했던 종이 질감을 삭제하여 화면을 쾌적하고 깔끔하게 만듭니다 */
}
header[data-testid="stHeader"]{background:transparent;}
.block-container{padding-top:0.8rem;padding-bottom:6.5rem;max-width:1050px;}

/* ---------- 사이드바: 프레시 아미 그린 ---------- */
[data-testid="stSidebar"]{
  background:var(--od);
  border-right:2px solid var(--od-line);
}
[data-testid="stSidebar"] *{color:#FFFFFF;} /* 텍스트를 또렷한 흰색으로 변경 */
[data-testid="stSidebar"] .eyebrow{
  font-size:10px;letter-spacing:.24em;color:var(--khaki)!important;
  font-weight:700;display:flex;align-items:center;gap:8px;margin:6px 0 2px;
}
[data-testid="stSidebar"] .eyebrow::after{content:"";flex:1;height:1px;background:var(--od-line);}

/* selectbox / pills / 버튼 */
[data-testid="stSidebar"] [data-baseweb="select"] > div{
  background:var(--od-2);border:1.5px solid var(--od-line);border-radius:0;
}
[data-testid="stSidebar"] button[kind="pills"],
[data-testid="stSidebar"] button[kind="pillsActive"]{
  border-radius:0;border:1px solid var(--od-line);
  background:transparent;color:var(--paper);font-size:12.5px;
}
[data-testid="stSidebar"] button[kind="pillsActive"]{
  background:var(--amber);border-color:var(--amber);color:var(--shell);font-weight:700;
}
[data-testid="stSidebar"] .stButton button{
  width:100%;text-align:left;justify-content:flex-start;
  background:transparent;border:1px dashed var(--od-line);border-radius:0;
  color:var(--paper);font-size:12.5px;padding:8px 11px;
}
[data-testid="stSidebar"] .stButton button:hover{border-color:var(--amber);color:var(--amber-soft);}

/* 긴급 신고 블록 */
.report{border:1.5px solid var(--red-soft);background:rgba(217,56,56,.18);padding:12px 13px;margin-top:10px;}
.report .rt{display:flex;align-items:center;gap:8px;font-size:11.5px;font-weight:800;color:var(--red-soft)!important;margin-bottom:6px;}
.report .rt::before{content:"▲";font-size:10px;}
.report .num{font-family:monospace;font-size:20px;font-weight:900;letter-spacing:.04em;color:var(--paper-2)!important;}
.report p{font-size:10.5px;line-height:1.5;color:var(--khaki)!important;margin:5px 0 0;}

/* ---------- 상단 바 ---------- */
.topbar{
  background:var(--shell);border-bottom:2px solid var(--od-line);
  display:flex;align-items:center;gap:14px;padding:10px 18px;color:var(--paper);
  margin:0 0 12px;
}
.topbar .crest{
  width:28px;height:28px;flex:none;border:2px solid var(--amber);
  display:grid;place-items:center;color:var(--amber);
  font-weight:900;font-size:13px;transform:rotate(45deg);
}
.topbar .crest span{transform:rotate(-45deg);}
.topbar .kr{font-weight:900;font-size:15px;color:var(--paper-2);}
.topbar .en{font-size:9.5px;letter-spacing:.3em;color:var(--khaki);}
.topbar .spacer{flex:1;}
.topbar .classification{
  font-size:10px;letter-spacing:.24em;color:var(--shell);
  background:var(--amber);padding:3px 10px;font-weight:700;
}

/* ---------- 메시지 버블 ---------- */
.msg{display:flex;gap:12px;max-width:860px;margin-bottom:16px;}
.msg.user{margin-left:auto;flex-direction:row-reverse;max-width:640px;}
.avatar{
  width:34px;height:34px;flex:none;display:grid;place-items:center;
  font-size:11.5px;font-weight:900;
}
.avatar.bot{background:var(--od);color:var(--amber-soft);border:1.5px solid var(--od-line);}
.avatar.me{background:var(--paper-2);color:var(--ink);border:1.5px solid var(--paper-line);}
.bubble{border:1.5px solid var(--paper-line);background:var(--paper-2);flex:1;min-width:0;}
.msg.user .bubble{background:var(--od);border-color:var(--od-line);}
.msg.user .b-body{color:var(--paper-2);}
.b-head{display:flex;align-items:center;gap:9px;background:var(--paper-line);padding:5px 12px;flex-wrap:wrap;}
.b-head .name{font-size:11px;font-weight:800;color:var(--ink);}
.b-head .code{font-family:monospace;font-size:9px;letter-spacing:.14em;color:var(--ink-soft);margin-left:auto;}
.badge{font-size:10px;font-weight:800;letter-spacing:.05em;padding:1px 8px;color:#fff;}
.badge.src{background:var(--green-ok);}
.badge.err{background:var(--red);}
.b-body{padding:13px 15px;font-size:13.5px;line-height:1.65;color:var(--ink);white-space:pre-wrap;word-break:break-word;}

/* 근거 pill */
.refs{border-top:1px dashed var(--paper-line);padding:9px 15px 11px;}
.refs .rlabel{font-size:9px;letter-spacing:.14em;color:var(--ink-soft);font-weight:800;margin-bottom:5px;}
.pill{
  display:inline-flex;align-items:center;gap:6px;border:1px solid var(--paper-line);
  background:var(--paper);padding:3px 9px;font-size:11.5px;margin:2px 5px 2px 0;font-weight:600;color:var(--ink);
}
.pill.law{border-left:3px solid var(--amber);}
.pill.pdf{border-left:3px solid var(--green-ok);}
.pill .t{font-family:monospace;font-size:8.5px;letter-spacing:.1em;color:var(--ink-soft);}
.note{border-top:1px dashed var(--paper-line);padding:8px 15px 10px;font-size:10.5px;color:var(--ink-soft);line-height:1.5;}
.note b{color:var(--red);}

/* 빈 화면 웰컴 카드 */
.welcome{
  border:1.5px dashed var(--paper-line);background:var(--paper-2);
  padding:26px 28px;max-width:640px;margin:40px auto;
}
.welcome h3{margin:0 0 8px;font-size:16px;color:var(--ink);}
.welcome p{margin:0;font-size:12.5px;line-height:1.7;color:var(--ink-soft);}

/* ---------- 참고용 도장 (시그니처) ---------- */
.stamp{
  position:fixed;right:34px;bottom:96px;z-index:50;
  border:3px solid var(--red);color:var(--red);
  padding:8px 14px;transform:rotate(-11deg);opacity:.45;
  text-align:center;pointer-events:none;mix-blend-mode:multiply;
}
.stamp .s1{font-size:16px;font-weight:900;letter-spacing:.14em;line-height:1;}
.stamp .s2{font-size:8px;letter-spacing:.2em;margin-top:3px;}
.stamp::before,.stamp::after{content:"";position:absolute;left:5px;right:5px;height:1.5px;background:var(--red);}
.stamp::before{top:3px;}.stamp::after{bottom:3px;}

/* ---------- 채팅 입력 ---------- */
[data-testid="stChatInput"]{background:var(--paper-2);border:1.5px solid var(--paper-line);border-radius:0;}
[data-testid="stChatInput"] textarea{color:var(--ink);}
[data-testid="stBottomBlockContainer"],[data-testid="stBottom"]>div{background:transparent;}

/* ---------- 시작화면 (병사/간부 선택) ---------- */
.ws-hero{text-align:center;margin:32px auto 26px;max-width:640px;}
.ws-crest{
  width:56px;height:56px;margin:0 auto 16px;border:3px solid var(--amber);
  display:grid;place-items:center;color:var(--amber);
  font-weight:900;font-size:22px;transform:rotate(45deg);
}
.ws-crest span{transform:rotate(-45deg);}
.ws-title{font-size:26px;font-weight:900;color:var(--ink);letter-spacing:-0.02em;}
.ws-sub{font-size:11px;letter-spacing:.34em;color:var(--khaki-dim);margin-top:4px;}
.ws-desc{font-size:13.5px;line-height:1.7;color:var(--ink-soft);margin-top:18px;}

.ws-card{
  border:1.5px solid var(--paper-line);background:var(--paper-2);
  padding:26px 20px 20px;text-align:center;margin-bottom:12px;
  border-top:4px solid var(--khaki-dim);
}
.ws-card-enlisted{border-top-color:var(--green-ok);}
.ws-card-officer{border-top-color:var(--amber);}
.ws-ic{font-size:40px;line-height:1;margin-bottom:10px;}
.ws-ct{font-size:20px;font-weight:900;color:var(--ink);}
.ws-cs{font-size:11.5px;letter-spacing:.06em;color:var(--ink-soft);margin-top:4px;}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
