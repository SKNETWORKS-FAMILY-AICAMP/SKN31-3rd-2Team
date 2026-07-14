import json
import re
import os
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

CHAT_MODEL = "gpt-4o"
EMBEDDING_MODEL = "text-embedding-3-large"  # 적재할 때 쓴 모델과 반드시 동일해야 함

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
    2. 가져온 N개의 문서를 gpt-4o에게 보내어 질문과의 실질적 '연관성 및 중요도'를 기준으로 정렬 및 필터링하도록 지시합니다.
    3. 정렬된 문서 중 최상위 K개(top_k=5)만 최종적으로 슬라이싱하여 LLM 답변 생성용 컨텍스트로 제공합니다.
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

    def _rerank_with_llm(self, user_query: str, retrieved_docs: list[dict]) -> list[dict]:
        """
        [수정사항: LLM 기반 자체 Rerank 메서드 추가]
        - Vector DB의 밀도 낮은 단순 코사인 유사도를 보완하기 위해, LLM의 문맥 이해 능력을 이용해 2차 정렬을 수행합니다.
        - 외부 오픈소스 리랭커 모델 로드가 불가능한 인프라 제약 상황에서 가장 안정적이고 성능이 뛰어난 대안입니다.
        - 질문과 전혀 어울리지 않는 노이즈 문서를 순위에서 강제로 제외하거나 뒤로 배치하여, 
          최종 프롬프트에 들어갈 컨텍스트의 밀도(Context Precision)를 대폭 끌어올립니다.
        """
        if not retrieved_docs:
            return []
        
        # LLM에게 순위를 매기도록 넘겨줄 후보 문서 목록을 포맷팅합니다.
        docs_input = ""
        for idx, doc in enumerate(retrieved_docs):
            docs_input += f"--- Document [ID: {idx}] ---\n{doc['text']}\n\n"

        system_prompt = """
당신은 정보 검색 및 랭킹 전문가입니다.
제공된 'Document 목록'에서 사용자의 '질문(Query)'과 실질적으로 가장 연관성이 높고 질문에 정확하게 답할 수 있는 문서들의 ID 목록을 관련성 순서대로 나열해 주세요.

[규칙]
1. 반드시 질문에 도움을 주는 우선순위가 높은 순서대로 정렬해야 합니다.
2. 질문에 전혀 쓸모없는 정보이거나 관련이 없는 노이즈 문서의 ID는 결과 리스트에서 과감히 배제하세요.
3. 결과는 불필요한 사설 없이 오직 JSON 리스트 형태로만 반환하세요. (예: [3, 0, 2])
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
                temperature=0,  # 랭킹의 일관성을 위해 온도를 0으로 고정합니다.
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = response.choices[0].message.content.strip()
            raw = re.sub(r'^```(json)?\s*|\s*```$', '', raw, flags=re.MULTILINE).strip()
            
            # 정렬된 ID(인덱스) 리스트 파싱
            ranked_indices = json.loads(raw)
            
            # 파싱 데이터 안정성 검증 후 재배치 실행
            if isinstance(ranked_indices, list):
                reranked_docs = []
                seen_indices = set()
                
                # 1. LLM이 우수하다고 1차 판정한 문서들을 순서대로 배치
                for idx in ranked_indices:
                    try:
                        idx_int = int(idx)
                        if 0 <= idx_int < len(retrieved_docs) and idx_int not in seen_indices:
                            reranked_docs.append(retrieved_docs[idx_int])
                            seen_indices.add(idx_int)
                    except (ValueError, TypeError):
                        continue
                
                # 2. 혹시나 LLM의 응답 누락으로 인해 누락된 문서가 있다면, 
                #    검색 정밀도가 완전히 망가지는 것을 방지하기 위해 백업용으로 원본 순서대로 뒤에 붙여줍니다.
                for idx, doc in enumerate(retrieved_docs):
                    if idx not in seen_indices:
                        reranked_docs.append(doc)
                        
                return reranked_docs
                
        # API 오류, 네트워크 연결 지연(Timeout), 잘못된 JSON 포맷 리턴 등 모든 예외 상황을 안전하게 캐치합니다.
        except Exception as e:
            # LLM API 일시적 오류 혹은 파싱 실패 시, 시스템 다운을 막기 위해 
            # 기존 Vector DB 유사도 원본 순서(Fallback)를 반환하도록 안전 조치합니다.
            print(f"[Rerank Warning] LLM Reranking 실패: {e}. 안전을 위해 기존 유사도 순서로 검색 결과를 보존하여 서빙합니다.")
            return retrieved_docs

        # 파싱 결과가 정상 리스트가 아닌 경우 등 예상치 못한 흐름에 대비한 최후의 안전장치 백업 리턴입니다.
        return retrieved_docs

    def retrieve(self, user_query: str, top_k: int = 5, search_limit: int = 15) -> list[dict]:
        """
        [수정사항: 2단계 검색 구조 도입 및 리트리브 핵심 함수 추가]
        - 기존: `limit=top_k`를 활용하여 처음부터 타이트하게 K개만 가져옴.
        - 변경: 
          1단계: `limit=search_limit` (N=15)개 만큼 넉넉하게 긁어와서 질문에 꼭 필요한 핵심 정보가 
                 포함되도록 우선 확보합니다. (context_recall 향상 및 보존)
          2단계: `_rerank_with_llm` 메서드를 거치며 알짜배기 순서대로 정렬 및 노이즈 필터링을 수행합니다.
          3단계: 최종 정렬 완료된 고품질 문서 중 딱 `top_k` (K=5)개만 슬라이싱하여 LLM 생성을 위한 재료로 반환합니다.
        """
        query_vector = self._embed(user_query)

        filter_dict = self._generate_filter(user_query)
        qdrant_filter = self._build_qdrant_filter(filter_dict)

        # 1차 검색 시 search_limit (N) 만큼 여유 있게 확보
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

        # 2차 검색 정렬: LLM을 이용해 랭킹 재배정 수행
        reranked_results = self._rerank_with_llm(user_query, formatted_results)

        # 최종 사용 용도에 맞는 top_k (K)개 만큼만 슬라이싱하여 반환
        return reranked_results[:top_k]

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


# ==========================================
# [추가 구문] 코드 단독 실행 및 테스트용 진입점
# ==========================================
if __name__ == "__main__":
    load_dotenv()

    openai_client = OpenAI()
    qdrant_client = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))

    retriever = QdrantRetriever(
        client=openai_client,
        qdrant=qdrant_client,
        collection_name="guidance_vectordb",
    )

    # top_k=5로 최종 출력하지만, 내부적으로는 15개(search_limit)를 먼저 가져온 후
    # gpt-4o가 질문과의 실질적 관련성이 높은 5개만 정렬하여 최종 반환합니다.
    print(">>> Qdrant에서 관련 문서를 검색하고 LLM Reranking을 진행 중입니다...")
    results = retriever.retrieve("2026년도 초급간부 휴가 관련 규정 알려줘", top_k=5, search_limit=15)
    
    print(f"\n===== [LLM Rerank 완료] 총 {len(results)}개의 결과가 반환되었습니다 =====\n")
    for i, r in enumerate(results):
        print(f"[{i+1}위 / {r['type']}] page={r['page']} score={r['score']:.4f}")
        print(r["text"][:150])
        print("-" * 50)