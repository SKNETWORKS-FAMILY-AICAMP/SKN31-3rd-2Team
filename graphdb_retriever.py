import re
from openai import OpenAI
from neo4j import GraphDatabase

CHAT_MODEL = "gpt-5.4-mini"  # 실제 사용 가능한 모델명인지 한 번 확인 권장
EMBEDDING_MODEL = "text-embedding-3-large"

FORBIDDEN_KEYWORDS = {"CREATE", "DELETE", "SET", "MERGE", "REMOVE", "DROP", "DETACH"}

# 벡터 검색(폴백)의 코사인 유사도 임계값 / 폴백 시 최소 반환 개수
DEFAULT_SCORE_THRESHOLD = 0.75
DEFAULT_FALLBACK_K = 1

SCHEMA_DESCRIPTION = """
그래프 DB 스키마:
1. 노드 라벨:
  - LAW (법률/법령 메타데이터)
    * 속성: id (string, 예: "공무원보수규정"), name (string), law_type (string), effective_date (string)
  - ARTICLE (법령 조문)
    * 속성: id (string, 형식 "법령명::제N조"), name (string, 조문제목), description (string, 본문), original_id (string, 예: "제8조"), law_id (string)

2. 관계(Relationships):
  - (:LAW)-[:CONTAINS]->(:ARTICLE) : 법률이 특정 조문을 포함함.
  - (:ARTICLE)-[:REFERENCE]->(:ARTICLE) : 하나의 조문이 다른 조문을 참조/인용함.

벡터 인덱스: 'article_vector_index' (ARTICLE 노드의 embedding 속성 기준, 의미 검색용)
"""


