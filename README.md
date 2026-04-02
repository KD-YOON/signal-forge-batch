# Signal Forge Batch Full

Render Cron Job용 국내주식 리포트 배치 앱입니다.

## 기능
- KIS 현재가 조회
- KIS 일봉 조회
- RSI / 거래량비 점수 계산
- 네이버 뉴스 2건 조회
- Gemini 뉴스 요약(키가 없으면 제목 fallback)
- 텔레그램 발송

## Render 설정
Build Command:
`pip install -r requirements.txt`

Start Command:
`python -m app.jobs manual`

예시 Schedule:
- 점심: `0 12 * * *`
- 저녁: `0 18 * * *`

## 필수 ENV
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- KIS_APP_KEY
- KIS_APP_SECRET

## 선택 ENV
- KIS_BASE_URL
- NAVER_CLIENT_ID
- NAVER_CLIENT_SECRET
- GEMINI_API_KEY
- CANDIDATES_JSON

## CANDIDATES_JSON 예시
[
  {"market":"KOR","code":"005930","name":"삼성전자","theme":"반도체 대형주"},
  {"market":"KOR","code":"000660","name":"SK하이닉스","theme":"AI 반도체"},
  {"market":"KOR","code":"035420","name":"NAVER","theme":"플랫폼/AI"}
]
