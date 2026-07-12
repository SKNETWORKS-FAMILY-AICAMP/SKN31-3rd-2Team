import os
from typing import TypedDict, List, Dict, Any, Literal

from openai import OpenAI
from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from dotenv import load_dotenv

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from typing_extensions import Annotated
from langgraph.graph.message import add_messages

from graphdb_retriever import Neo4jRetriever
from vectordb_retriever import QdrantRetriever

load_dotenv()

TARGET_DATABASE = "lawdb"
QDRANT_COLLECTION = "GUIDANCE"

RetrieverType = Literal["neo4j", "qdrant"]

# 자기 평가 후 재검색: 최대 1번
MAX_RETRIES = 1

# 보조 판단 모델: 참조 필요 여부 판단 / 소스 선택 / 검색 결과 채점 / 검색어 재작성
MODEL_NAME = "gpt-4o-mini"

REWRITE_PROMPT = """당신은 법률·규정 검색용 질문을 재작성하는 도우미입니다.
사용자의 현재 질문이 이전 대화에 의존하는 경우, 이전 대화를 참고해서 현재 질문을
독립적으로 이해할 수 있는 명확한 검색용 질문으로 바꾸세요.

규칙:
1. 답변하지 말고 검색용 질문만 출력하세요.
2. 이전 질문의 주제, 법령명, 대상, 상황을 가능한 한 포함하세요.
3. 현재 질문이 이미 명확하면 그대로 출력하세요.
4. 이전 대화에 없는 내용을 임의로 추가하지 마세요.
5. 한 문장으로 작성하세요."""

# 참조 문서 검색이 필요한 질문인지 분기하기 위한 분류 프롬프트
ROUTE_PROMPT = """당신은 사용자 질문이 '군 법률·규정 참조 문서 검색'이 필요한지 판단하는 분류기입니다.

- 군대 법률·규정·훈령·권리·의무·처벌·휴가·징계·복무 등 규정 근거가 필요한 질문 → "yes"
- 단순 인사, 잡담, 챗봇(박병장) 자기소개, 규정과 무관한 일반 대화 → "no"

반드시 "yes" 또는 "no" 한 단어만 출력하세요."""

# 어떤 검색 소스(Neo4j/Qdrant)를 쓸지 결정하는 라우터 프롬프트
SOURCE_PROMPT = """당신은 사용자 질문을 어떤 검색 소스로 보낼지 결정하는 라우터입니다.
두 소스는 원본은 같은 문서군이지만, 담고 있는 데이터의 형태와 성격이 다릅니다.

- "neo4j": 법령 조문이 개별 조문 단위로 구조화되어 저장된 그래프 DB.
  법조문 원문, 조번호, 법적 근거를 정확히 "인용"해야 하는 질문에 강함.
- "qdrant": 실무 안내서(길라잡이) PDF의 본문·표·이미지가 원문 그대로 저장된 벡터 DB.
  법조문이 아니라 안내서에만 있는 절차, 수치, 표, 이미지, 연락처, 신청 방법에 강함.

"neo4j"로 보내는 경우 (아래 중 하나라도 해당):
1. 질문에 조번호나 법령명이 명시됨 (예: "군인사법 제31조", "복무규율 몇 조")
2. "~할 수 있나요?", "의무인가요?", "위반하면 어떻게 되나요?", "권리인가요?" 등
   권리·의무·처벌·자격요건의 법적 근거를 묻는 질문
3. "이게 법적으로 근거가 있나요?", "규정상 맞나요?" 처럼 규범적 정당성을 확인하는 질문

"qdrant"로 보내는 경우 (아래 중 하나라도 해당):
1. 구체적인 수치·금액·할인율·지급 기준을 묻는 질문
   (예: "휴가비 얼마 나와요?", "기차 할인율 몇 %예요?", "급식비 지원 금액은?")
2. 표 형태로 정리된 데이터를 찾는 질문
   (예: "호봉표 보여줘", "학군단 시간표 알려줘", "계급별 봉급표")
3. 이미지·서식·양식 자체를 확인해야 하는 질문
   (예: "신청서 양식이 어떻게 생겼어요?", "사진 있으면 보여줘")
4. 신청 절차, 방법, 연락처, 담당 부서 등 실무 프로세스를 묻는 질문
   (예: "취업 지원 어떻게 신청해요?", "상담관 연락처 알려줘", "전역 전에 뭐부터 준비해요?")
5. "~은 어떻게 도와줘요?", "~ 지원받으려면 뭐 해야 돼요?" 처럼
   법적 근거보다 "실제로 어떻게 하면 되는지"가 핵심인 질문

판단 우선순위:
- 질문에 조번호/법령명이 명시되어 있으면 무조건 "neo4j"
- 그 외에는 "법적 근거 확인"이 목적인지 "실무 정보/수치/표/절차"가 목적인지로 판단
- 여전히 애매하면 "qdrant"를 선택하세요 (실무 질문이 더 많은 시스템이므로).

예시:
Q: "군인사법 제31조가 뭔가요?" → neo4j
Q: "휴가 안 주면 규정 위반인가요?" → neo4j
Q: "전역예정장병 취업 어떻게 도와줘?" → qdrant
Q: "부사관 호봉표 보여줘" → qdrant
Q: "기차 할인 몇 % 받아요?" → qdrant
Q: "성고충전문상담관한테 연락하려면 어떻게 해요?" → qdrant

반드시 "neo4j" 또는 "qdrant" 한 단어만 출력하세요."""

