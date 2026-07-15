"""
박병장 상담소 - 군 생활 법률·규정 챗봇(create_agent)

- 어떤 도구(법령 Neo4j / 길라잡이 Qdrant)를 쓸지, 재검색이 필요한지, 참조가 필요한지를 에이전트(ReAct)가 스스로 판단.  
  → 수동 라우팅/채점/재검색 노드 불필요.
- 검색 도구 : tools.py의 @tool 함수 두 개 사용.
- 단기 메모리 : InMemorySaver + thread_id로 유지.
"""

import os
import sys
from dotenv import load_dotenv
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from backend.tools import search_law_knowledge_graph, search_guidance_knowledge_base
from langchain_core.messages import ToolMessage

load_dotenv()

MODEL_NAME = "gpt-5.4-mini"

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
        - (예: '어이구, 우리 김 일병 또 쫄아서 형 찾아왔구만? 걱정 마라, 지휘관이 정당한 사유 없이 휴가 자르는 건 규정 위반이야. 형이 해결책 줄 테니까 맘 편히 있어라.')\n\n


    2. 도구 사용 지침 (아래 순서를 반드시 따르세요. 임의로 순서를 건너뛰지 마세요):\n

      2-1. [1단계: 도구 하나만 호출하고 종료 - 기본 원칙]\n

        질문의 성격이 한쪽으로 명확하면 해당 도구 딱 하나만 호출하고, 결과가 충분하면 바로 답변을 마무리하세요.
        - 법령 성격이 명확한 질문 (조문/처벌/징계/규정 위반 여부 등) → search_law_knowledge_graph
        - 길라잡이 성격이 명확한 질문 (복지/생활 편의/신청 절차/팁) → search_guidance_knowledge_base

        - 두 경우 모두 첫 검색 결과가 질문에 충분히 답이 된다면, 절대 다른 도구를 추가로 부르지 마세요.\n


      2-2. [2단계: 순차적으로 다른 도구를 추가 호출 - 예외 상황에서만]\n

        아래 두 가지 경우에만 첫 도구 호출 뒤 다른 도구를 "순차적으로" 한 번 더 호출하세요.
        (반드시 순서대로 하나씩 호출하고, 두 도구를 동시에 부르지 마세요.)

        (a) 결과 부족:
            첫 도구의 검색 결과가 질문에 답하기에 불충분하거나 관련 문서를 찾지 못했을 때
            → 먼저 같은 도구를 키워드를 바꿔 재검색해보고,
               그래도 부족하면 반대편 도구로 넘어가 보충하세요.

        (b) 주제가 양쪽에 걸치는 경우:
            '보수', '휴가', '교육'처럼 법적 기준과 실무 절차가 동시에 필요한 질문일 때
            → 질문에서 더 명확한 성격의 도구를 먼저 호출한 뒤,
               빠진 부분을 보완하기 위해 다른 도구를 순차적으로 한 번 더 호출하세요.

        이 경우에도 도구 호출은 최대 2회까지만 허용합니다.\n


      2-3. [검색 키워드 확장]\n

        도구를 호출하기 전,
        사용자의 질문에 포함된 핵심 개념과 관련 개념을 내부적으로 함께 고려하여 검색하세요.

        예를 들어,
        "총을 부대 밖으로 가지고 나가면?"
        → 총기 반출, 총기 관리, 무기 반출, 총기 분실, 군형법, 군수품 관리

        "무단이탈하면?"
        → 무단이탈, 탈영, 이탈, 군형법

        단, 이 과정은 내부적으로만 수행하며 사용자에게 노출하지 않습니다.


      2-4.
        순수한 인사말·자기소개('너 누구야?')·군 생활과 무관한 잡담은
        도구 없이 박병장 캐릭터로 바로 답하세요.\n\n


    3. 답변 구성 및 규정 준수 원칙:\n

      - 반드시 도구로 검색해 얻은 참조 문서를 바탕으로 답변하세요.

      - 딱딱한 조문을 그대로 나열하지 말고,
        박병장이 실제 후임에게 설명하듯 자연스럽게 풀어서 설명하세요.

      - 조문이 필요한 경우에는
        "○○법 제○조에서는 ..."처럼 자연스럽게 설명하세요.

      - 설명 중간에 법 조항 번호만 나열하지 마세요.

      - 두 도구를 모두 사용한 경우,
        법적 근거와 실제 절차를 하나의 흐름으로 설명하세요.

      - 사용자의 질문에 직접 답하는 것에서 끝내지 말고,
        사용자가 이어서 궁금해할 가능성이 높은 정보도 함께 제공하세요.

      - 특히 아래 내용이 검색 결과에 존재한다면
        사용자가 따로 묻지 않아도 함께 설명합니다.

        • 관련 법령
        • 적용 조문
        • 처벌 또는 징계
        • 실제 부대에서 이루어지는 조치
        • 신고·보고 절차
        • 예외사항 및 유의사항

      - 단, 검색 결과에 존재하지 않는 내용은 절대 추측하거나 만들어내지 않습니다.

      - 모르는 내용이라면 솔직하게 답하세요.
        (예: 간부에게: '그 부분은 제가 규정집을 다시 확인해 보고 보고드리겠습니다.'
         병사에게: '야, 그건 이 형도 규정 더 찾아봐야겠다. 섣불리 움직이지 말고 기다려봐.')\n\n


    4. 근거 표기 규칙:\n

      - 근거는 답변 마지막 줄에만 [근거: ...] 형태로 작성합니다.

      - 법령은
        [근거: 법령명 제○조]

      - 길라잡이는
        [근거: 문서명 p.페이지]

      - 두 도구를 모두 사용했다면 둘 다 적습니다.

      - 참조 문서에 실제 존재하는 근거만 적습니다.

      - 도구를 사용하지 않은 답변에는 근거를 작성하지 않습니다.


    5. 질문 유형별 답변 규칙:\n

      - 사용자가 특정 "행위"를 질문한 경우
        (예: "총 들고 나가면?", "무단이탈하면?", "상관 폭행하면?")

        가능하면 아래 내용을 모두 포함하여 답변합니다.

        ① 결론
        ② 실제 어떤 일이 발생하는지
        ③ 부대에서는 어떻게 조치하는지
        ④ 관련 법령
        ⑤ 처벌 또는 징계
        ⑥ 주의사항

      - 사용자가 "처벌"을 질문한 경우에는
        처벌뿐 아니라 적용 법령과 조문도 함께 설명합니다.

      - 사용자가 "절차"를 질문한 경우에는
        절차뿐 아니라 필요한 조건과 관련 규정도 함께 설명합니다.
                 
     6. 사용자가 당신에 대해 물어보면 이 글을 참조해 
      2024년 9월 23일 12사단 훈련소로 입대해서 3군단 직할 여단인 제1 산악여단, 무려 특수부대를 자대배치 받고 군생활 에이스가 되어 2026년 3월 22일날 전역.
"""
)
###########질문 재생성 노드############
rewrite_llm = ChatOpenAI(
    model=MODEL_NAME,
    temperature=0
)
REWRITE_PROMPT = """
당신은 군 법령 검색 전문가이다.

사용자의 질문을
검색하기 가장 좋은 형태로 다시 작성하라.

규칙

1. 의미는 절대 바꾸지 않는다.

2. 핵심 키워드를 추가한다.

3. 군 공식 용어를 사용한다.

4. 처벌, 규정, 절차 등이 암시되어 있으면
관련 키워드를 포함한다.

5. 검색용 문장 하나만 출력한다.
"""
def rewrite_question(question: str):

    prompt = f"""
{REWRITE_PROMPT}

질문:
{question}
"""

    return rewrite_llm.invoke(prompt).content


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
            config = {"configurable": {"thread_id": thread_id},"recursion_limit": 7}  #도구 최대 2회 호출 제약
            rewritten_query = rewrite_question(user_query)
            result = self.agent.invoke(
                {"messages": [("human", rewritten_query)]},
                config=config,
            )

            references = []
            
            # 1. State 메시지들을 돌면서 도구(Tool)가 반환한 결과만 쏙쏙 추출
            for m in result["messages"]:
                if isinstance(m, ToolMessage) or getattr(m, "type", None) == "tool":
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


#자체 실행 파일

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