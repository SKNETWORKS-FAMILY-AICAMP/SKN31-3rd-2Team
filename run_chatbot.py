import os
from typing import TypedDict, List, Dict, Any, Literal, Optional

from openai import OpenAI
from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from dotenv import load_dotenv

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from typing_extensions import Annotated
from langgraph.graph.message import add_messages

from graphdb_retriever import Neo4jRetriever, CHAT_MODEL
from vectordb_retriever import QdrantRetriever

load_dotenv()

TARGET_DATABASE = "lawdb"
QDRANT_COLLECTION = "GUIDANCE"

RetrieverType = Literal["neo4j", "qdrant"]

REWRITE_PROMPT = """당신은 법률·규정 검색용 질문을 재작성하는 도우미입니다.
사용자의 현재 질문이 이전 대화에 의존하는 경우, 이전 대화를 참고해서 현재 질문을
독립적으로 이해할 수 있는 명확한 검색용 질문으로 바꾸세요.

규칙:
1. 답변하지 말고 검색용 질문만 출력하세요.
2. 이전 질문의 주제, 법령명, 대상, 상황을 가능한 한 포함하세요.
3. 현재 질문이 이미 명확하면 그대로 출력하세요.
4. 이전 대화에 없는 내용을 임의로 추가하지 마세요.
5. 한 문장으로 작성하세요."""

GENERATE_PROMPT = (
    "당신은 군 생활의 모든 법률, 규정, 꼼수까지 마스터한 만렙 에이스 선임 '박병장'입니다. "
    "당신은 질문자의 신분(간부 vs 병사)에 따라 태도를 180도 바꾸는 완벽한 처세술을 보여주어야 합니다.\n\n"
    "1. 대상별 완벽한 태세 전환 규칙:\n"
    "- [질문자가 '장교·부사관 등 간부'인 경우]: 눈빛부터 고쳐 잡고 철저한 격식과 '다나까'를 씁니다. "
    "에이스답게 기에 눌리지 않는 당당함과 여유를 풍기며 든든한 조력자 역할을 합니다. "
    "말끝은 주로 '~지 말입니다', '~이지 않습니까?'를 씁니다. "
    "(예: '소대장님, 그 규정은 이번에 개정되어서 그렇게 처리하시면 감사관실에 털립니다. 제가 깔끔하게 짚어드리겠습니다.')\n"
    "- [질문자가 '병사'인 경우]: 전부 내 친동생이자 직속 후임입니다. 격식 따윈 버리고 아주 편하게 반말과 '하오체'를 섞어 씁니다. "
    "귀찮은 척 틱틱거리지만 속은 엄청 깊은 '츤데레 형'입니다. "
    "말끝은 주로 '~지', '~냐?', '~마라'를 씁니다. "
    "(예: '어이구, 우리 김 일병 또 쫄아서 형 찾아왔구만? 걱정 마라, 지휘관이 정당한 사유 없이 휴가 자르는 건 규정 위반이야. 형이 해결책 줄 테니까 맘 편히 있어라.')\n\n"
    "2. 답변 구성 및 규정 준수 원칙:\n"
    "- 반드시 제공된 참조 문서 내용을 바탕으로 답변하되, 딱딱한 조문은 박병장이 상황에 맞게 풀어서 설명하는 것처럼 자연스럽게 녹여내세요.\n"
    "- 설명 중간에 법 조항 번호를 나열하며 훈수 두지 마세요.\n"
    "- 대신, 법적 근거는 답변 맨 마지막 줄에만 [근거: 군인사법 제O조] 또는 [근거: 부대관리훈령 제O조] 형태로 깔끔하게 딱 한 줄만 덧붙이세요.\n"
    "- 참조 문서에 없는 내용을 상상으로 지어내거나 가짜 규정을 만들어서는 절대 안 됩니다. 모르는 내용이라면 솔직하게 답하세요. "
    "(간부에게: '중대장님, 그 부분은 제가 규정집을 다시 확인해 보고 보고드리겠습니다.' / 병사에게: '야, 그건 이 형도 규정 더 찾아봐야겠다. 섣불리 움직이지 말고 기다려봐.')"
)


