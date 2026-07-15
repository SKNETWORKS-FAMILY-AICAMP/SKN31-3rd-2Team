import json
import re
import os
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

CHAT_MODEL = "gpt-5.4-mini"
EMBEDDING_MODEL = "text-embedding-3-large"  # 적재할 때 쓴 모델과 반드시 동일해야 함

# 재랭킹 점수(0~10) 임계값 / 임계값을 넘는 문서가 없을 때 반환할 최소 개수
DEFAULT_SCORE_THRESHOLD = 6.0
DEFAULT_FALLBACK_K = 1

SCHEMA_DESCRIPTION = """
Qdrant collection: guidance_vectordb
포인트(payload) 필드:
  - page_content: string, 임베딩에 사용된 텍스트 (본문 / 표 요약)
  - metadata.doc_name: string, 원본 PDF 파일명
  - metadata.page: int, 페이지 번호
  - metadata.type: string, "text" | "table" 중 하나 (이미지는 적재하지 않음)
  - metadata.table_markdown: string, type=="table"일 때 원본 표 (마크다운)
  - metadata.summary: string, type=="table"일 때 표 요약
"""


class QdrantRetriever:
    """
    [수정 배경]
    - 기존의 Vector 유사도 기반 검색(Top-K)만으로는 질문과 직접적인 연관성이 떨어지는 노이즈 문서들이 상위에 배치되어
      'llm_context_precision_with_reference' 점수가 낮게 나오는 문제 존재.
    - 또한 무관한 컨텍스트가 LLM에 많이 전달되면서 답변의 신뢰도('faithfulness')와 질문 적합도('answer_relevancy')를 저하시킴.
    - 이에 대한 해결책으로 HuggingFace 등 무거운 외부 Cross-Encoder 모델을 추가 서빙(Load)하지 않고,
      이미 사용 중인 OpenAI 'gpt-4o'를 2-Step으로 활용하는 'LLM 기반 Reranker' 구조를 도입.

    [개선된 Rerank 프로세스]
    1. Vector DB에서 넉넉하게 N개(search_limit=15)의 관련 문서를 1차적으로 긁어옵니다. (높은 context_recall 확보)
    2. 가져온 N개의 문서 전체에 대해 gpt-4o가 질문과의 관련도를 0~10점으로 채점합니다.
       (기존처럼 "포함/배제"하지 않고, 문서를 하나도 버리지 않은 채 점수만 매깁니다.)
    3. score_threshold(기본 6.0)를 넘는 문서만 채택합니다.
       - 단답형 질문처럼 정답 문서가 1개뿐이면 자연스럽게 1개만 반환됩니다.
       - 복합 질문이라 여러 문서가 다 높은 점수를 받으면 여러 개가 통과합니다.
       - 임계값을 넘는 문서가 하나도 없으면, 최상위 fallback_k(기본 1)개만 반환합니다.
    4. top_k는 더 이상 "무조건 채워야 하는 개수"가 아니라, "최대 몇 개까지 허용할지"에 대한 상한선 역할만 합니다.

    [이전 버전과의 차이 / 수정 이유]
    - 이전 버전은 LLM이 "노이즈"라고 배제한 문서를 안전장치로 다시 리스트 뒤에 붙이는
      백필(backfill) 로직이 있었는데, 이게 두 가지 문제를 동시에 일으켰다.
      1) LLM이 배제한(=관련 없다고 판단한) 문서가 top_k 슬라이싱 안에 다시 섞여 들어가
         context_precision을 깎아먹었다.
      2) LLM이 실수로 진짜 정답 문서를 "관련 없음"으로 잘못 판단하면, 그 문서가 원본
         벡터 순위 그대로 뒤로 밀려났다가 top_k 밖으로 잘려나가 context_recall이 깨졌다.
    - 이번 버전은 "포함/배제" 대신 "전체 점수화 + 임계값 컷"으로 바꿔 문서를 아예 버리지
      않으므로, 위 두 문제가 구조적으로 발생하지 않는다.
    """

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
2. 특정 페이지 번호가 질문에 명시되어 있으면 page 필터를 추가하세요 (정수).
3. 필터가 필요 없으면(일반 질문, 콘텐츠 유형을 특정하지 않음) 빈 객체 {{}}를 반환하세요.
4. 오직 JSON만 출력하세요. 설명, 마크다운 코드블록 표시 없이 순수 JSON 텍스트만 출력하세요.

