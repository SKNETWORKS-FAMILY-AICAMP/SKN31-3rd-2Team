import json
import re
from typing import Optional

from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

CHAT_MODEL = "gpt-4o"
EMBEDDING_MODEL = "text-embedding-3-large"  # 적재할 때 쓴 모델과 반드시 동일해야 함

SCHEMA_DESCRIPTION = """
Qdrant collection: GUIDANCE
포인트(payload) 필드:
  - doc_name: string, 원본 PDF 파일명
  - page: int, 페이지 번호
  - type: string, "text" | "table" | "image" 중 하나
  - text: string, 임베딩에 사용된 텍스트 (본문 / 표 요약 / 이미지 캡션)
  - content: string, type=="text"일 때 원본 본문 전체
  - table_markdown: string, type=="table"일 때 원본 표 (마크다운)
  - summary: string, type=="table"일 때 표 요약
  - image_path: string, type=="image"일 때 이미지 파일 경로
  - caption: string, type=="image"일 때 이미지 캡션
"""


class QdrantRetriever:
    """사용자 질문을 받아 Qdrant(GUIDANCE)에서 관련 청크를 가져오는 retriever.
    LLM으로 payload 필터(type/page)를 먼저 추론한 뒤 벡터 검색을 수행하고,
    필터 적용 결과가 없으면 필터 없이 재검색(폴백)한다."""

    def __init__(self, client: OpenAI, qdrant: QdrantClient, collection_name: str):
        self.client = client
        self.qdrant = qdrant
        self.collection_name = collection_name

    def _embed(self, text: str) -> list[float]:
        response = self.client.embeddings.create(model=EMBEDDING_MODEL, input=[text])
        return response.data[0].embedding

    def _generate_filter(self, user_query: str) -> Optional[dict]:
        """질문 내용을 보고 type/page 필터가 필요한지 LLM으로 판단. 필요 없으면 빈 dict."""
        system_prompt = f"""
당신은 벡터DB 검색 필터를 설계하는 전문가입니다.
아래 스키마만을 근거로, 사용자 질문에 필요한 필터를 JSON으로 작성하세요.

{SCHEMA_DESCRIPTION}

규칙:
1. 사용자가 "표", "테이블", "표로", "수치표" 등을 명시적으로 요구하면 type="table".
2. 사용자가 "그림", "이미지", "사진", "그래프", "도표(이미지 형태)" 등을 명시적으로 요구하면 type="image".
3. 특정 페이지 번호가 질문에 명시되어 있으면 page 필터를 추가하세요 (정수).
4. 필터가 필요 없으면(일반 질문, 콘텐츠 유형을 특정하지 않음) 빈 객체 {{}}를 반환하세요.
5. 오직 JSON만 출력하세요. 설명, 마크다운 코드블록 표시 없이 순수 JSON 텍스트만 출력하세요.

출력 형식 예시:
{{"type": "table"}}
{{"page": 12}}
{{"type": "image", "page": 5}}
{{}}
"""
        response = self.client.chat.completions.create(
            model=CHAT_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query},
            ],
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r'^```(json)?\s*|\s*```$', '', raw, flags=re.MULTILINE).strip()

        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

        return parsed or None

    def _build_qdrant_filter(self, filter_dict: Optional[dict]) -> Optional[Filter]:
        if not filter_dict:
            return None

        conditions = []
        if "type" in filter_dict:
            conditions.append(FieldCondition(key="type", match=MatchValue(value=filter_dict["type"])))
        if "page" in filter_dict:
            conditions.append(FieldCondition(key="page", match=MatchValue(value=filter_dict["page"])))

        if not conditions:
            return None
        return Filter(must=conditions)

    def retrieve(self, user_query: str, top_k: int = 5) -> list[dict]:
        """관련 청크(텍스트/표/이미지) 목록을 반환.
        LLM 필터 추론을 우선 적용하고, 결과가 없으면 필터 없이 재검색한다."""
        query_vector = self._embed(user_query)

        filter_dict = self._generate_filter(user_query)
        qdrant_filter = self._build_qdrant_filter(filter_dict)

        response = self.qdrant.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=qdrant_filter,
            limit=top_k,
            with_payload=True,
        )
        results = response.points

        if not results and qdrant_filter is not None:
            # 필터가 너무 좁았을 수 있으니 필터 없이 재검색
            response = self.qdrant.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=top_k,
                with_payload=True,
            )
            results = response.points

        return [
            {
                "id": r.id,
                "score": r.score,
                "page": r.payload.get("page"),
                "type": r.payload.get("type"),
                "text": r.payload.get("text"),
                **{k: v for k, v in r.payload.items() if k not in {"page", "type", "text"}},
            }
            for r in results
        ]


if __name__ == "__main__":
    # 사용 예시
    openai_client = OpenAI()
    qdrant_client = QdrantClient(url="http://localhost:6333")

    retriever = QdrantRetriever(
        client=openai_client,
        qdrant=qdrant_client,
        collection_name="GUIDANCE",
    )

    results = retriever.retrieve("2026년도 초급간부 휴가 관련 규정 알려줘", top_k=5)
    for r in results:
        print(f"[{r['type']}] page={r['page']} score={r['score']:.3f}")
        print(r["text"][:150])
        print("-" * 40)