# 검색 결과가 질문에 답하기 충분한지 스스로 평가하는 채점 프롬프트
GRADE_PROMPT = """당신은 검색된 참조 문서가 사용자 질문에 답하기에 충분한지 평가하는 채점기입니다.

기준:
- 문서가 질문의 핵심을 다루고 답변 근거로 쓸 수 있으면 → "yes"
- 문서가 질문과 관련이 없거나 근거로 삼기에 부족하면 → "no"

반드시 "yes" 또는 "no" 한 단어만 출력하세요."""

# 채점에서 부족('no') 판정이 나왔을 때, 재검색을 위한 검색어 개선 프롬프트
REFINE_PROMPT = """당신은 검색 결과가 부족했을 때 검색용 질문을 개선하는 도우미입니다.
이전 검색 질문으로는 관련 문서를 충분히 찾지 못했습니다.
같은 의미를 유지하되, 법령·규정 문서에서 더 잘 검색되도록 핵심 법률 용어나 키워드를
넣어 다른 표현으로 검색용 질문을 다시 작성하세요.

규칙:
1. 답변하지 말고 검색용 질문만 한 문장으로 출력하세요.
2. 원래 질문의 의도를 바꾸지 마세요.
3. 이전과 똑같은 문장을 반복하지 마세요."""

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
    needs_reference: bool            
    source: RetrieverType           
    search_data: List[Dict[str, Any]]
    context_text: str
    is_relevant: bool             
    retry_count: int               
    answer: str
    messages: Annotated[List[BaseMessage], add_messages]


