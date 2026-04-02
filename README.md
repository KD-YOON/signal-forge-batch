# Signal Forge Batch Full v5

추가/개선 사항
- KIS 접근토큰 실행당 1회만 발급
- 뉴스 검색어 강화 (주식/주가/실적/수주/증권)
- 블랙리스트 + 화이트리스트 + 관련도 점수 강화
- 뉴스가 애매하면 '관련 투자 뉴스 부족' fallback
- top 1 + top 2 후보 함께 표시
- lunch / evening / auto 모드 지원
- Cron 1개로 12시/18시 운영 가능

## Render 권장 설정
Build Command:
pip install -r requirements.txt

Command:
python app/jobs.py auto

Schedule:
0 12,18 * * *

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
