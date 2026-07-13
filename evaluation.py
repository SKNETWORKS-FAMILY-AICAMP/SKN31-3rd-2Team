# evaluation.py 상단에 넣을 코드
from run_chatbot import LangGraphChatbot

# 객체 생성 후 바로 호출 가능
bot = LangGraphChatbot(verbose=True)
references, answer = bot.ask("병장 월급 얼마에요")