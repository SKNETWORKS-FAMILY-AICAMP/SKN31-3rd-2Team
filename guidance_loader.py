#!/usr/bin/env python
# coding: utf-8

# ## 0. 패키지 설치

# In[ ]:


# 필요한 library: uv pip install pymupdf pdfplumber pillow openai qdrant-client langchain-core langchain-openai langchain-qdrant langchain-text-splitters python-dotenv


# ## 1. 설정 및 클라이언트 준비

# In[4]:


import os
import re
import glob
import uuid
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber
from PIL import Image
from openai import OpenAI
from dotenv import load_dotenv

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, Filter, FieldCondition, MatchValue

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

# ----- 설정값 -----
GUIDANCE_DIR = "./길라잡이"          # 이 폴더 안의 모든 PDF를 찾아서 적재

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
COLLECTION_NAME = "guidance_vectordb"

CHAT_MODEL = "gpt-5.4-mini"                          # 표 요약 / 이미지 캡션용
EMBED_MODEL = "text-embedding-3-large"         # large 임베딩 모델
EMBED_DIM = 3072

CHUNK_SIZE = 800       # 텍스트 청크 최대 글자 수 (splitter 기준)
CHUNK_OVERLAP = 150    # 청크 간 겹치는 글자 수 (문맥 끊김 방지)

openai_client = OpenAI()
qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
embeddings = OpenAIEmbeddings(model=EMBED_MODEL)


def ensure_collection():
    existing = [c.name for c in qdrant_client.get_collections().collections]
    if COLLECTION_NAME in existing:
        print(f"'{COLLECTION_NAME}' collection이 이미 존재합니다.")
        return
    qdrant_client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
    )
    print(f"'{COLLECTION_NAME}' collection 생성 완료 (dim={EMBED_DIM})")


ensure_collection()

vectorstore = QdrantVectorStore(
    client=qdrant_client,
    collection_name=COLLECTION_NAME,
    embedding=embeddings,
)

pdf_paths = sorted(glob.glob(str(Path(GUIDANCE_DIR) / "*.pdf")))
print(f"'{GUIDANCE_DIR}' 안에서 발견된 PDF {len(pdf_paths)}개")
for p in pdf_paths:
    print(" -", p)


# ## 2. 텍스트 정제

# In[5]:


def clean_text(text: str) -> str:
    # Private Use Area (U+E000–U+F8FF) 문자 제거
    text = re.sub(r'[\ue000-\uf8ff]', '', text)
    # 과도한 공백/빈 줄 정리
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ## 3. 표 추출 → 마크다운 → 요약 

# In[13]:


def table_to_markdown(table_rows):
    rows = [[cell if cell is not None else "" for cell in row] for row in table_rows]
    if not rows:
        return ""
    header = rows[0]
    body = rows[1:]
    md_lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * len(header)) + " |"]
    for row in body:
        md_lines.append("| " + " | ".join(row) + " |")
    return "\n".join(md_lines)


def extract_tables(pdf_path: str):
    tables_out = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue
                md_table = table_to_markdown(table)
                tables_out.append({"page": page_num, "markdown": md_table})
    return tables_out


def summarize_table(table_markdown: str) -> str:
    response = openai_client.chat.completions.create(
        model=CHAT_MODEL,
        max_completion_tokens=300,
        messages=[{
            "role": "user",
            "content": (
                "다음은 문서에서 추출한 표입니다. 이 표가 어떤 내용을 담고 있는지 "
                "검색에 활용할 수 있도록 2~4문장의 한국어로 요약해줘. "
                "컬럼이 의미하는 바와 주요 수치/항목을 포함해줘.\n\n"
                f"{table_markdown}"
            ),
        }],
    )
    return response.choices[0].message.content.strip()


# ## 4. 텍스트 청킹 (페이지 단위)
# 
# 이 PDF는 법령처럼 문장이 페이지를 넘어 쭉 이어지는 문서가 아니라, 페이지 하나하나가 그 자체로 하나의 토픽/안내 단위로 디자인된 문서입니다. 그래서 페이지 경계를 문맥 단위로 그대로 씁니다: **원칙적으로 한 페이지 = 한 청크**입니다.

# In[14]:


text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
)

# 이 길이를 넘는 페이지만 splitter로 추가 분할 (그 외엔 페이지 통째로 한 청크)
PAGE_OVERFLOW_THRESHOLD = 1200


