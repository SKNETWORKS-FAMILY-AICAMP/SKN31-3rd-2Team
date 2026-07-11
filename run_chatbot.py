import os
from typing import TypedDict, List, Dict, Any

from openai import OpenAI
from neo4j import GraphDatabase
from dotenv import load_dotenv

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
)

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import InMemorySaver

from typing_extensions import Annotated

from retriever import Neo4jRetriever, CHAT_MODEL


load_dotenv()

TARGET_DATABASE = "lawdb"


# ============================================================
# 1. LangGraph 상태 정의
# ============================================================
class ChatBotState(TypedDict, total=False):
    # 현재 사용자가 입력한 원본 질문
    user_query: str

    # 이전 대화를 참고해 다시 작성한 검색용 질문
    search_query: str

    # Neo4j 검색 개수
    top_k: int

    # Neo4j에서 가져온 검색 결과
    search_data: List[Dict[str, Any]]

    # 검색 결과를 GPT에게 전달하기 위한 문자열
    context_text: str

    # 최종 답변
    answer: str

    # 단기메모리에 저장되는 대화 기록
    messages: Annotated[List[BaseMessage], add_messages]


# ============================================================
# 2. LangGraph 챗봇 클래스
# ============================================================
class LangGraphChatbot:

    def __init__(
        self,
        client: OpenAI,
        retriever: Neo4jRetriever
    ):
        self.client = client
        self.retriever = retriever

        # RAM에 대화 상태를 저장하는 단기메모리
        self.checkpointer = InMemorySaver()

        # LangGraph 생성
        self.workflow = self._build_graph()


    # ========================================================
    # 검색된 Neo4j 데이터를 하나의 문자열로 합치는 함수
    # ========================================================
    def _build_context(
        self,
        search_data: List[Dict[str, Any]]
    ) -> str:

        blocks = []

        for result in search_data:
            article_id = result.get("id", "")
            article_name = result.get("name", "")
            description = result.get("description", "")
            score = result.get("score")

            block = (
                f"[조문 ID] {article_id}\n"
                f"[조문 제목] {article_name}\n"
                f"[조문 내용]\n{description}"
            )

            if score is not None:
                block += f"\n[유사도 점수] {score:.4f}"

            blocks.append(block)

        return "\n\n---\n\n".join(blocks)


    # ========================================================
    # BaseMessage를 OpenAI SDK 형식으로 변환
    # ========================================================
    def _convert_messages_for_openai(
        self,
        messages: List[BaseMessage]
    ) -> List[Dict[str, str]]:

        converted_messages = []

        for message in messages:

            if isinstance(message, HumanMessage):
                role = "user"

            elif isinstance(message, AIMessage):
                role = "assistant"

            else:
                # 현재 코드에서는 HumanMessage와 AIMessage만 사용
                continue

            converted_messages.append(
                {
                    "role": role,
                    "content": str(message.content)
                }
            )

        return converted_messages


    # ========================================================
    # Node 1: 검색용 질문 재작성
    # ========================================================
    def rewrite_node(
        self,
        state: ChatBotState
    ) -> Dict[str, Any]:

        user_query = state["user_query"]
        messages = state.get("messages", [])

        # 이번 질문은 ask()에서 이미 messages에 추가되므로
        # 마지막 메시지를 제외하면 이전 대화만 남는다.
        previous_messages = messages[:-1]

        # 이전 대화가 없다면 원래 질문 그대로 검색
        if not previous_messages:
            return {
                "search_query": user_query
            }

        history = self._convert_messages_for_openai(
            previous_messages
        )

        rewrite_system_prompt = """
당신은 법률·규정 검색용 질문을 재작성하는 도우미입니다.

사용자의 현재 질문이 이전 대화에 의존하는 경우,
이전 대화를 참고해서 현재 질문을 독립적으로 이해할 수 있는
명확한 검색용 질문으로 바꾸세요.

규칙:
1. 답변하지 말고 검색용 질문만 출력하세요.
2. 이전 질문의 주제, 법령명, 대상, 상황을 가능한 한 포함하세요.
3. 현재 질문이 이미 명확하면 그대로 출력하세요.
4. 이전 대화에 없는 내용을 임의로 추가하지 마세요.
5. 한 문장으로 작성하세요.
"""

        api_messages = [
            {
                "role": "system",
                "content": rewrite_system_prompt
            }
        ]

        api_messages.extend(history)

        api_messages.append(
            {
                "role": "user",
                "content": (
                    f"현재 질문을 검색용 질문으로 재작성하세요.\n\n"
                    f"현재 질문: {user_query}"
                )
            }
        )

        response = self.client.chat.completions.create(
            model=CHAT_MODEL,
            temperature=0,
            messages=api_messages
        )

        search_query = response.choices[0].message.content

        if not search_query:
            search_query = user_query
        else:
            search_query = search_query.strip()

        return {
            "search_query": search_query
        }


    # ========================================================
    # Node 2: Neo4j 문서 검색
    # ========================================================
    def retrieve_node(
        self,
        state: ChatBotState
    ) -> Dict[str, Any]:

        # 원본 질문이 아닌 재작성된 질문으로 검색
        search_query = state.get(
            "search_query",
            state["user_query"]
        )

        top_k = state.get("top_k", 3)

        search_data = self.retriever.retrieve(
            user_query=search_query,
            top_k=top_k
        )

        if not search_data:
            context_text = (
                "현재 질문과 관련된 참조 조문을 "
                "Neo4j에서 찾지 못했습니다."
            )

        else:
            context_text = self._build_context(search_data)

        return {
            "search_data": search_data,
            "context_text": context_text
        }


    # ========================================================
    # Node 3: 최종 답변 생성
    # ========================================================
    def generate_node(
        self,
        state: ChatBotState
    ) -> Dict[str, Any]:

        system_prompt = """
당신은 초급간부와 병사를 위한 군 생활 법률·규정 안내 챗봇입니다.

답변 규칙:
1. 제공된 참조 조문을 우선 근거로 답변하세요.
2. 사용자가 이해하기 쉬운 표현으로 설명하세요.
3. 답변 본문에서 조문 번호를 지나치게 나열하지 마세요.
4. 근거 조문은 답변 마지막에 짧게 정리하세요.
5. 참조 문서에서 확인할 수 없는 내용은 지어내지 마세요.
6. 근거가 부족한 경우 확인하기 어렵다고 명확히 말하세요.
7. 이전 대화의 맥락을 참고해서 후속 질문에 답하세요.
8. 법률적 판단이 필요한 문제는 담당 간부나 법무 담당자에게
   확인이 필요하다는 점을 안내하세요.
"""

        all_messages = state.get("messages", [])

        # 마지막 HumanMessage는 현재 질문이다.
        # 아래에서 참조 문서와 함께 다시 넣으므로 제외한다.
        previous_messages = all_messages[:-1]

        api_messages = [
            {
                "role": "system",
                "content": system_prompt
            }
        ]

        api_messages.extend(
            self._convert_messages_for_openai(
                previous_messages
            )
        )

        current_prompt = f"""
[검색에 사용한 질문]
{state.get("search_query", state["user_query"])}

[참조 조문]
{state["context_text"]}

[사용자의 현재 질문]
{state["user_query"]}
"""

        api_messages.append(
            {
                "role": "user",
                "content": current_prompt
            }
        )

        response = self.client.chat.completions.create(
            model=CHAT_MODEL,
            temperature=0,
            messages=api_messages
        )

        answer = response.choices[0].message.content

        if not answer:
            answer = "답변을 생성하지 못했습니다."

        # HumanMessage는 ask()에서 이미 저장했다.
        # 여기서는 AI 답변만 messages에 추가한다.
        return {
            "answer": answer,
            "messages": [
                AIMessage(content=answer)
            ]
        }


    # ========================================================
    # LangGraph 구조 생성
    # ========================================================
    def _build_graph(self):

        builder = StateGraph(ChatBotState)

        # 노드 추가
        builder.add_node(
            "rewrite",
            self.rewrite_node
        )

        builder.add_node(
            "retrieve",
            self.retrieve_node
        )

        builder.add_node(
            "generate",
            self.generate_node
        )

        # 실행 순서
        builder.add_edge(
            START,
            "rewrite"
        )

        builder.add_edge(
            "rewrite",
            "retrieve"
        )

        builder.add_edge(
            "retrieve",
            "generate"
        )

        builder.add_edge(
            "generate",
            END
        )

        # checkpointer를 연결해야 상태가 저장된다.
        return builder.compile(
            checkpointer=self.checkpointer
        )


    # ========================================================
    # 사용자 질문 실행
    # ========================================================
    def ask(
        self,
        user_query: str,
        top_k: int = 3,
        thread_id: str = "default-thread"
    ) -> str:

        # thread_id가 같으면 이전 대화 상태를 이어간다.
        config = {
            "configurable": {
                "thread_id": thread_id
            }
        }

        # 기존 상태를 전부 초기화하지 않는다.
        # 이번 실행에서 바뀌는 값만 전달한다.
        input_state = {
            "user_query": user_query,
            "top_k": top_k,

            # 이번 질문을 단기메모리에 먼저 추가
            "messages": [
                HumanMessage(content=user_query)
            ]
        }

        final_state = self.workflow.invoke(
            input_state,
            config=config
        )

        return final_state["answer"]