class Neo4jRetriever:
    """사용자 질문을 받아 Neo4j(text-to-Cypher + 벡터 폴백)에서 참조 조문을 가져오는 retriever

    [수정 이력]
    1. _generate_cypher() 등 OpenAI 호출부가 예외 처리 없이 노출되어 있어,
       네트워크 순간 장애 시 retrieve() 전체가 죽는 문제(Connection error) 수정.
       -> 모든 외부 호출(Cypher 생성, 임베딩 생성, Neo4j 세션 실행)을 개별적으로
          try/except 하여 실패 시 벡터 폴백으로 안전하게 전환하도록 변경.
    2. 특정 조문 조회 시 LLM이 합성한 id("법령명::제N조") 완전 일치(=) 매칭에
       의존하면 표기 차이만으로도 매칭 실패 -> 불필요한 벡터 폴백이 발생하는 문제.
       -> 프롬프트 예시를 original_id / law_id 기반 CONTAINS 매칭으로 변경.
    3. 벡터 폴백이 무조건 top_k개를 채워 반환하여 관련 없는 조문까지 섞이는 문제
       (Qdrant retriever의 백필 버그와 동일한 패턴).
       -> score_threshold를 넘는 결과만 채택하고, 하나도 없으면 fallback_k개만
          반환하도록 변경 (Qdrant retriever와 동일한 설계로 통일).
    """

    def __init__(self, client: OpenAI, driver: GraphDatabase.driver, database: str):
        self.client = client
        self.driver = driver
        self.database = database

    def _is_safe_cypher(self, query: str) -> bool:
        upper = query.upper()
        return not any(re.search(rf"\b{kw}\b", upper) for kw in FORBIDDEN_KEYWORDS)

    def _generate_cypher(self, user_query: str) -> str:
        system_prompt = f"""
당신은 Neo4j Cypher 쿼리를 작성하는 전문가입니다.
아래 그래프 스키마만을 근거로, 사용자 질문에 답하기 위한 최적의 Cypher 쿼리를 작성하세요.

{SCHEMA_DESCRIPTION}

쿼리 작성 가이드라인:
1. 오직 읽기(MATCH) 쿼리만 작성하세요. (CUD 명령어 절대 금지)
2. [특정 조문 지정 질문]: 사용자가 특정 법령이나 조번호를 명시했다면 (예: "공무원보수규정 제8조에 대해 알려줘"),
   id 완전 일치(=) 대신 **original_id / law_id 기반 CONTAINS 매칭**을 사용하세요.
   표기 차이(띄어쓰기, "제N조" vs "N조" 등)로 인한 매칭 실패를 방지하기 위함입니다.
   그리고 **그 조문이 참조하고 있는 타 조문들까지 함께 가져오는 쿼리**를 작성하세요.
   예시 형태:
   MATCH (a:ARTICLE)
   WHERE a.original_id CONTAINS "제8조" AND a.law_id CONTAINS "공무원보수규정"
   OPTIONAL MATCH (a)-[:REFERENCE]->(ref:ARTICLE)
   RETURN a.id AS id, a.name AS name, a.description AS description, 1.0 AS score
   UNION
   MATCH (a:ARTICLE)-[:REFERENCE]->(ref:ARTICLE)
   WHERE a.original_id CONTAINS "제8조" AND a.law_id CONTAINS "공무원보수규정"
   RETURN ref.id AS id, ref.name AS name, ref.description AS description, 0.9 AS score

3. [주제/의미 검색 질문]: 명시된 법령명이나 조번호가 없고 일반적인 내용 질문이라면, 아래의 벡터 검색 형태를 사용하세요:
   CALL db.index.vector.queryNodes('article_vector_index', $top_k, $query_embedding)
   YIELD node, score
   RETURN node.id AS id, node.name AS name, node.description AS description, score
   ORDER BY score DESC

4. 결과 포맷 변수명 준수: 어떤 쿼리를 작성하든 RETURN문에는 반드시 'id', 'name', 'description', 'score'라는 별칭(AS)을 사용해야 합니다.
5. 오직 Cypher 쿼리 텍스트만 출력하세요. 마크다운 코드 블록(```)이나 설명은 절대 포함하지 마세요.
"""
        response = self.client.chat.completions.create(
            model=CHAT_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query},
            ],
        )
        cypher = response.choices[0].message.content.strip()
        cypher = re.sub(r'^```(cypher)?\s*|\s*```$', '', cypher, flags=re.MULTILINE).strip()
        return cypher

    def _embed_query(self, user_query: str) -> list[float]:
        return self.client.embeddings.create(
            model=EMBEDDING_MODEL, input=[user_query]
        ).data[0].embedding

    def _vector_fallback(
        self,
        user_query: str,
        top_k: int,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        fallback_k: int = DEFAULT_FALLBACK_K,
    ) -> list[dict]:
        """벡터 검색 기반 폴백.

        top_k를 무조건 채우지 않고, score_threshold를 넘는 결과만 채택한다.
        하나도 없으면 최상위 fallback_k개만 반환한다 (Qdrant retriever와 동일 설계).
        """
        try:
            embedding = self._embed_query(user_query)
        except Exception as e:
            print(f"[Neo4j Warning] 폴백용 임베딩 생성 실패: {e}. 빈 결과를 반환합니다.")
            return []

        search_limit = max(top_k, 10)  # threshold 컷을 감안해 넉넉히 확보
        cypher = """
        CALL db.index.vector.queryNodes('article_vector_index', $search_limit, $query_embedding)
        YIELD node, score
        RETURN node.id AS id, node.name AS name, node.description AS description, score
        ORDER BY score DESC
        """
        try:
            with self.driver.session(database=self.database) as session:
                results = [
                    dict(r)
                    for r in session.run(
                        cypher, search_limit=search_limit, query_embedding=embedding
                    )
                ]
        except Exception as e:
            print(f"[Neo4j Warning] 벡터 폴백 쿼리 실행 실패: {e}. 빈 결과를 반환합니다.")
            return []

        passed = [r for r in results if r.get("score", 0) >= score_threshold]
        if not passed:
            passed = results[:fallback_k]

        return passed[:top_k]

    def retrieve(
        self,
        user_query: str,
        top_k: int = 5,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        fallback_k: int = DEFAULT_FALLBACK_K,
    ) -> list[dict]:
        """참조 문서(조문) 목록을 반환.

        text-to-Cypher 우선, 아래 어느 단계에서든 실패하면 벡터 검색으로 안전하게 폴백한다.
        - Cypher 생성 (OpenAI 호출) 실패
        - 안전하지 않은 Cypher (CUD 키워드 포함)
        - 임베딩 생성 (OpenAI 호출) 실패
        - Cypher 실행 (Neo4j) 실패
        - 실행 결과가 0건
        """
        try:
            cypher = self._generate_cypher(user_query)
        except Exception as e:
            print(f"[Neo4j Warning] Cypher 생성 실패: {e}. 벡터 검색으로 폴백합니다.")
            return self._vector_fallback(user_query, top_k, score_threshold, fallback_k)

        if not self._is_safe_cypher(cypher):
            return self._vector_fallback(user_query, top_k, score_threshold, fallback_k)

        params = {"top_k": top_k}
        if "query_embedding" in cypher:
            try:
                params["query_embedding"] = self._embed_query(user_query)
            except Exception as e:
                print(f"[Neo4j Warning] 임베딩 생성 실패: {e}. 벡터 검색으로 폴백합니다.")
                return self._vector_fallback(user_query, top_k, score_threshold, fallback_k)

        try:
            with self.driver.session(database=self.database) as session:
                results = session.run(cypher, **params)
                rows = [dict(r) for r in results]
        except Exception as e:
            print(f"[Neo4j Warning] Cypher 실행 실패: {e}. 벡터 검색으로 폴백합니다.")
            return self._vector_fallback(user_query, top_k, score_threshold, fallback_k)

        if not rows:
            return self._vector_fallback(user_query, top_k, score_threshold, fallback_k)

        return rows