def chunk_text_by_page(pdf_path: str) -> list[dict]:
    """페이지 단위로 청크를 만든다. 페이지가 너무 길 때만 그 페이지 안에서 추가로 나눈다."""
    doc = fitz.open(pdf_path)
    results = []

    for page_num, page in enumerate(doc, start=1):
        page_text = clean_text(page.get_text("text"))

        if not page_text:
            continue  # 텍스트 없는 페이지(이미지만 있는 페이지 등)는 건너뜀

        if len(page_text) <= PAGE_OVERFLOW_THRESHOLD:
            results.append({"page": page_num, "text": page_text})
        else:
            # 이 페이지만 너무 길어서 임베딩이 흐려질 수 있는 경우 -> 페이지 내부에서만 분할
            sub_chunks = text_splitter.split_text(page_text)
            for sub in sub_chunks:
                results.append({"page": page_num, "text": sub})

    doc.close()
    return results


# ## 6. PDF 1개 → LangChain `Document` 리스트로 통합

# In[15]:


ID_NAMESPACE = uuid.NAMESPACE_URL


def make_id(doc_name: str, chunk_type: str, index: int) -> str:
    """같은 PDF를 다시 적재해도 같은 ID가 나오도록 결정론적으로 생성 (재실행 시 upsert로 덮어씀)"""
    return str(uuid.uuid5(ID_NAMESPACE, f"{doc_name}::{chunk_type}::{index}"))


def build_documents_for_pdf(pdf_path: str) -> tuple[list[Document], list[str]]:
    doc_name = Path(pdf_path).name
    documents = []
    ids = []
    counter = 0

    # 1) 텍스트 청크
    text_chunks = chunk_text_by_page(pdf_path)
    for c in text_chunks:
        documents.append(Document(
            page_content=c["text"],
            metadata={"doc_name": doc_name, "page": c["page"], "type": "text"},
        ))
        ids.append(make_id(doc_name, "text", counter))
        counter += 1

    # 2) 표
    tables = extract_tables(pdf_path)
    for t in tables:
        summary = summarize_table(t["markdown"])
        documents.append(Document(
            page_content=summary,
            metadata={
                "doc_name": doc_name, "page": t["page"], "type": "table",
                "table_markdown": t["markdown"], "summary": summary,
            },
        ))
        ids.append(make_id(doc_name, "table", counter))
        counter += 1

    print(f"[{doc_name}] 텍스트 {len(text_chunks)} / 표 {len(tables)} → 총 {len(documents)}개")
    return documents, ids


# ## 7. 디렉토리 전체 적재 (upsert)
# 

# In[16]:


def upsert_documents(documents: list[Document], ids: list[str], batch_size: int = 100):
    for i in range(0, len(documents), batch_size):
        batch_docs = documents[i:i + batch_size]
        batch_ids = ids[i:i + batch_size]
        vectorstore.add_documents(documents=batch_docs, ids=batch_ids)
        print(f"  upsert 진행: {min(i + batch_size, len(documents))}/{len(documents)}")


def run_pipeline(directory: str = GUIDANCE_DIR):
    paths = sorted(glob.glob(str(Path(directory) / "*.pdf")))
    print(f"'{directory}'에서 PDF {len(paths)}개 발견, 적재 시작\n")

    total_chunks = 0
    for pdf_path in paths:
        documents, ids = build_documents_for_pdf(pdf_path)
        upsert_documents(documents, ids)
        total_chunks += len(documents)
        print()

    print(f"완료: PDF {len(paths)}개 / 총 {total_chunks}개 청크 적재")


# 실행
run_pipeline(GUIDANCE_DIR)


# ## 8. 검색 예시
# 
# `vectorstore.similarity_search`로 기본 검색, `filter`로 `type`(text/table/image) 등 메타데이터 필터링도 가능합니다.

# In[20]:


# def search(query: str, k: int = 5, type_filter: str = None):
#     qfilter = None
#     if type_filter:
#         qfilter = Filter(must=[FieldCondition(key="metadata.type", match=MatchValue(value=type_filter))])

#     results = vectorstore.similarity_search_with_score(query, k=k, filter=qfilter)

#     for doc, score in results:
#         print(f"[score={score:.3f}] doc={doc.metadata.get('doc_name')} page={doc.metadata.get('page')} type={doc.metadata.get('type')}")
#         print(doc.page_content[:200])
#         print("-" * 40)

#     return results


# # 사용 예시:
# search("군인 해택 휴양시설알려줘")
# # search("휴가 관련 표", type_filter="table")
# # search("기차 할인 안내 이미지", type_filter="image")


# # In[ ]:




