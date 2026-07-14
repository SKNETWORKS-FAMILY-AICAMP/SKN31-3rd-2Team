"""
박병장 상담소 - 군 생활 법률·규정 챗봇(create_agent)

- 어떤 도구(법령 Neo4j / 길라잡이 Qdrant)를 쓸지, 재검색이 필요한지, 참조가 필요한지를 에이전트(ReAct)가 스스로 판단.  
  → 수동 라우팅/채점/재검색 노드 불필요.
- 검색 도구 : tools.py의 @tool 함수 두 개 사용.
- 단기 메모리 : InMemorySaver + thread_id로 유지.
"""

import os
from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from tools import search_law_knowledge_graph, search_guidance_knowledge_base

load_dotenv()

MODEL_NAME = "gpt-4o"

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

    2. 도구 사용 지침 (질문의 의도에 맞게 적절한 도구를 선택하되, 복합적인 질문인 경우 두 도구를 모두 활용하여 종합적인 답변을 도출하세요):
      2-1. search_law_knowledge_graph (법령 Neo4j):
        - "법적으로 맞는지", "근거 조문이 뭔지", "위반 시 처벌/징계 수위가 어떻게 되는지", "특정 법령/시행령/훈령의 제○조 내용"을 확인해야 할 때 사용합니다.
      2-2. search_guidance_knowledge_base (길라잡이 Qdrant):
        - "실제 금액이 얼마인지", "어떻게 신청/발급받는지", "어떤 혜택/시설이 있는지" 등 가이드북 성격의 실무 정보나 구체적인 절차/액수를 확인해야 할 때 사용합니다.
      2-3. 복합 질문 처리 규칙:
        - 만약 유저의 질문이 법적 근거와 실무 절차/액수(예: "2026년 병장 월급 액수와 지급 관련 법적 근거")를 동시에 요구한다면, 두 도구를 순차적으로 모두 호출하여 정보를 수집한 뒤 자연스럽게 하나의 답변으로 융합해야 합니다. 단, 완전히 무관한 도구를 무분별하게 중복 호출하는 것은 지양하세요.
                 
    3. 답변 구성 및 규정 준수 원칙:\n
      - 반드시 도구로 검색해 얻은 참조 문서 내용을 바탕으로 답변하되, 딱딱한 조문은 박병장이 상황에 맞게
      -풀어서 설명하는 것처럼 자연스럽게 녹여내세요.\n
      - 설명 중간에 법 조항 번호를 나열하며 훈수 두지 마세요.\n
      - 검색으로 얻은 참조 문서에 없는 내용을 상상으로 지어내거나 가짜 규정을 만들어서는 절대 안 됩니다. 
      - 모르는 내용이라면 솔직하게 답하세요.
        (예: 간부에게: '그 부분은 제가 규정집을 다시 확인해 보고 보고드리겠습니다.' / 
        병사에게: '야, 그건 이 형도 규정 더 찾아봐야겠다. 섣불리 움직이지 말고 기다려봐.')\n\n
                 
    4. 근거 표기 규칙:\n
      - 근거는 답변 맨 마지막 줄에만 [근거: ...] 형태로 딱 한 줄만 덧붙입니다. 참조 문서에 실제로 등장한 것만 적고,
    없는 법령·조문을 지어내거나 'O조'처럼 번호를 비워두지 마세요.\n
      - 근거는 [근거: 법령명 제○조] 형태로, 참조 문서에 표기된 법령명과 조 번호를 그대로 씁니다. (예: [근거: 군인 징계령 제8조])\n
      - 길라잡이(search_guidance_knowledge_base) 근거는 [근거: 문서명 p.페이지] 형태로 씁니다.\n
      - 인사·잡담 등 도구를 쓰지 않은 답변에는 [근거: ...] 줄을 붙이지 마세요."""
)


class LangGraphChatbot:
    """create_agent 기반 박병장 챗봇.

    도구 선택 / 재검색 / 참조 필요 여부 / 답변 생성을 에이전트가 자율 판단(ReAct)하며,
    tools.py의 @tool 두 개를 그대로 바인딩해 사용한다.
    """

    def __init__(self, model_name: str = MODEL_NAME, verbose: bool = True):
        self.verbose = verbose
        self.tools = [search_law_knowledge_graph, search_guidance_knowledge_base]
        self.checkpointer = InMemorySaver()
        self.agent = create_agent(
            model=ChatOpenAI(model=model_name, temperature=0),
            tools=self.tools,
            system_prompt=SYSTEM_PROMPT,
            checkpointer=self.checkpointer,  # thread_id 별 단기 메모리
        )

    def ask(self, user_query: str, thread_id: str = "default-thread") -> tuple[list[str], str]:
            """유저 질문을 받아 (참조문서_리스트, 최종_답변)을 반환합니다."""
            config = {"configurable": {"thread_id": thread_id}}
            result = self.agent.invoke(
                {"messages": [("human", user_query)]},
                config=config,
            )

            references = []
            
            # 1. State 메시지들을 돌면서 도구(Tool)가 반환한 결과만 쏙쏙 추출
            for m in result["messages"]:
                if getattr(m, "type", None) == "tool" or m.__class__.__name__ == "ToolMessage":
                    # 도구가 반환한 원본 텍스트 내용 저장
                    references.append(m.content)

            # 2. 가장 마지막 메시지(AI의 최종 대답) 추출
            final_response = result["messages"][-1].content

            # 3. 요청하신 프린트 로직 진행
            if self.verbose:
                print("\n" + "="*60)
                print("📄 [참조 문서 목록 (References)]")
                print("="*60)
                if references:
                    for i, ref in enumerate(references, 1):
                        print(f"[{i}번째 검색 결과]\n{ref}")
                        print("-" * 40)
                else:
                    print("(참조한 문서 없음 - 잡담 또는 자체 답변)")
                    
                print("\n" + "="*60)
                print("✨ [최종 Response]")
                print("="*60)
                print(final_response)
                print("="*60 + "\n")

            # [참조문서 리스트, 최종 답변] 구조로 리턴
            return references, final_response

def main():
    bot = LangGraphChatbot()

    print("\n💬 군 생활 법률·규정 챗봇 (박병장) - [create_agent 자율 판단 모드]입니다.")
    print("종료하려면 exit를 입력하세요.\n")

    thread_id = "console-user-1"
    while True:
        user_input = input("🔍 질문: ").strip()
        if user_input.lower() in {"exit", "quit"}:
            break
        if not user_input:
            continue

        # 함수 리턴 구조가 바뀐 것에 맞춰 unpacking 진행
        references, answer = bot.ask(user_query=user_input, thread_id=thread_id)



if __name__ == "__main__":
    main()