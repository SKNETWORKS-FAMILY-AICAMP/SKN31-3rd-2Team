import re
from openai import OpenAI
from neo4j import GraphDatabase

CHAT_MODEL = "gpt-5.4-mini"
EMBEDDING_MODEL = "text-embedding-3-large"

FORBIDDEN_KEYWORDS = {"CREATE", "DELETE", "SET", "MERGE", "REMOVE", "DROP", "DETACH"}

# [수정] LAW 노드와 관계선(CONTAINS, REFERENCE) 정보를 스키마에 명확히 추가
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
    """사용자 질문을 받아 Neo4j(text-to-Cypher + 벡터 폴백)에서 참조 조문을 가져오는 retriever"""

    def __init__(self, client: OpenAI, driver: GraphDatabase.driver, database: str):
        self.client = client
        self.driver = driver
        self.database = database

    def _is_safe_cypher(self, query: str) -> bool:
        upper = query.upper()
        return not any(re.search(rf"\b{kw}\b", upper) for kw in FORBIDDEN_KEYWORDS)

    def _generate_cypher(self, user_query: str) -> str:
        # [수정] LLM이 관계를 활용한 영리한 쿼리를 짜도록 프롬프트 대폭 강화
        system_prompt = f"""
당신은 Neo4j Cypher 쿼리를 작성하는 전문가입니다.
아래 그래프 스키마만을 근거로, 사용자 질문에 답하기 위한 최적의 Cypher 쿼리를 작성하세요.

{SCHEMA_DESCRIPTION}

쿼리 작성 가이드라인:
1. 오직 읽기(MATCH) 쿼리만 작성하세요. (CUD 명령어 절대 금지)
2. [특정 조문 지정 질문]: 사용자가 특정 법령이나 조번호를 명시했다면 (예: "공무원보수규정 제8조에 대해 알려줘"), 
   해당 ARTICLE 노드를 매칭하고, **그 조문이 참조하고 있는 타 조문들까지 함께 가져오는 쿼리**를 작성하세요.
   예시 형태:
   MATCH (a:ARTICLE) WHERE a.id = "공무원보수규정::제8조"
   OPTIONAL MATCH (a)-[:REFERENCE]->(ref:ARTICLE)
   RETURN a.id AS id, a.name AS name, a.description AS description, 1.0 AS score
   UNION
   MATCH (a:ARTICLE)-[:REFERENCE]->(ref:ARTICLE) WHERE a.id = "공무원보수규정::제8조"
   RETURN ref.id AS id, ref.name AS name, ref.description AS description, 0.9 AS score

3. [주제/의미 검색 질문]: 명시된 법령명이나 조번호가 없고 일반적인 내용 질문이라면, 아래의 벡터 검색 형태를 사용하세요:
   CALL db.index.vector.queryNodes('article_vector_index', $top_k,$query_embedding)
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

    def _vector_fallback(self, user_query: str, top_k: int) -> list[dict]:
        embedding = self.client.embeddings.create(
            model=EMBEDDING_MODEL, input=[user_query]
        ).data[0].embedding

        cypher = """
        CALL db.index.vector.queryNodes('article_vector_index', $top_k, $query_embedding)
        YIELD node, score
        RETURN node.id AS id, node.name AS name, node.description AS description, score
        ORDER BY score DESC
        """
        with self.driver.session(database=self.database) as session:
            results = session.run(cypher, top_k=top_k, query_embedding=embedding)
            return [dict(r) for r in results]

    def retrieve(self, user_query: str, top_k: int = 5) -> list[dict]:
        """참조 문서(조문) 목록을 반환. text-to-Cypher 우선, 실패하거나 결과가 없으면 벡터 검색으로 폴백."""
        cypher = self._generate_cypher(user_query)

        if not self._is_safe_cypher(cypher):
            return self._vector_fallback(user_query, top_k)

        params = {"top_k": top_k}
        if "query_embedding" in cypher:
            params["query_embedding"] = self.client.embeddings.create(
                model=EMBEDDING_MODEL, input=[user_query]
            ).data[0].embedding

        try:
            with self.driver.session(database=self.database) as session:
                results = session.run(cypher, **params)
                rows = [dict(r) for r in results]
        except Exception:
            # 쿼리 문법 에러 등이 나면 안전하게 벡터로 폴백
            return self._vector_fallback(user_query, top_k)

        # 결과가 하나도 없으면 의미적 유사도 검색으로 전환
        if not rows:
            return self._vector_fallback(user_query, top_k)

        return rows