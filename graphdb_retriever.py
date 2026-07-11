import re
from openai import OpenAI
from neo4j import GraphDatabase

CHAT_MODEL = "gpt-4o"
EMBEDDING_MODEL = "text-embedding-3-small"

FORBIDDEN_KEYWORDS = {"CREATE", "DELETE", "SET", "MERGE", "REMOVE", "DROP", "DETACH"}

SCHEMA_DESCRIPTION = """
노드 라벨: ARTICLE (법령 조문)
속성:
  - id: string, 형식 "법령명(대통령령)(제N호)(날짜)::제N조"
  - name: string, 조문 제목
  - description: string, 조문 본문 내용
  - original_id: string, 조번호만 (예: "제31조")
  - source_pdf: string, 원본 법령명

벡터 인덱스: article_vector_index (embedding 속성 기준, 의미 검색용)
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
        system_prompt = f"""
당신은 Neo4j Cypher 쿼리를 작성하는 전문가입니다.
아래 스키마만을 근거로, 사용자 질문에 답하기 위한 Cypher 쿼리를 작성하세요.

{SCHEMA_DESCRIPTION}

규칙:
1. 오직 읽기 쿼리만 작성하세요. CREATE/DELETE/SET/MERGE는 절대 금지.
2. 조번호나 법령명이 질문에 명시되어 있으면 CONTAINS로 텍스트 매칭하세요.
3. 명시된 조번호/법령명이 없고 주제/내용 기반 질문이면 아래 형태의 벡터 검색을 쓰세요:
   CALL db.index.vector.queryNodes('article_vector_index', $top_k, $query_embedding)
   YIELD node, score
   RETURN node.id AS id, node.name AS name, node.description AS description, score
   ORDER BY score DESC
4. 쿼리만 출력하세요. 설명이나 마크다운 코드블록 표시 없이 순수 Cypher 텍스트만 출력하세요.
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

    def retrieve(self, user_query: str, top_k: int = 3) -> list[dict]:
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
            return self._vector_fallback(user_query, top_k)

        # 핵심 수정: 쿼리는 성공했지만 결과가 0건이면 벡터 검색으로 폴백
        if not rows:
            return self._vector_fallback(user_query, top_k)

        return rows