# ============================================================
# 3. 프로그램 실행
# ============================================================
def main():

    api_key = os.getenv("OPENAI_API_KEY")
    neo4j_uri = os.getenv("NEO4J_URI")
    neo4j_username = os.getenv("NEO4J_USERNAME")
    neo4j_password = os.getenv("NEO4J_PASSWORD")

    if not api_key:
        raise ValueError(
            ".env 파일에 OPENAI_API_KEY가 없습니다."
        )

    if not neo4j_uri:
        raise ValueError(
            ".env 파일에 NEO4J_URI가 없습니다."
        )

    if not neo4j_username:
        raise ValueError(
            ".env 파일에 NEO4J_USERNAME이 없습니다."
        )

    if not neo4j_password:
        raise ValueError(
            ".env 파일에 NEO4J_PASSWORD가 없습니다."
        )

    client = OpenAI(
        api_key=api_key
    )

    driver = GraphDatabase.driver(
        neo4j_uri,
        auth=(
            neo4j_username,
            neo4j_password
        )
    )

    retriever = Neo4jRetriever(
        client=client,
        driver=driver,
        database=TARGET_DATABASE
    )

    bot = LangGraphChatbot(
        client=client,
        retriever=retriever
    )

    print(
        "💬 군 생활 법률·규정 챗봇입니다.\n"
        "종료하려면 exit를 입력하세요.\n"
    )

    # 이 프로그램을 실행한 동안 동일한 대화방으로 사용
    thread_id = "console-user-1"

    try:
        while True:

            user_input = input("질문: ").strip()

            if user_input.lower() in {
                "exit",
                "quit"
            }:
                break

            if not user_input:
                continue

            answer = bot.ask(
                user_query=user_input,
                top_k=3,
                thread_id=thread_id
            )

            print(f"\n답변: {answer}\n")

    finally:
        driver.close()


if __name__ == "__main__":
    main()