class ChatBotState(TypedDict, total=False):
    user_query: str
    search_query: str
    top_k: int
    search_data: List[Dict[str, Any]]
    context_text: str
    answer: str
    messages: Annotated[List[BaseMessage], add_messages]


class LangGraphChatbot:
    """retriever_type("neo4j" 또는 "qdrant")에 맞는 retriever를 받아서 동작하는 챗봇.
    두 retriever 모두 retrieve(user_query, top_k) 인터페이스가 동일하므로,
    검색 자체는 공통 코드로 처리하고 payload 구조가 다른 부분(context 조립)만 분기한다."""

    def __init__(self, client: OpenAI, retriever, retriever_type: RetrieverType):
        self.client = client
        self.retriever = retriever
        self.retriever_type = retriever_type
        self.checkpointer = InMemorySaver()
        self.workflow = self._build_graph()

    # ---------- helpers ----------
    def _build_context_neo4j(self, search_data: List[Dict[str, Any]]) -> str:
        blocks = []
        for r in search_data:
            block = (
                f"[조문 ID] {r.get('id', '')}\n"
                f"[조문 제목] {r.get('name', '')}\n"
                f"[조문 내용]\n{r.get('description', '')}"
            )
            if r.get("score") is not None:
                block += f"\n[유사도 점수] {r['score']:.4f}"
            blocks.append(block)
        return "\n\n---\n\n".join(blocks)

    def _build_context_qdrant(self, search_data: List[Dict[str, Any]]) -> str:
        blocks = []
        for r in search_data:
            chunk_type = r.get("type", "text")
            header = f"[문서] {r.get('doc_name', '')} / [페이지] {r.get('page', '')} / [유형] {chunk_type}"

            if chunk_type == "table":
                body = (
                    f"[표 요약]\n{r.get('summary', '')}\n\n"
                    f"[원본 표]\n{r.get('table_markdown', '')}"
                )
            elif chunk_type == "image":
                body = (
                    f"[이미지 설명]\n{r.get('caption', '')}\n"
                    f"[이미지 경로] {r.get('image_path', '')}"
                )
            else:
                body = f"[본문]\n{r.get('content', r.get('text', ''))}"

            block = f"{header}\n{body}"
            if r.get("score") is not None:
                block += f"\n[유사도 점수] {r['score']:.4f}"
            blocks.append(block)
        return "\n\n---\n\n".join(blocks)

    def _build_context(self, search_data: List[Dict[str, Any]]) -> str:
        if self.retriever_type == "qdrant":
            return self._build_context_qdrant(search_data)
        return self._build_context_neo4j(search_data)

    def _to_openai_messages(self, messages: List[BaseMessage]) -> List[Dict[str, str]]:
        role_map = {HumanMessage: "user", AIMessage: "assistant"}
        return [
            {"role": role_map[type(m)], "content": str(m.content)}
            for m in messages if type(m) in role_map
        ]

    def _chat(self, system_prompt: str, history: List[Dict[str, str]], user_content: str) -> str:
        messages = [{"role": "system", "content": system_prompt}, *history,
                    {"role": "user", "content": user_content}]
        response = self.client.chat.completions.create(
            model=CHAT_MODEL, temperature=0, messages=messages
        )
        return (response.choices[0].message.content or "").strip()

    # ---------- nodes ----------
    def rewrite_node(self, state: ChatBotState) -> Dict[str, Any]:
        user_query = state["user_query"]
        previous_messages = state.get("messages", [])[:-1]

        if not previous_messages:
            return {"search_query": user_query}

        history = self._to_openai_messages(previous_messages)
        search_query = self._chat(
            REWRITE_PROMPT, history,
            f"현재 질문을 검색용 질문으로 재작성하세요.\n\n현재 질문: {user_query}"
        )
        return {"search_query": search_query or user_query}

    def retrieve_node(self, state: ChatBotState) -> Dict[str, Any]:
        search_query = state.get("search_query", state["user_query"])
        top_k = state.get("top_k", 3)
        search_data = self.retriever.retrieve(user_query=search_query, top_k=top_k)

        source_name = "Qdrant" if self.retriever_type == "qdrant" else "Neo4j"
        context_text = (
            self._build_context(search_data) if search_data
            else f"현재 질문과 관련된 참조 문서를 {source_name}에서 찾지 못했습니다."
        )
        return {"search_data": search_data, "context_text": context_text}

    def generate_node(self, state: ChatBotState) -> Dict[str, Any]:
        previous_messages = state.get("messages", [])[:-1]
        history = self._to_openai_messages(previous_messages)

        current_prompt = (
            f"[검색에 사용한 질문]\n{state.get('search_query', state['user_query'])}\n\n"
            f"[참조 문서]\n{state['context_text']}\n\n"
            f"[사용자의 현재 질문]\n{state['user_query']}"
        )

        answer = self._chat(GENERATE_PROMPT, history, current_prompt) or "답변을 생성하지 못했습니다."

        return {"answer": answer, "messages": [AIMessage(content=answer)]}

    # ---------- graph ----------
    def _build_graph(self):
        builder = StateGraph(ChatBotState)
        builder.add_node("rewrite", self.rewrite_node)
        builder.add_node("retrieve", self.retrieve_node)
        builder.add_node("generate", self.generate_node)

        builder.add_edge(START, "rewrite")
        builder.add_edge("rewrite", "retrieve")
        builder.add_edge("retrieve", "generate")
        builder.add_edge("generate", END)

        return builder.compile(checkpointer=self.checkpointer)

    # ---------- public API ----------
    def ask(self, user_query: str, top_k: int = 3, thread_id: str = "default-thread") -> str:
        config = {"configurable": {"thread_id": thread_id}}
        input_state = {
            "user_query": user_query,
            "top_k": top_k,
            "messages": [HumanMessage(content=user_query)],
        }
        final_state = self.workflow.invoke(input_state, config=config)
        return final_state["answer"]


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f".env 파일에 {name}이(가) 없습니다.")
    return value


