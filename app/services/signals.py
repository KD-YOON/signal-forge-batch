def analyze_stage_signals(item: dict) -> dict:
    """
    종목 상태를 단계별로 판단하는 핵심 로직
    → 향후 매수 신호 고도화용
    """

    rsi = float(item.get("rsi", 50) or 50)
    change_pct = float(item.get("change_pct", 0) or 0)
    vol_rate = float(item.get("vol_rate", 0) or 0)
    rebound = float(item.get("rebound_from_low", 0) or 0)

    stage = "NEUTRAL"
    reason = []

    # 🔥 1. 과매도 구간 (바닥 탐색)
    if rsi < 35:
        stage = "BOTTOM"
        reason.append("RSI 과매도")

        if rebound >= 1.0:
            stage = "BOTTOM_REBOUND"
            reason.append("저점 반등 시작")

    # 🔥 2. 정상 상승 구간
    elif 35 <= rsi <= 65:
        stage = "TREND"
        reason.append("정상 추세 구간")

        if change_pct > 2:
            stage = "TREND_STRONG"
            reason.append("상승 강도 있음")

    # 🔥 3. 과열 구간
    elif rsi > 70:
        stage = "OVERHEAT"
        reason.append("과열 구간")

    # 🔥 거래량 보정
    if vol_rate > 200:
        reason.append("거래량 강세")

    # 🔥 최종 판단
    return {
        "stage": stage,
        "stage_reason": ", ".join(reason)
    }