class LangGraphChatbot:
    """Neo4j·Qdrant 두 retriever를 모두 받아, 질문마다 알맞은 소스를 '자동으로' 골라 동작하는 챗봇.
    두 retriever 모두 retrieve(user_query, top_k) 인터페이스가 동일하므로,
    검색 자체는 공통 코드로 처리하고 payload 구조가 다른 부분(context 조립)만 소스별로 분기한다.
    """

    def __init__(self, client: OpenAI, retrievers: Dict[RetrieverType, Any], verbose: bool = True):
        self.client = client
        self.retrievers = retrievers
        self.verbose = verbose
        self.checkpointer = InMemorySaver()
        self.workflow = self._build_graph()

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message)

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

    def _build_context(self, source: RetrieverType, search_data: List[Dict[str, Any]]) -> str:
        if source == "qdrant":
            return self._build_context_qdrant(search_data)
        return self._build_context_neo4j(search_data)

    def _to_openai_messages(self, messages: List[BaseMessage]) -> List[Dict[str, str]]:
        role_map = {HumanMessage: "user", AIMessage: "assistant"}
        return [
            {"role": role_map[type(m)], "content": str(m.content)}
            for m in messages if type(m) in role_map
        ]

    def _chat(self, system_prompt: str, history: List[Dict[str, str]],
              user_content: str, model: str = MODEL_NAME) -> str:
        """model 인자를 추가해서, 보조 판단(분류/채점/재작성)에는 MODEL_NAME을 넘김."""
        messages = [{"role": "system", "content": system_prompt}, *history,
                    {"role": "user", "content": user_content}]
        response = self.client.chat.completions.create(
            model=model, temperature=0, messages=messages
        )
        return (response.choices[0].message.content or "").strip()

    # ---------- nodes ----------
    def check_reference_node(self, state: ChatBotState) -> Dict[str, Any]:
        """이 질문이 규정 참조 검색이 필요한 질문인지 판단해서 needs_reference에 저장."""
        verdict = self._chat(
            ROUTE_PROMPT, [], f"질문: {state['user_query']}", model=MODEL_NAME
        )
        needs_reference = verdict.strip().lower().startswith("yes")
        self._log(f"[참조 필요 여부] {'예' if needs_reference else '아니오'}")
        return {"needs_reference": needs_reference}

    def route_source_node(self, state: ChatBotState) -> Dict[str, Any]:
        """질문 성격을 보고 Neo4j / Qdrant 중 처음 시도할 소스를 자동으로 고른다."""
        verdict = self._chat(
            SOURCE_PROMPT, [], f"질문: {state['user_query']}", model=MODEL_NAME
        )
        source: RetrieverType = "qdrant" if verdict.strip().lower().startswith("qdrant") else "neo4j"
        self._log(f"[소스 선택] {source}")
        return {"source": source}

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
        source: RetrieverType = state.get("source", "neo4j")
        retriever = self.retrievers[source]

        search_query = state.get("search_query", state["user_query"])
        top_k = state.get("top_k", 3)
        search_data = retriever.retrieve(user_query=search_query, top_k=top_k)

        source_name = "Qdrant" if source == "qdrant" else "Neo4j"
        context_text = (
            self._build_context(source, search_data) if search_data
            else f"현재 질문과 관련된 참조 문서를 {source_name}에서 찾지 못했습니다."
        )
        return {"search_data": search_data, "context_text": context_text}

    def grade_node(self, state: ChatBotState) -> Dict[str, Any]:
        """검색 결과가 질문에 답하기 충분한지 스스로 평가. 검색 결과가 아예 없으면 LLM 호출 없이 바로 '부족'으로 처리"""
        search_data = state.get("search_data", [])
        if not search_data:
            self._log("[채점] 검색 결과 없음 → 부족")
            return {"is_relevant": False}

        verdict = self._chat(
            GRADE_PROMPT, [],
            f"[사용자 질문]\n{state['user_query']}\n\n[검색된 문서]\n{state.get('context_text', '')}",
            model=MODEL_NAME,
        )
        is_relevant = verdict.strip().lower().startswith("yes")
        self._log(f"[채점] {'충분' if is_relevant else '부족'}")
        return {"is_relevant": is_relevant}

    def refine_node(self, state: ChatBotState) -> Dict[str, Any]:
        """채점 결과가 '부족'일 때: 검색어를 개선하고, 소스를 반대쪽으로 전환해 다른 DB도 시도.
        (Neo4j와 Qdrant는 담긴 내용이 다르므로, 한 번의 재검색을 다른 소스에 쓰는 게 효과적이다.)"""
        retry_count = state.get("retry_count", 0) + 1
        current: RetrieverType = state.get("source", "neo4j")
        switched: RetrieverType = "qdrant" if current == "neo4j" else "neo4j"

        new_query = self._chat(
            REFINE_PROMPT, [],
            f"원래 질문: {state['user_query']}\n이전 검색 질문: {state.get('search_query', '')}",
            model=MODEL_NAME,
        )
        self._log(f"[재검색 {retry_count}/{MAX_RETRIES}] 소스 {current} → {switched}, 검색어 재작성")
        return {
            "source": switched,
            "search_query": new_query or state.get("search_query", state["user_query"]),
            "retry_count": retry_count,
        }

    def generate_node(self, state: ChatBotState) -> Dict[str, Any]:
        previous_messages = state.get("messages", [])[:-1]
        history = self._to_openai_messages(previous_messages)

        if state.get("needs_reference"):
            # 참조가 필요한 질문: 검색된 문서를 근거로 답변
            current_prompt = (
                f"[검색에 사용한 질문]\n{state.get('search_query', state['user_query'])}\n\n"
                f"[참조 문서]\n{state.get('context_text', '')}\n\n"
                f"[사용자의 현재 질문]\n{state['user_query']}"
            )
        else:
            # 참조가 필요 없는 질문(인사·잡담 등): 박병장 캐릭터로만 답변, 근거 줄 생략
            current_prompt = (
                f"[사용자의 현재 질문]\n{state['user_query']}\n\n"
                "이 질문은 규정 참조가 필요 없는 일반 대화입니다. "
                "박병장 캐릭터로 자연스럽게 답하되, 규정 근거([근거: ...]) 줄은 붙이지 마세요."
            )

        answer = self._chat(GENERATE_PROMPT, history, current_prompt) or "답변을 생성하지 못했습니다."
        return {"answer": answer, "messages": [AIMessage(content=answer)]}

    # ---------- routers ----------
    def route_after_check(self, state: ChatBotState) -> Literal["route_source", "generate"]:
        """참조가 필요하면 소스 라우팅(route_source)으로, 아니면 바로 답변 생성으로."""
        return "route_source" if state.get("needs_reference") else "generate"

    def route_after_grade(self, state: ChatBotState) -> Literal["generate", "refine"]:
        """검색 결과가 충분하거나 재검색 한도를 다 쓰면 답변 생성, 아니면 검색어를 개선해 다시 검색"""
        if state.get("is_relevant"):
            return "generate"
        if state.get("retry_count", 0) >= MAX_RETRIES:
            return "generate"
        return "refine"

    # ---------- graph ----------
    def _build_graph(self):
        builder = StateGraph(ChatBotState)
        builder.add_node("check_reference", self.check_reference_node)
        builder.add_node("route_source", self.route_source_node)
        builder.add_node("rewrite", self.rewrite_node)
        builder.add_node("retrieve", self.retrieve_node)
        builder.add_node("grade", self.grade_node)
        builder.add_node("refine", self.refine_node)
        builder.add_node("generate", self.generate_node)

        builder.add_edge(START, "check_reference")

        # [분기 1] 참조 필요 여부: 필요하면 소스 라우팅, 아니면 바로 답변
        builder.add_conditional_edges(
            "check_reference",
            self.route_after_check,
            {"route_source": "route_source", "generate": "generate"},
        )

        # [분기 2] 소스 자동 선택 → 검색 파이프라인
        builder.add_edge("route_source", "rewrite")
        builder.add_edge("rewrite", "retrieve")
        builder.add_edge("retrieve", "grade")

        # [분기 3] 자기 평가 후 재검색 루프: 부족하면 refine(검색어 개선 + 소스 전환) → retrieve 로 되돌아감
        builder.add_conditional_edges(
            "grade",
            self.route_after_grade,
            {"generate": "generate", "refine": "refine"},
        )
        builder.add_edge("refine", "retrieve")

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


