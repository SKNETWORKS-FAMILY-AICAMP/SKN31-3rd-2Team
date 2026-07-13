# SKN31-3rd-2Team

## 1. 팀 및 팀원 소개

| 박동관 | 고현아 | 김세희 | 이용혁 | 전서연 |
| :---: | :---: | :---: | :---: | :---: |
| <a href="https://github.com/Parkdongkwan"><img src="https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=GitHub&logoColor=white"/> | <a href="https://github.com/hellene0708-cyber"><img src="https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=GitHub&logoColor=white"/> | <a href="https://github.com/kimsehuikim"><img src="https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=GitHub&logoColor=white"/> | <a href="https://github.com/leeyonghyok"><img src="https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=GitHub&logoColor=white"/> |  <a href="https://github.com/sxoxyn"><img src="https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=GitHub&logoColor=white"/> |
|<img src="image/dg.png" width="150" height="150"> | <img src="image/ha.png" width="150" height="150"> | <img src="image/sh.png" width="150" height="150"> | <img src="image/yh.png" width="150" height="150"> | <img src="image/sy.png" width="150" height="150"> |
| <b>PM/BE</b>     |<b>FE</b>  |<b>BE</b>   |<b>BE</b>  | <b>BE/FE</b>   | | 

## 1.2 WBS

##  WBS 📅

| Phase | Task | Owner |
|:---:|:---|:---:|
| 🟢 | 주제 선정 | 전체 |
| 🟢 | 데이터 확보 및 청킹 | 전체 |
| 🔵 | Neo4j · Qdrant Retriever 구현 | 박동관 |
| 🔵 | 메모리 및 페르소나 구현 | 김세희 |
| 🔵 | 그래프 구조 및 라우팅 개선 | 전서연 |
| 🔵 | UI 및 백엔드 연동 | 고현아 |
| 🟣 | 모델 평가 | 이용혁 |
| 🟣 | README 작성 | 김세희, 전서연 |
| 🟣 | 발표 준비 | 전체 |

---

## 2. 프로젝트 개요.
## 2.1 프로젝트 소개
병영생활과 군 관련 규정 정보를 쉽고 정확하게 제공하기 위한 AI 기반 RAG(Retrieval-Augmented Generation) 챗봇입니다. 군 관련 정보는 법령, 행정규칙, 병영생활 길라잡이 등 여러 문서에 분산되어 있고, 기존 키워드 검색은 정확한 용어를 입력해야 하는 한계가 있습니다. 이를 해결하기 위해 Neo4j와 Qdrant를 활용한 하이브리드 검색을 적용하여 사용자 질문에 적합한 정보를 검색하고, LLM을 기반으로 신뢰도 높은 답변을 제공합니다.
- **Neo4j**를 활용하여 법률 및 규정의 관계를 기반으로 정확한 정보를 적재 및 검색
- **Qdrant**를 활용하여 병영생활 길라잡이 문서를 의미 기반(Vector Search)으로 적재 및 검색
- **LangGraph** 기반 워크플로우를 통해 검색 → 자료 참조 → 답변 생성 과정을 체계적으로 구성
- 검색된 문서를 기반으로 LLM이 신뢰도 높은 답변을 생성
- **단기기억** 과 RAG를 결합하여 대화 맥락과 검색 결과를 함께 반영
검색된 문서를 기반으로 LLM이 신뢰도 높은 답변을 생성


## 2.2 프로젝트 배경
군 장병들은 복무 중 궁금한 사항이 생겨도 선임이나 간부에게 먼저 물어보거나 여러 규정 문서를 직접 찾아봐야 하는 경우가 많습니다. 하지만 관련 정보는 법령, 행정규칙, 병영생활 길라잡이 등 여러 문서에 분산되어 있고, 법률 문서는 전문 용어와 조문 중심으로 작성되어 원하는 답을 찾는 데 많은 시간과 어려움이 따릅니다. 이에 장병들이 누구에게 묻지 않아도 자연어 질문만으로 필요한 정보를 쉽고 정확하게 확인할 수 있는 AI 기반 하이브리드 RAG 챗봇을 개발하게 되었습니다.

## 2.3 주요 기능 ✨
- **자연어 기반 질의응답**  
  사용자의 질문 의도를 파악해 자연스러운 답변을 제공합니다.

- **법률·규정 검색**  
  Neo4j를 활용해 군 관련 법령과 규정을 관계 기반으로 검색합니다.

- **병영생활 안내 검색**  
  Qdrant를 활용해 길라잡이 문서를 의미 기반으로 검색합니다.

- **하이브리드 RAG**  
  Neo4j와 Qdrant의 검색 결과를 결합해 신뢰도 높은 답변을 생성합니다.

## 2.4  Tech Stack 🛠

| Layer | Technology |
|:---|:---|
| Language | ![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white) |
| Frontend | ![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=flat-square&logo=streamlit&logoColor=white) |
| AI | ![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat-square&logo=openai&logoColor=white) ![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?style=flat-square&logo=langchain&logoColor=white) ![LangGraph](https://img.shields.io/badge/LangGraph-111111?style=flat-square) |
| Database | ![Qdrant](https://img.shields.io/badge/Qdrant-DC244C?style=flat-square&logo=qdrant&logoColor=white) ![Neo4j](https://img.shields.io/badge/Neo4j-4581C3?style=flat-square&logo=neo4j&logoColor=white) |
| Libraries | ![PyMuPDF](https://img.shields.io/badge/PyMuPDF-2C8EBB?style=flat-square&logo=adobeacrobatreader&logoColor=white) ![pdfplumber](https://img.shields.io/badge/pdfplumber-555555?style=flat-square&logo=adobeacrobatreader&logoColor=white) 



---

## 3. 프로젝트 구조 📂 (미정)

```text
```
---

## 5. 데이터 파이프라인

---

## 6. 실행 파이프라인

---

## 7. 수행 결과

---

## 8. 회고
#### 박동관
 - 

#### 고현아
  -

#### 김세희
 - 

#### 이용혁
 - 

#### 전서연
 - 
