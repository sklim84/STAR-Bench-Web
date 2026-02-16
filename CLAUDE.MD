# Project: AML Assistant Platform
- 에이전트를 활용하여 자금세탁의심거래를 분석하는 웹 서비스
- 기능1 : 대시보드 형태로 자금세탁의심거래들의 기본 분석 정보 출력
- 기능2 : 대시보드 형태로 자금세탁의심거래들의 네트워크(그래프) 분석 정보 출력
- 기능3 : AI 모델(부스팅 모델) 기반 자금세탁의심거래 학습 및 탐지(확률)
- 기능4 : 에이전트와 대화를 통해 기능1, 기능2, 기능3을 활용하여 자금세탁의심거래들을 분석하고, Suspicious Transaction Report 작성
## Tech Stack
- **Frontend**: streamlit 등
- **Backend**: FastAPI, PostgreSQL, OpenAI API, Claude API 등
## Project Structure
- `/_datasets`: 자금세탁의심거래 (HOFINET.csv)
## Coding Standards
- 지나친 예외처리 하지 않기
- 구조화된 코드 작성하기
## DO NOT
- Never commit `.env` files
- Never expose API keys in client code
## Common Commands
- 