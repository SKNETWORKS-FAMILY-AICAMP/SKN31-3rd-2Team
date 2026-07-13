import os
from typing import List
from langchain_core.tools import tool  # LangGraph/LangChain 전용 데코레이터
from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from vectordb_retriever import QdrantRetriever
from neo4j import GraphDatabase
from graphdb_retriever import Neo4jRetriever

@tool
def search_guidance_knowledge_base(user_query: str) -> str: # 반환 타입을 str로 변경
    """Search the military guidance knowledge base to find relevant regulation documents.

    Use this tool when the user asks questions about military regulations, 
    vacation rules, executive officer guidelines, or specific table data in the document.
    Especially effective for queries regarding the '2026 초급간부 길라잡이' or '병영생활 안내서' topics such as:
    - 보수/수당 (초급간부/병사 보수, 급식/물자, 군인공제회 등)
    - 복지/시설 (나라사랑카드, 장병내일준비적금, 청약통장, 군 마트/Wa-Mall, 휴양시설, 체력단련장)
    - 인사/근무 (휴가·외출·외박, 장기/연장복무, 전과 제도, 표창/상훈, 예비군훈련)
    - 진료/재해보상 (군 보건의료기관, 응급진료, 사망/장애보상금, 병 무료 상해보험)
    - 고충/상담 (성고충/병영생활전문상담관, 국방헬프콜 1303, 군 인권지키미)

    Args:
        user_query: The specific search query or user question in Korean (e.g., "초급간부 휴가 규정", "장병내일준비적금 신청", "군병원 응급진료").
    """
    # 💡 LangGraph 내부에서 안정적으로 돌 수 있게 환경변수와 클라이언트를 함수 내에서 초기화합니다.
    load_dotenv()
    
    openai_client = OpenAI()
    qdrant_client = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333")) # 환경변수 처리 개선
    
    retriever = QdrantRetriever(
        client=openai_client,
        qdrant=qdrant_client,
        collection_name="guidance_vectordb"
    )
    
    # 검색 결과 가져오기
    raw_results = retriever.retrieve(user_query=user_query, top_k=4)
    
    # 오직 page_content(text)만 추출하여 가독성 좋은 텍스트로 합치기
    # 각 문서 사이에 구분선을 넣어 LLM과 사람이 모두 읽기 편하게 만듭니다.
    formatted_docs = []
    for i, doc in enumerate(raw_results, 1):
        # 텍스트 내의 특수문자나 불필요한 공백을 가볍게 정리할 수 있습니다.
        clean_text = doc["text"].strip()
        formatted_docs.append(f"--- [참조 문서 {i}] ---\n{clean_text}")
        
    return "\n\n".join(formatted_docs)


@tool
def search_law_knowledge_graph(user_query: str) -> str: # 반환 타입을 str로 변경
    """Search the Neo4j legal knowledge graph to retrieve specific law articles and referenced terms.
    
    Use this tool when the user queries explicit statutory provisions, specific article numbers 
    (e.g., 'Article 8'), or relationships between different military laws and acts.
    
    Args:
        user_query: The specific legal search query or article description in Korean.
    """
    # 💡 LangGraph 내부에서 안정적으로 연결되도록 함수 내에서 환경변수와 드라이버를 초기화합니다.
    load_dotenv()
    
    openai_client = OpenAI()
    
    # .env 파일에 NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DB_NAME이 정의되어 있어야 합니다.
    neo4j_driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD"))
    )
    database_name = os.getenv("NEO4J_DATABASE")
    
    retriever = Neo4jRetriever(
        client=openai_client,
        driver=neo4j_driver,
        database=database_name
    )
    
    # 1. 그래프 검색 및 벡터 폴백 가동 (딕셔너리 리스트 반환)
    raw_results = retriever.retrieve(user_query=user_query, top_k=4)
    
    # 세션 드라이버 안전하게 닫기
    neo4j_driver.close()
    
    # 2. 조문 제목(법령명·조 번호)을 본문과 함께 담아 문자열로 묶기
    formatted_docs = []
    for i, doc in enumerate(raw_results, 1):
        description = doc.get("description", "").strip()
        if not description:
            continue
        formatted_docs.append(f"--- [참조 조문 {i}] ---\n[조문] {doc.get('name', '')} (ID: {doc.get('id', '')})\n{description}")
        
    return "\n\n".join(formatted_docs)


# # ==========================================
# # 툴 작동 확인을 위한 간단한 테스트 코드
# # ==========================================
# if __name__ == "__main__":
#     print("[테스트 시작] DB에서 데이터를 정상적으로 긁어오는지 확인합니다...\n")

#     # 1. Qdrant 툴 테스트
#     print("1. Qdrant 지침서 DB 테스트 중...")
#     try:
#         # LangChain 툴은 함수명(인자) 대신 .invoke()를 쓰면 안전하게 알맹이만 실행됩니다.
#         qdrant_results = search_guidance_knowledge_base.invoke(
#             {"user_query": "2026년도 초급간부 휴가 관련 규정 알려줘"}
#         )
#         print(f"Qdrant 성공! 가져온 본문 개수: {len(qdrant_results)}개")
#         if qdrant_results:
#             print(f"샘플 내용: {qdrant_results[0][:100]}...\n")
#         else:
#             print("DB 연결은 됐으나 매칭되는 데이터가 없습니다.\n")
#     except Exception as e:
#         print(f"Qdrant 에러 발생: {e}\n")

#     print("-" * 50)

#     # 2. Neo4j 툴 테스트
#     print("2. Neo4j 법률 그래프 DB 테스트 중...")
#     try:
#         neo4j_results = search_law_knowledge_graph.invoke(
#             {"user_query": "공무원보수규정 제8조에 대해 알려줘"}
#         )
#         print(f"Neo4j 성공! 가져온 조문 개수: {len(neo4j_results)}개")
#         if neo4j_results:
#             print(f"샘플 내용: {neo4j_results[0][:100]}...\n")
#         else:
#             print("DB 연결은 됐으나 매칭되는 데이터가 없습니다.\n")
#     except Exception as e:
#         print(f"Neo4j 에러 발생: {e}\n")

#     print("[테스트 종료]")