def _build_neo4j_retriever(client: OpenAI):
    neo4j_uri = _require_env("NEO4J_URI")
    neo4j_username = _require_env("NEO4J_USERNAME")
    neo4j_password = _require_env("NEO4J_PASSWORD")
    driver = GraphDatabase.driver(
        neo4j_uri, 
        auth=(neo4j_username, neo4j_password),
        notifications_min_severity="OFF"    
    )
    return Neo4jRetriever(client=client, driver=driver, database=TARGET_DATABASE), driver


def _build_qdrant_retriever(client: OpenAI):
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_api_key = os.getenv("QDRANT_API_KEY") or None
    collection_name = os.getenv("QDRANT_COLLECTION", QDRANT_COLLECTION)
    qdrant_client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    return QdrantRetriever(client=client, qdrant=qdrant_client, collection_name=collection_name), qdrant_client


def main():
    api_key = _require_env("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key)

    # 두 retriever를 질문마다 그래프가 자동으로 고름
    neo4j_retriever, driver = _build_neo4j_retriever(client)
    qdrant_retriever, qdrant_client = _build_qdrant_retriever(client)

    retrievers: Dict[RetrieverType, Any] = {
        "neo4j": neo4j_retriever,
        "qdrant": qdrant_retriever,
    }

    bot = LangGraphChatbot(client=client, retrievers=retrievers)

    print("\n💬 군 생활 법률·규정 챗봇 (박병장) - [소스 자동 선택 모드]입니다.")
    print("질문 성격에 따라 Neo4j(조문)/Qdrant(PDF)를 알아서 골라 검색합니다.")
    print("종료하려면 exit를 입력하세요.\n")
    thread_id = "console-user-1"

    try:
        while True:
            user_input = input("🔍 질문: ").strip()
            if user_input.lower() in {"exit", "quit"}:
                break
            if not user_input:
                continue

            answer = bot.ask(user_query=user_input, top_k=3, thread_id=thread_id)
            print(f"\n✅ 답변: {answer}\n")
    finally:
        if driver is not None:
            driver.close()
        if qdrant_client is not None:
            qdrant_client.close()


if __name__ == "__main__":
    main()