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
def search_guidance_knowledge_base(user_query: str) -> List[str]:
    """Search the military guidance knowledge base to find relevant regulation documents.
    
    Use this tool when the user asks questions about military regulations, 
    vacation rules, executive officer guidelines, or specific table data in the document.
    
    Args:
        user_query: The specific search query or user question in Korean.
    """
    # 💡 LangGraph 내부에서 안정적으로 돌 수 있게 환경변수와 클라이언트를 함수 내에서 초기화합니다.
    load_dotenv()
    
    openai_client = OpenAI()
    qdrant_client = QdrantClient(url=os.getenv("http://localhost:6333"))
    
    retriever = QdrantRetriever(
        client=openai_client,
        qdrant=qdrant_client,
        collection_name="guidance_vectordb"
    )
    
    # 검색 후 오직 page_content(text)만 리스트로 추출
    raw_results = retriever.retrieve(user_query=user_query, top_k=4)
    return [doc["text"] for doc in raw_results]



@tool
def search_law_knowledge_graph(user_query: str) -> List[str]:
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
    
    # 2. 요청하신 스타일대로 오직 법령 조문 본문(description)만 문자열 리스트로 추출
    descriptions = [doc.get("description", "") for doc in raw_results if doc.get("description")]
    
    return descriptions



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