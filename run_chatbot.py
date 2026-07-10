import os
from openai import OpenAI
from neo4j import GraphDatabase
from dotenv import load_dotenv

from retriever import Neo4jRetriever, CHAT_MODEL

load_dotenv()

TARGET_DATABASE = "lawdb"


class ChatbotPipeline:
    """검색(retriever) + 생성(LLM)을 묶은 파이프라인"""

    def __init__(self, client: OpenAI, retriever: Neo4jRetriever):
        self.client = client
        self.retriever = retriever

    def _build_context(self, search_data: list[dict]) -> str:
        blocks = [
            f"[{r.get('id', '')}] {r.get('name', '')}\n{r.get('description', '')}"
            for r in search_data
        ]
        return "\n\n---\n\n".join(blocks)

    def answer(self, user_query: str, top_k: int = 3) -> str:
        search_data = self.retriever.retrieve(user_query, top_k=top_k)

        if not search_data:
            context_text = "(참조할 문서를 찾지 못했습니다.)"
        else:
            context_text = self._build_context(search_data)

        system_prompt = (
            "당신은 초급간부와 병사를 위한 군 생활 법률·규정 안내 챗봇입니다. "
            "참조 문서 내용을 바탕으로 자연스럽게 설명하고, 조문 번호를 나열하지 마세요. "
            "근거 조문은 답변 끝에 짧게만 덧붙이세요. "
            "참조 문서에 없는 내용은 지어내지 마세요."
        )
        response = self.client.chat.completions.create(
            model=CHAT_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"[참조 문서]\n{context_text}\n\n[질문]\n{user_query}"},
            ],
        )
        return response.choices[0].message.content


def main():
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )

    retriever = Neo4jRetriever(client=client, driver=driver, database=TARGET_DATABASE)
    pipeline = ChatbotPipeline(client=client, retriever=retriever)

    print("💬 군 생활 법률·규정 챗봇입니다. 종료하려면 'exit' 입력하세요.\n")

    try:
        while True:
            user_input = input("질문: ").strip()
            if user_input.lower() in {"exit", "quit"}:
                break
            if not user_input:
                continue

            answer = pipeline.answer(user_input)
            print(f"\n답변: {answer}\n")
    finally:
        driver.close()


if __name__ == "__main__":
    main()