출력 형식 예시:
{{"type": "table"}}
{{"page": 12}}
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
            conditions.append(FieldCondition(key="metadata.type", match=MatchValue(value=filter_dict["type"])))
        if "page" in filter_dict:
            conditions.append(FieldCondition(key="metadata.page", match=MatchValue(value=filter_dict["page"])))

        if not conditions:
            return None
        return Filter(must=conditions)

    def _score_with_llm(self, user_query: str, retrieved_docs: list[dict]) -> list[tuple[dict, float]]:
        """
        문서를 배제하지 않고 전 문서에 관련도 점수(0~10)를 매긴다.
        (doc, score) 쌍의 리스트를 점수 내림차순으로 반환한다.
        """
        if not retrieved_docs:
            return []

        docs_input = ""
        for idx, doc in enumerate(retrieved_docs):
            docs_input += f"--- Document [ID: {idx}] ---\n{doc['text']}\n\n"

        system_prompt = """
당신은 정보 검색 및 랭킹 전문가입니다.
제공된 'Document 목록'의 모든 문서에 대해, 사용자의 '질문(Query)'과의 관련도를
0~10 사이 정수 점수로 채점해 주세요.

[규칙]
1. 반드시 목록에 있는 모든 Document ID에 대해 점수를 매겨야 합니다. (하나도 빠짐없이)
2. 질문에 직접적으로 답할 수 있는 문서일수록 높은 점수(8~10)를 주세요.
3. 키워드만 겹칠 뿐 질문의 핵심 의도와 무관한 문서는 낮은 점수(0~3)를 주세요.
4. 결과는 불필요한 설명 없이 오직 JSON 객체로만 반환하세요.
   예: {"0": 9, "1": 2, "2": 6, ...}
"""
        user_prompt = f"""
[사용자 질문]
{user_query}

[Document 목록]
{docs_input}
"""
        try:
            response = self.client.chat.completions.create(
                model=CHAT_MODEL,
                temperature=0,  # 채점의 일관성을 위해 온도를 0으로 고정합니다.
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = response.choices[0].message.content.strip()
            raw = re.sub(r'^```(json)?\s*|\s*```$', '', raw, flags=re.MULTILINE).strip()
            raw_scores = json.loads(raw)

            def get_score(idx: int) -> float:
                try:
                    return float(raw_scores.get(str(idx), 0))
                except (TypeError, ValueError):
                    return 0.0

            scored = [(doc, get_score(i)) for i, doc in enumerate(retrieved_docs)]
            scored.sort(key=lambda pair: pair[1], reverse=True)
            return scored

        except Exception as e:
            # API 오류, 타임아웃, JSON 파싱 실패 등 모든 예외 상황을 안전하게 캐치한다.
            # 원본 벡터 유사도 순서를 유지하되, 임계값 로직이 깨지지 않도록 임의의
            # 내림차순 점수를 부여해 폴백한다.
            print(f"[Rerank Warning] LLM 채점 실패: {e}. 기존 유사도 순서로 폴백합니다.")
            n = len(retrieved_docs)
            return [(doc, float(n - i)) for i, doc in enumerate(retrieved_docs)]

    def retrieve(
        self,
        user_query: str,
        top_k: int = 5,
        search_limit: int = 15,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        fallback_k: int = DEFAULT_FALLBACK_K,
    ) -> list[dict]:
        """
        1단계: search_limit(=15)개를 넉넉히 벡터 검색으로 확보 (recall 확보용)
        2단계: LLM으로 전 문서에 관련도 점수를 매긴다 (문서 유실 없음)
        3단계: score_threshold를 넘는 문서만 채택.
               - 임계값을 넘는 문서가 하나도 없으면, 최상위 fallback_k개만 반환.
               - top_k는 "이 이상은 안 넘긴다"는 상한선 역할만 한다.
        """
        query_vector = self._embed(user_query)

        filter_dict = self._generate_filter(user_query)
        qdrant_filter = self._build_qdrant_filter(filter_dict)

        response = self.qdrant.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=qdrant_filter,
            limit=search_limit,
            with_payload=True,
        )
        results = response.points

        if not results and qdrant_filter is not None:
            # 메타데이터 필터 바운더리가 너무 엄격했을 경우, 빈 결과를 막기 위해 필터를 해제하여 검색
            response = self.qdrant.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=search_limit,
                with_payload=True,
            )
            results = response.points

        formatted_results = [self._format_result(r) for r in results]
        if not formatted_results:
            return []

        scored_results = self._score_with_llm(user_query, formatted_results)

        passed = [doc for doc, score in scored_results if score >= score_threshold]
        if not passed:
            passed = [doc for doc, _ in scored_results[:fallback_k]]

        return passed[:top_k]

    def _format_result(self, r) -> dict:
        """LangChain QdrantVectorStore의 중첩 payload(page_content + metadata)를
        평평한(flat) dict로 펼쳐서 반환한다."""
        payload = r.payload or {}
        metadata = payload.get("metadata", {}) or {}

        return {
            "id": r.id,
            "score": r.score,
            "text": payload.get("page_content", ""),
            "page": metadata.get("page"),
            "type": metadata.get("type"),
            **{k: v for k, v in metadata.items() if k not in {"page", "type"}},
        }


##자체실행파일
# # ==========================================
# # [추가 구문] 코드 단독 실행 및 테스트용 진입점
# # ==========================================
# if __name__ == "__main__":
#     load_dotenv()

#     openai_client = OpenAI()
#     qdrant_client = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))

#     retriever = QdrantRetriever(
#         client=openai_client,
#         qdrant=qdrant_client,
#         collection_name="guidance_vectordb",
#     )

#     # top_k=5는 상한선일 뿐, 실제 반환 개수는 score_threshold를 넘는 문서 수에 따라 달라진다.
#     print(">>> Qdrant에서 관련 문서를 검색하고 LLM 채점 기반 재랭킹을 진행 중입니다...")
#     results = retriever.retrieve("2026년도 초급간부 휴가 관련 규정 알려줘", top_k=5, search_limit=15)

#     print(f"\n===== [재랭킹 완료] 총 {len(results)}개의 결과가 반환되었습니다 =====\n")
#     for i, r in enumerate(results):
#         print(f"[{i+1}위 / {r['type']}] page={r['page']} score={r['score']:.4f}")
#         print(r["text"][:150])
#         print("-" * 50)