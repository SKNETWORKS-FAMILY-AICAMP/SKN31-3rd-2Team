"""
박병장 상담소 - 군 생활 법률·규정 챗봇 (StateGraph 명시적 버전)

- add_node / add_edge / add_conditional_edges로 그래프를 직접 구성
- 도구 선택 / 재검색 여부 / 답변 생성은 전부 AI(시스템 프롬프트)가 판단
- 코드가 강제하는 건 딱 하나: 도구 호출 최대 2회 하드캡 (프롬프트 규칙이 새는 경우 대비 안전장치)
- 429 rate limit 대응: tenacity로 지수 백오프 재시도
"""

import os
import sys
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_random_exponential, retry_if_exception

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
from langchain_openai import ChatOpenAI

from backend.tools import search_law_knowledge_graph, search_guidance_knowledge_base

load_dotenv()

# =====================================================================
# 설정
# =====================================================================
MODEL_NAME = "gpt-5.4-mini"
MAX_TOOL_CALLS = 2   # 도구 호출 최대 횟수 하드캡 (프롬프트 규칙 "최대 2회"를 코드로도 강제)

SYSTEM_PROMPT = (""" 
    당신은 군 생활의 모든 법률, 규정, 꼼수까지 마스터한 만렙 에이스 선임 '박병장'입니다.
    당신은 질문자의 신분(간부 vs 병사)에 따라 태도를 180도 바꾸는 완벽한 처세술을 보여주어야 합니다.\n\n
    1. 대상별 완벽한 태세 전환 규칙:\n
      1-1. [질문자가 '장교·부사관 등 간부'인 경우]: 눈빛부터 고쳐 잡고 철저한 격식과 '다나까'를 씁니다.
        - 에이스답게 기에 눌리지 않는 당당함과 여유를 풍기며 든든한 조력자 역할을 합니다. 
        - 말끝은 주로 '~지 말입니다', '~이지 않습니까?'를 씁니다.
        (예: '그 규정은 이번에 개정되어서 그렇게 처리하시면 감사관실에 털립니다. 제가 깔끔하게 짚어드리겠습니다.')\n
      1-2. [질문자가 '병사'인 경우]: 전부 내 친동생이자 직속 후임입니다. 격식 따윈 버리고 아주 편하게 반말과 '하오체'를 섞어 씁니다.
        - 귀찮은 척 틱틱거리지만 속은 엄청 깊은 '츤데레 형'입니다.
        - 말끝은 주로 '~지', '~냐?', '~마라'를 씁니다.
        - (예: '어이구, 우리 김 일병 또 쫄아서 형 찾아왔구만? 걱정 마라, 지휘관이 정당한 사유 없이 휴가 자르는 건 규정 위반이야. 형이 해결책 줄 테니까 맘 편히 있어라.')\n\n

    2. 도구 사용 지침 (아래 순서를 반드시 따르세요. 임의로 순서를 건너뛰지 마세요):\n

      2-1. [1단계: 도구 하나만 호출하고 종료 - 기본 원칙]\n
        질문의 성격이 한쪽으로 명확하면 해당 도구 딱 하나만 호출하고, 결과가 충분하면 바로 답변을 마무리하세요.
        - 법령 성격이 명확한 질문 (조문/처벌/징계/규정 위반 여부 등) → search_law_knowledge_graph
          (예: '무단이탈 처벌 수위', '지시 불이행 시 징계', '초임호봉 획정 법적 기준')
        - 길라잡이 성격이 명확한 질문 (복지/생활 편의/신청 절차/팁) → search_guidance_knowledge_base
          (예: '휴가 갈 때 기차 할인 받는 법', '군대에서 자격증 공부하는 법', '전역 후 사회적응 프로그램')
        - 두 경우 모두 첫 검색 결과가 질문에 충분히 답이 된다면, 절대 다른 도구를 추가로 부르지 마세요.\n

      2-2. [2단계: 순차적으로 다른 도구를 추가 호출 - 예외 상황에서만]\n
        아래 두 가지 경우에만 첫 도구 호출 뒤 다른 도구를 "순차적으로" 한 번 더 호출하세요.
        (반드시 순서대로 하나씩 호출하고, 두 도구를 동시에 부르지 마세요.)

        (a) 결과 부족: 첫 도구의 검색 결과가 질문에 답하기에 불충분하거나 관련 문서를 찾지 못했을 때
            → 먼저 같은 도구를 키워드를 바꿔 재검색해보고, 그래도 부족하면 반대편 도구로 넘어가 보충하세요.

        (b) 주제가 양쪽에 걸치는 경우: '보수', '휴가', '교육'처럼 법적 기준과 실무 절차가
            동시에 필요한 질문일 때
            (예: '휴가 규정이랑 신청 방법 둘 다 알려줘', '보수 인상 법적 근거랑 실제 지급 절차 알려줘',
                '교육 이수 의무 규정이랑 신청 방법 알려줘')
            → 질문에서 더 명확한 성격의 도구를 먼저 호출한 뒤, 빠진 부분을 보완하기 위해
              다른 도구를 순차적으로 한 번 더 호출해서 두 관점(법적 근거 + 실무 절차)을 모두 담아 답변하세요.

        이 두 경우라도 도구 호출은 최대 2회로 제한하고, 그 이상 반복 재검색하지 마세요.\n

      2-3. 순수한 인사말·자기소개('너 누구야?')·군 생활과 무관한 잡담은 도구 없이 박병장 캐릭터로 바로 답하세요.\n\n
                 
    3. 답변 구성 및 규정 준수 원칙:\n
      - 반드시 도구로 검색해 얻은 참조 문서 내용을 바탕으로 답변하되, 딱딱한 조문은 박병장이 상황에 맞게
      -풀어서 설명하는 것처럼 자연스럽게 녹여내세요.\n
      - 설명 중간에 법 조항 번호를 나열하며 훈수 두지 마세요.\n
      - 두 도구를 모두 사용한 경우, 법적 근거와 실무 절차를 자연스럽게 하나의 흐름으로 엮어서 설명하세요.
        (예: '법적으로는 이렇게 보장돼 있고, 실제로 신청은 이렇게 하면 돼' 식의 흐름)\n
      - 검색으로 얻은 참조 문서에 없는 내용을 상상으로 지어내거나 가짜 규정을 만들어서는 절대 안 됩니다. 
      - 모르는 내용이라면 솔직하게 답하세요.
        (예: 간부에게: '그 부분은 제가 규정집을 다시 확인해 보고 보고드리겠습니다.' / 
        병사에게: '야, 그건 이 형도 규정 더 찾아봐야겠다. 섣불리 움직이지 말고 기다려봐.')\n\n
                 
    4. 근거 표기 규칙:\n
      - 근거는 답변 맨 마지막 줄에만 [근거: ...] 형태로 딱 한 줄만 덧붙입니다. 참조 문서에 실제로 등장한 것만 적고,
    없는 법령·조문을 지어내거나 'O조'처럼 번호를 비워두지 마세요.\n
      - 근거는 [근거: 법령명 제○조] 형태로, 참조 문서에 표기된 법령명과 조 번호를 그대로 씁니다. (예: [근거: 군인 징계령 제8조])\n
      - 길라잡이(search_guidance_knowledge_base) 근거는 [근거: 문서명 p.페이지] 형태로 씁니다.\n
      - 두 도구를 모두 쓴 경우 근거도 둘 다 적으세요. (예: [근거: 군인 징계령 제8조 / 2026 초급간부 길라잡이 p.12])\n
      - 인사·잡담 등 도구를 쓰지 않은 답변에는 [근거: ...] 줄을 붙이지 마세요."""
)

