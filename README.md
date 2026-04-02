# Signal Forge Batch Full v4

변경사항
- KIS 접근토큰 1회 발급 후 재사용
- 불필요한 뉴스 필터링
- auto / lunch / evening 모드 지원
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
