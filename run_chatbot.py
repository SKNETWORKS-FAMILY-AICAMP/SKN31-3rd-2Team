import os
from typing import TypedDict, List, Dict, Any
from openai import OpenAI
from neo4j import GraphDatabase
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

from retriever import Neo4jRetriever, CHAT_MODEL

load_dotenv()

TARGET_DATABASE = "lawdb"

# 1. 그래프 상태(State) 정의
class ChatBotState(TypedDict):
    user_query: str
    top_k: int
    search_data: List[Dict[str, Any]]
    context_text: str
    answer: str

# 2. 노드에 사용할 의존성 객체들을 감싸는 클래스 또는 환경 설정
class LangGraphChatbot:
    def __init__(self, client: OpenAI, retriever: Neo4jRetriever):
        self.client = client
        self.retriever = retriever
        self.workflow = self._build_graph()

    def _build_context(self, search_data: list[dict]) -> str:
        blocks = [
            f"[{r.get('id', '')}] {r.get('name', '')}\n{r.get('description', '')}"
            for r in search_data
        ]
        return "\n\n---\n\n".join(blocks)

    # [Node 1] 검색 단계
    def retrieve_node(self, state: ChatBotState) -> Dict[str, Any]:
        user_query = state["user_query"]
        top_k = state.get("top_k", 3)
        
        search_data = self.retriever.retrieve(user_query, top_k=top_k)
        
        if not search_data:
            context_text = "(참조할 문서를 찾지 못했습니다.)"
        else:
            context_text = self._build_context(search_data)
            
        return {"search_data": search_data, "context_text": context_text}

    # [Node 2] 답변 생성 단계
    def generate_node(self, state: ChatBotState) -> Dict[str, Any]:
        system_prompt = (
            "당신은 초급간부와 병사를 위한 군 생활 법률·규정 안내 챗봇입니다. "
            "참조 문서 내용을 바탕으로 자연스럽게 설명하고, 조문 번호를 나열하지 마세요. "
            "근거 조문은 답변 끝에 짧게만 덧붙이세요. "
            "참조 문서에 없는 내용은 지어내지 마세요."
        )
        
        response = self.client.chat.completions.create(
            model=CHAT_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"[참조 문서]\n{state['context_text']}\n\n[질문]\n{state['user_query']}"},
            ],
        )
        return {"answer": response.choices[0].message.content}

    # 그래프 구조 조립
    def _build_graph(self):
        builder = StateGraph(ChatBotState)
        
        # 노드 추가
        builder.add_node("retrieve", self.retrieve_node)
        builder.add_node("generate", self.generate_node)
        
        # 엣지 연결 (START -> retrieve -> generate -> END)
        builder.add_edge(START, "retrieve")
        builder.add_edge("retrieve", "generate")
        builder.add_edge("generate", END)
        
        # 컴파일
        return builder.compile()

    # 실행 메서드
    def ask(self, user_query: str, top_k: int = 3) -> str:
        initial_state = {
            "user_query": user_query,
            "top_k": top_k,
            "search_data": [],
            "context_text": "",
            "answer": ""
        }
        final_state = self.workflow.invoke(initial_state)
        return final_state["answer"]


def main():
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )

    retriever = Neo4jRetriever(client=client, driver=driver, database=TARGET_DATABASE)
    
    # 랑그래프 챗봇 초기화
    bot = LangGraphChatbot(client=client, retriever=retriever)

    print("💬 [LangGraph] 군 생활 법률·규정 챗봇입니다. 종료하려면 'exit' 입력하세요.\n")

    try:
        while True:
            user_input = input("질문: ").strip()
            if user_input.lower() in {"exit", "quit"}:
                break
            if not user_input:
                continue

            answer = bot.ask(user_input)
            print(f"\n답변: {answer}\n")
    finally:
        driver.close()


if __name__ == "__main__":
    main()