def _select_retriever_type() -> RetrieverType:
    print("사용할 retriever를 선택하세요.")
    print("  1) Neo4j (조문 그래프 검색)")
    print("  2) Qdrant (PDF 텍스트/표/이미지 벡터 검색)")
    while True:
        choice = input("번호 입력 (1 또는 2): ").strip()
        if choice == "1":
            return "neo4j"
        if choice == "2":
            return "qdrant"
        print("잘못된 입력입니다. 1 또는 2를 입력해주세요.")


def _build_neo4j_retriever(client: OpenAI):
    neo4j_uri = _require_env("NEO4J_URI")
    neo4j_username = _require_env("NEO4J_USERNAME")
    neo4j_password = _require_env("NEO4J_PASSWORD")
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_username, neo4j_password))
    return Neo4jRetriever(client=client, driver=driver, database=TARGET_DATABASE), driver


def _build_qdrant_retriever(client: OpenAI):
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_api_key = os.getenv("QDRANT_API_KEY") or None
    collection_name = os.getenv("QDRANT_COLLECTION", QDRANT_COLLECTION)
    qdrant_client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    return QdrantRetriever(client=client, qdrant=qdrant_client, collection_name=collection_name), None


def main():
    api_key = _require_env("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key)

    retriever_type = _select_retriever_type()

    driver: Optional[Any] = None
    if retriever_type == "neo4j":
        retriever, driver = _build_neo4j_retriever(client)
    else:
        retriever, driver = _build_qdrant_retriever(client)

    bot = LangGraphChatbot(client=client, retriever=retriever, retriever_type=retriever_type)

    source_label = "Neo4j" if retriever_type == "neo4j" else "Qdrant"
    print(f"\n💬 군 생활 법률·규정 챗봇 (박병장) - [{source_label} 검색 모드]입니다.")
    print("종료하려면 exit를 입력하세요.\n")
    thread_id = "console-user-1"

    try:
        while True:
            user_input = input("질문: ").strip()
            if user_input.lower() in {"exit", "quit"}:
                break
            if not user_input:
                continue

            answer = bot.ask(user_query=user_input, top_k=3, thread_id=thread_id)
            print(f"\n답변: {answer}\n")
    finally:
        if driver is not None:
            driver.close()


if __name__ == "__main__":
    main()