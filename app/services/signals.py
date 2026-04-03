def analyze_stage_signals(item: dict) -> dict:
    rsi = float(item.get("rsi", 50) or 50)
    change_pct = float(item.get("change_pct", 0) or 0)
    vol_rate = float(item.get("vol_rate", 0) or 0)
    rebound = float(item.get("rebound_from_low", 0) or 0)

    stage = "NEUTRAL"
    reason = []

    if rsi < 35:
        stage = "BOTTOM"
        reason.append("RSI 과매도")
        if rebound >= 1.0:
            stage = "BOTTOM_REBOUND"
            reason.append("저점 반등 시작")
    elif 35 <= rsi <= 65:
        stage = "TREND"
        reason.append("정상 추세 구간")
        if change_pct > 2:
            stage = "TREND_STRONG"
            reason.append("상승 강도 있음")
    elif rsi > 70:
        stage = "OVERHEAT"
        reason.append("과열 구간")

    if vol_rate > 200:
        reason.append("거래량 강세")

    return {
        "stage": stage,
        "stage_reason": ", ".join(reason) if reason else "기본 상태",
    }


def decide_stage_label(item: dict) -> str:
    stage_info = analyze_stage_signals(item)
    stage = stage_info.get("stage", "NEUTRAL")

    label_map = {
        "BOTTOM": "바닥 탐색",
        "BOTTOM_REBOUND": "반등 시작",
        "TREND": "추세 유지",
        "TREND_STRONG": "강한 추세",
        "OVERHEAT": "과열 주의",
        "NEUTRAL": "중립",
    }
    return label_map.get(stage, "중립")


def compute_weighted_stage_score(item: dict) -> float:
    stage_info = analyze_stage_signals(item)
    stage = stage_info.get("stage", "NEUTRAL")

    base_map = {
        "BOTTOM": 20.0,
        "BOTTOM_REBOUND": 35.0,
        "TREND": 45.0,
        "TREND_STRONG": 55.0,
        "OVERHEAT": 15.0,
        "NEUTRAL": 30.0,
    }

    score = base_map.get(stage, 30.0)

    rsi = float(item.get("rsi", 50) or 50)
    vol_rate = float(item.get("vol_rate", 0) or 0)
    change_pct = float(item.get("change_pct", 0) or 0)
    rebound = float(item.get("rebound_from_low", 0) or 0)

    if 45 <= rsi <= 65:
        score += 10
    elif rsi < 35:
        score -= 5
    elif rsi > 75:
        score -= 8

    if 120 <= vol_rate <= 250:
        score += 10
    elif vol_rate > 250:
        score += 4

    if 0.3 <= change_pct <= 3.5:
        score += 8
    elif change_pct < -3:
        score -= 6
    elif change_pct > 6:
        score -= 5

    if rebound >= 1.0:
        score += 6
    if rebound >= 2.0:
        score += 4

    return round(score, 1)


def build_stage_comment(item: dict) -> str:
    stage_info = analyze_stage_signals(item)
    stage = stage_info.get("stage", "NEUTRAL")
    reason = stage_info.get("stage_reason", "")

    comment_map = {
        "BOTTOM": "바닥 탐색 구간",
        "BOTTOM_REBOUND": "저점 반등 확인 구간",
        "TREND": "무난한 추세 구간",
        "TREND_STRONG": "강한 추세 구간",
        "OVERHEAT": "과열 주의 구간",
        "NEUTRAL": "중립 구간",
    }

    head = comment_map.get(stage, "중립 구간")
    return f"{head} / {reason}".strip(" /")