# =====================================================================
# 429 재시도 유틸
# =====================================================================
def _is_rate_limit_error(exc: BaseException) -> bool:
    msg = str(exc)
    return "429" in msg or "rate_limit" in msg.lower()


rate_limit_retry = retry(
    retry=retry_if_exception(_is_rate_limit_error),
    wait=wait_random_exponential(min=1, max=60),
    stop=stop_after_attempt(6),
    reraise=True,
)


@rate_limit_retry
def safe_invoke(llm: ChatOpenAI, messages: list) -> AIMessage:
    """429 발생 시 지수 백오프로 자동 재시도하는 LLM 호출 wrapper."""
    return llm.invoke(messages)


@rate_limit_retry
def safe_tool_invoke(tool, args: dict):
    """도구 자체가 내부적으로 LLM/API를 호출해 429가 날 수 있는 경우 대비."""
    return tool.invoke(args)


# =====================================================================
# LLM 인스턴스
# =====================================================================
llm = ChatOpenAI(model=MODEL_NAME, temperature=0)

tools = [search_law_knowledge_graph, search_guidance_knowledge_base]
tools_by_name = {t.name: t for t in tools}
llm_with_tools = llm.bind_tools(tools)


# =====================================================================
# State
# =====================================================================
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    question: str
    references: list[str]
    tool_call_count: int   # 도구 호출 하드캡을 위한 카운터


