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
    """군 생활 '가이드북성 실무 안내'를 검색합니다. 
    
    병영 복지, 생활 편의, 행정 절차 등 현장 실무 팁을 다룬 '2026 초급간부 길라잡이', 
    '병영생활 안내서' 등의 가이드북 문서에서 정보를 탐색합니다.
    
    [언제 사용하나요?]
    '법적 조문/처벌/징계 규정'이 아니라, '어떻게 혜택을 받고 신청하는지' 실무 절차·복지·팁을 묻는 질문에 사용하세요:
    - 보수/수당: 초급간부/병사 보수, 급식/물자, 군인공제회 저축제도 등
    - 복지/시설: 나라사랑카드, 장병내일준비적금, 청년 주택드림 청약통장, 군 마트/Wa-Mall, 휴양시설 및 체력단련장 이용
    - 인사/근무 절차: 휴가·외출·외박 신청 방법, 장기/연장복무 신청, 전과(병과 전환) 제도, 표창/상훈, 예비군훈련 안내
    - 진료/재해보상: 군 보건의료기관/민간 의료시설 이용법, 응급진료 절차, 사망/장애보상금 청구, 병 무료 상해보험
    - 고충/상담 창구: 성고충/병영생활전문상담관, 국방헬프콜 1303, 군 인권지키미 이용 방법
    
    [언제 사용하지 않나요?]
    법적 처벌 수위, 징계 기준, 법적 권리·의무의 구체적인 법령 근거를 물을 때는 이 도구 대신 'search_law_knowledge_graph'를 사용하세요.
    - 예시 1: "휴가 신청 어떻게 하나요?" -> 이 도구(search_guidance_knowledge_base) 사용
    - 예시 2: "정당한 사유 없이 휴가를 잘렸는데 징계나 규정 위반인가요?" -> 'search_law_knowledge_graph' 사용
    
    Args:
        user_query (str): 검색할 구체적인 질문 또는 군 제도 키워드 (한국어). 
                         (예: "초급간부 휴가 신청 방법", "장병내일준비적금 매칭지원금 신청")
                         
    Returns:
        str: 해당 가이드북에서 추출한 상세 안내 및 절차 내용.
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
    
    [★ 중요: 언제 사용하나요? - 엄격한 법적 판단 전용]
    단순한 안내나 절차가 아니라, '처벌/징계/법적 권리·의무' 등 오직 엄격한 법률적 근거 및 규정 위반 여부를 판단해야 할 때만 이 툴을 사용하세요.
    - 처벌/징계 수위: 무단이탈, 지시 불이행, 명령 불복종, 가혹행위 등에 대한 처벌 수위 및 구체적인 징계 종류
    - 법령/조문 명시: 특정 조 번호(예: '제8조')나 구체적인 법령명(예: '군인사법', '군형법')이 직접 언급된 질문
    - 법적 지급 기준: 초임호봉 획정, 보수/수당의 법적 지급 기준 및 산정 원칙 (단순 '수당 신청 방법'은 제외)
    - 적법성 판단: 지휘관의 조치(휴가 제한, 인사 조치, 징계 등)가 '규정/법령 위반인지 아닌지' 법적 판단이 필요한 질문
    - 규정 간 관계: 서로 다른 법령·훈령·시행령 간의 상하위 관계나 연계 조문 확인
    
    [언제 사용하지 않나요?]
    복지 혜택, 시설 이용, 신청 절차 등 "어떻게 하면 되나요?" 류의 가이드북성 실무 안내는 절대로 이 툴을 사용하지 말고, 대신 'search_guidance_knowledge_base'를 사용하세요.
    - 예시 1: "정당한 사유 없이 휴가를 취소당했는데 규정 위반인가요?" -> 이 도구(search_law_knowledge_graph) 사용
    - 예시 2: "휴가 가려는데 신청 절차가 어떻게 되나요?" -> 'search_guidance_knowledge_base' 사용
    
    Args:
        user_query (str): 검색할 구체적인 법률 질의, 조문 번호 또는 법령 설명 (한국어).
                         (예: "무단이탈 처벌 수위", "지시 불이행 시 징계 규정", "공무원보수규정 제8조")
                         
    Returns:
        str: 지식그래프에서 추출한 관련 법령 조문, 상하위 규정 및 법적 근거 데이터.
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