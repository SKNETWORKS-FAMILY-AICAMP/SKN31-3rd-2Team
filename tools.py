import os
from langchain_core.tools import tool  # LangGraph/LangChain 전용 데코레이터
from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from vectordb_retriever import QdrantRetriever
from neo4j import GraphDatabase
from graphdb_retriever import Neo4jRetriever

# =====================================================================
# [수정] 클라이언트/드라이버를 모듈 레벨에서 한 번만 생성해 재사용한다.
# - 기존에는 도구가 호출될 때마다 OpenAI/Qdrant 클라이언트, Neo4j 드라이버를
#   매번 새로 만들었다. 평가 루프처럼 짧은 시간에 여러 번 호출될 때
#   커넥션이 계속 새로 열리며 순간적인 부하/타임아웃(Connection error)의
#   원인이 될 수 있고, QdrantClient는 닫히지도 않아 리소스가 누수됐다.
# - LangGraph 툴 함수는 보통 같은 프로세스/스레드 내에서 반복 호출되므로,
#   모듈 임포트 시 한 번만 초기화해 재사용해도 안전하다.
# =====================================================================
load_dotenv()

_openai_client = OpenAI()
_qdrant_client = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
_neo4j_driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
)
_NEO4J_DATABASE = os.getenv("NEO4J_DATABASE")

_qdrant_retriever = QdrantRetriever(
    client=_openai_client,
    qdrant=_qdrant_client,
    collection_name="guidance_vectordb",
)

_neo4j_retriever = Neo4jRetriever(
    client=_openai_client,
    driver=_neo4j_driver,
    database=_NEO4J_DATABASE,
)


@tool
def search_guidance_knowledge_base(user_query: str) -> str:
    """군 생활 '가이드북성 실무 안내'를 검색합니다. 병영 복지, 생활 편의, 행정 절차 등
        현장 실무 팁을 다룬 '2026 초급간부 길라잡이', '병영생활 안내서' 문서에서 찾습니다.

        다음과 같이 '조문/처벌/징계'가 아니라 '어떻게 하면 되는지' 절차·복지·팁을 묻는 질문에 사용하세요:
        
    보수/수당 (초급간부/병사 보수, 급식/물자, 군인공제회 등)
    복지/시설 (나라사랑카드, 장병내일준비적금, 청약통장, 군 마트/Wa-Mall, 휴양시설, 체력단련장)
    인사/근무 절차 (휴가·외출·외박 "신청 방법", 장기/연장복무 "절차", 전과 제도, 표창/상훈, 예비군훈련)
    진료/재해보상 절차 (군 보건의료기관 이용법, 응급진료, 사망/장애보상금, 병 무료 상해보험)
    고충/상담 창구 (성고충/병영생활전문상담관, 국방헬프콜 1303, 군 인권지키미)

        사용하지 않는 경우: 법적 처벌 수위, 징계 조문, 법적 권리·의무의 근거를 물으면
        대신 search_law_knowledge_graph를 사용하세요.

        Args:
            user_query: 검색할 구체적인 질문 (한국어). 예: "초급간부 휴가 신청 방법", "장병내일준비적금 신청 절차".
        """
    try:
        raw_results = _qdrant_retriever.retrieve(user_query=user_query, top_k=2)
    except Exception as e:
        # 모든 폴백이 실패한 최악의 경우에도 툴 자체는 죽지 않고
        # LLM이 이해할 수 있는 문자열을 반환하도록 한다.
        print(f"[Tool Warning] search_guidance_knowledge_base 실패: {e}")
        return "지침서 검색 중 오류가 발생하여 관련 문서를 가져오지 못했습니다."

    if not raw_results:
        return "질문과 관련된 지침서 문서를 찾지 못했습니다."

    formatted_docs = []
    for i, doc in enumerate(raw_results, 1):
        clean_text = (doc.get("text") or "").strip()
        if not clean_text:
            continue
        formatted_docs.append(f"--- [참조 문서 {i}] ---\n{clean_text}")

    return "\n\n".join(formatted_docs) if formatted_docs else "질문과 관련된 지침서 문서를 찾지 못했습니다."


@tool
def search_law_knowledge_graph(user_query: str) -> str:
    """군 관련 법률·시행령·훈령의 '조문 단위 법적 근거'를 Neo4j 지식그래프에서 검색합니다.

        다음과 같이 명확한 법적 처벌/징계/권리 근거가 필요한 질문에 사용하세요:
        
    무단이탈/지시 불이행 등에 대한 처벌 수위, 징계 종류
    특정 조 번호(예: '제8조')나 법령명이 언급된 질문
    보수/호봉 획정의 법적 기준
    서로 다른 법령·훈령 간의 관계

        사용하지 않는 경우: 복지/생활 편의, 절차 안내, "어떻게 신청하나요" 류의 질문은
        대신 search_guidance_knowledge_base를 사용하세요.

        Args:
            user_query: 검색할 구체적인 법률 질의 또는 조문 설명 (한국어).
        """
    try:
        # 조문 + 참조 조문을 함께 가져오는 구조라 top_k를 조금 넉넉하게 준다.
        raw_results = _neo4j_retriever.retrieve(user_query=user_query, top_k=4)
    except Exception as e:
        print(f"[Tool Warning] search_law_knowledge_graph 실패: {e}")
        return "법령 그래프 검색 중 오류가 발생하여 관련 조문을 가져오지 못했습니다."

    if not raw_results:
        return "질문과 관련된 조문을 찾지 못했습니다."

    formatted_docs = []
    for i, doc in enumerate(raw_results, 1):
        description = (doc.get("description") or "").strip()
        if not description:
            continue
        formatted_docs.append(
            f"--- [참조 조문 {i}] ---\n[조문] {doc.get('name', '')} (ID: {doc.get('id', '')})\n{description}"
        )

    return "\n\n".join(formatted_docs) if formatted_docs else "질문과 관련된 조문을 찾지 못했습니다."


def close_clients() -> None:
    """프로세스 종료 시 명시적으로 호출하여 Neo4j 드라이버 등 리소스를 정리한다."""
    try:
        _neo4j_driver.close()
    except Exception:
        pass


# # ==========================================
# # 툴 작동 확인을 위한 간단한 테스트 코드
# # ==========================================
# if __name__ == "__main__":
#     print("[테스트 시작] DB에서 데이터를 정상적으로 긁어오는지 확인합니다...\n")
#
#     print("1. Qdrant 지침서 DB 테스트 중...")
#     try:
#         qdrant_results = search_guidance_knowledge_base.invoke(
#             {"user_query": "2026년도 초급간부 휴가 관련 규정 알려줘"}
#         )
#         print(f"Qdrant 결과:\n{qdrant_results[:200]}...\n")
#     except Exception as e:
#         print(f"Qdrant 에러 발생: {e}\n")
#
#     print("-" * 50)
#
#     print("2. Neo4j 법률 그래프 DB 테스트 중...")
#     try:
#         neo4j_results = search_law_knowledge_graph.invoke(
#             {"user_query": "공무원보수규정 제8조에 대해 알려줘"}
#         )
#         print(f"Neo4j 결과:\n{neo4j_results[:200]}...\n")
#     except Exception as e:
#         print(f"Neo4j 에러 발생: {e}\n")
#     finally:
#         close_clients()
#
#     print("[테스트 종료]")