# =====================================================================
# 노드
# =====================================================================
def agent_node(state: AgentState) -> dict:
    try:
        response = safe_invoke(llm_with_tools, state["messages"])
    except Exception as e:
        print(f"[Agent Warning] 최종 재시도 실패: {e}")
        response = AIMessage(content="죄송합니다, 지금 요청이 몰려서 답변이 지연되고 있습니다. 잠시 후 다시 시도해주세요.")
    return {"messages": [response]}


def tools_node(state: AgentState) -> dict:
    """도구 실행. 판단(어떤 도구/몇 번)은 전부 AI가 하고, 여기선 실행만 담당."""
    last_msg: AIMessage = state["messages"][-1]

    tool_messages = []
    new_refs = []
    for call in last_msg.tool_calls:
        tool = tools_by_name[call["name"]]
        try:
            result = safe_tool_invoke(tool, call["args"])
        except Exception as e:
            print(f"[Tool Warning] {call['name']} 실패: {e}")
            result = "(검색 실패 - 잠시 후 다시 시도 필요)"

        result_str = str(result)
        new_refs.append(result_str)
        tool_messages.append(ToolMessage(content=result_str, tool_call_id=call["id"]))

    return {
        "messages": tool_messages,
        "references": state.get("references", []) + new_refs,
        "tool_call_count": state.get("tool_call_count", 0) + len(last_msg.tool_calls),
    }


# =====================================================================
# 라우팅
# =====================================================================
def route_after_agent(state: AgentState) -> str:
    last_msg = state["messages"][-1]
    has_tool_calls = bool(getattr(last_msg, "tool_calls", None))

    if not has_tool_calls:
        return END

    # 하드캡: 이미 MAX_TOOL_CALLS만큼 호출했으면 더 이상 도구로 안 보내고
    # AI에게 "그만 부르고 지금까지 결과로 답변해라"는 신호만 주고 종료 라우팅
    if state.get("tool_call_count", 0) >= MAX_TOOL_CALLS:
        print(f"⚠️ 도구 호출 {MAX_TOOL_CALLS}회 도달 — 추가 호출 무시하고 종료")
        return END

    return "tools"


# =====================================================================
# 그래프 조립
# =====================================================================
graph_builder = StateGraph(AgentState)

graph_builder.add_node("agent", agent_node)
graph_builder.add_node("tools", tools_node)

graph_builder.add_edge(START, "agent")
graph_builder.add_conditional_edges(
    "agent",
    route_after_agent,
    {"tools": "tools", END: END},
)
graph_builder.add_edge("tools", "agent")

checkpointer = InMemorySaver()
compiled_graph = graph_builder.compile(checkpointer=checkpointer)


# =====================================================================
# 챗봇 클래스 (인터페이스 동일 유지: bot.ask(...))
# =====================================================================
class LangGraphChatbot:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.graph = compiled_graph

    def ask(self, user_query: str, thread_id: str = "default-thread") -> tuple[list[str], str]:
        config = {"configurable": {"thread_id": thread_id}}
        initial_state = {
            "messages": [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_query)],
            "question": user_query,
            "references": [],
            "tool_call_count": 0,
        }
        result = self.graph.invoke(initial_state, config=config)

        references = result.get("references", [])
        final_response = result["messages"][-1].content

        if self.verbose:
            print("\n" + "=" * 60)
            print("📄 [참조 문서 목록 (References)]")
            print("=" * 60)
            if references:
                for i, ref in enumerate(references, 1):
                    print(f"[{i}번째 검색 결과]\n{ref}")
                    print("-" * 40)
            else:
                print("(참조한 문서 없음 - 잡담 또는 자체 답변)")
            print("\n" + "=" * 60)
            print("✨ [최종 Response]")
            print("=" * 60)
            print(final_response)
            print("=" * 60 + "\n")

        return references, final_response


def main():
    bot = LangGraphChatbot()

    print("\n💬 군 생활 법률·규정 챗봇 (박병장) - [StateGraph 명시 버전]입니다.")
    print("종료하려면 exit를 입력하세요.\n")

    thread_id = "console-user-1"
    while True:
        user_input = input("🔍 질문: ").strip()
        if user_input.lower() in {"exit", "quit"}:
            break
        if not user_input:
            continue

        references, answer = bot.ask(user_query=user_input, thread_id=thread_id)


if __name__ == "__main__":
    main()