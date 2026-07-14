@echo off
:: 1. 배치 파일이 있는 진짜 최상위 폴더로 이동
cd /d "%~dp0"

:: 2. 지금 폴더의 가상환경 파이썬(.venv)을 콕 집어서, 그걸로 스트림릿 실행하기
.\.venv\Scripts\python.exe -m streamlit run app/app.py

pause