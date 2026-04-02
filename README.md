# Render Signal Forge 리포트 v6

## 추가 기능
- 리포트 이름 변경: **Render Signal Forge 리포트**
- KIS 토큰 실행당 1회만 발급
- 뉴스 정밀 필터링
- top1 + 차순위 후보 표시
- Render에서 구현한 매수 타이밍 판단
  - 전일종가 기준 제안매수가(-5%)
  - 관심구간(±1%)
  - 당일 저점 대비 반등률
  - 진입/대기/관망 판단

## Render 권장 설정
Build Command:
`pip install -r requirements.txt`

Command:
`python app/jobs.py auto`

Schedule:
`0 12,18 * * *`
