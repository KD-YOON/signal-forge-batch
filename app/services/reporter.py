from datetime import datetime

def build_report(mode: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""📊 Signal Forge 리포트
모드: {mode}
시각: {now}

🔥 테스트 종목
삼성전자 (005930)

💡 시스템 정상 작동 중
"""
