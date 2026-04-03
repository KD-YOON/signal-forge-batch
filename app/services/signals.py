def _safe_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _as_dict(value):
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    if hasattr(value, "to_dict"):
        try:
            converted = value.to_dict()
            if isinstance(converted, dict):
                return converted
        except Exception:
            pass

    return {}


def _normalize_item(item: dict, quote: dict = None, daily: dict = None, news_signal: dict = None) -> dict:
    item = _as_dict(item)
    quote = _as_dict(quote)
    daily = _as_dict(daily)
    news_signal = _as_dict(news_signal)

    merged = {}
    merged.update(daily)
    merged.update(quote)
    merged.update(item)

    if "price" not in merged:
        merged["price"] = (
            quote.get("price")
            or item.get("price")
            or item.get("close")
            or daily.get("close")
            or 0
        )

    if "prev_close" not in merged:
        merged["prev_close"] = (
            quote.get("prev_close")
            or item.get("prev_close")
            or daily.get("prev_close")
            or 0
        )

    if "change_pct" not in merged:
        price = _safe_float(merged.get("price"), 0)
        prev_close = _safe_float(merged.get("prev_close"), 0)
        merged["change_pct"] = ((price - prev_close) / prev_close) * 100 if prev_close > 0 else 0

    if "vol_rate" not in merged:
        merged["vol_rate"] = (
            merged.get("volume_ratio")
            or quote.get("volume_ratio")
            or daily.get("volume_ratio")
            or daily.get("vol_rate")
            or item.get("vol_rate")
            or 0
        )

    if "rebound_from_low" not in merged:
        low = _safe_float(merged.get("low") or daily.get("low"), 0)
        price = _safe_float(merged.get("price") or merged.get("close"), 0)
        merged["rebound_from_low"] = ((price - low) / low) * 100 if low > 0 else 0

    if "rsi" not in merged:
        merged["rsi"] = item.get("rsi") or daily.get("rsi") or quote.get("rsi") or 50

    news_score = (
        news_signal.get("score")
        or news_signal.get("signal_score")
        or news_signal.get("sentiment_score")
        or 0
    )
    merged["news_score"] = _safe_float(news_score, 0)

    return merged


def _classify_stage(item: dict):
    rsi = _safe_float(item.get("rsi", 50), 50)
    change_pct = _safe_float(item.get("change_pct", 0), 0)
    vol_rate = _safe_float(item.get("vol_rate", 0), 0)
    rebound = _safe_float(item.get("rebound_from_low", 0), 0)
    news_score = _safe_float(item.get("news_score", 0), 0)

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

    if news_score >= 60:
        reason.append("뉴스 긍정 신호")

    return stage, reason


def analyze_stage_signals(item: dict, quote: dict = None, daily: dict = None, news_signal: dict = None) -> dict:
    normalized = _normalize_item(item, quote, daily, news_signal)
    stage, reason = _classify_stage(normalized)

    return {
        "stage": stage,
        "stage_reason": ", ".join(reason) if reason else "기본 상태",
        "stage_score": compute_weighted_stage_score(normalized),
        "stage_label": decide_stage_label(normalized),
        "stage_comment": build_stage_comment(normalized),
    }


def decide_stage_label(item) -> str:
    if isinstance(item, dict):
        stage, _ = _classify_stage(item)
        label_map = {
            "BOTTOM": "바닥 탐색",
            "BOTTOM_REBOUND": "반등 시작",
            "TREND": "추세 유지",
            "TREND_STRONG": "강한 추세",
            "OVERHEAT": "과열 주의",
            "NEUTRAL": "중립",
        }
        return label_map.get(stage, "중립")

    score = _safe_float(item, 0)
    if score >= 80:
        return "강매수"
    if score >= 60:
        return "매수관심"
    if score >= 40:
        return "관심"
    return "관망"


def compute_weighted_stage_score(
    item: dict = None,
    early_score: float = None,
    breakout_score: float = None,
    news_score: float = None,
    risk_score: float = None,
    **kwargs,
) -> float:
    # 1) reporter.py 쪽에서 개별 점수 인자로 호출하는 경우
    if early_score is not None or breakout_score is not None or news_score is not None or risk_score is not None:
        e = _safe_float(early_score, 0)
        b = _safe_float(breakout_score, 0)
        n = _safe_float(news_score, 0)
        r = _safe_float(risk_score, 0)

        score = 35 + e + b + n - r
        score = max(0, min(100, score))
        return round(score, 1)

    # 2) analyze_stage_signals 내부에서 item dict로 호출하는 경우
    item = _as_dict(item)
    stage, _ = _classify_stage(item)

    base_map = {
        "BOTTOM": 20.0,
        "BOTTOM_REBOUND": 35.0,
        "TREND": 45.0,
        "TREND_STRONG": 55.0,
        "OVERHEAT": 15.0,
        "NEUTRAL": 30.0,
    }

    score = base_map.get(stage, 30.0)

    rsi = _safe_float(item.get("rsi", 50), 50)
    vol_rate = _safe_float(item.get("vol_rate", 0), 0)
    change_pct = _safe_float(item.get("change_pct", 0), 0)
    rebound = _safe_float(item.get("rebound_from_low", 0), 0)
    news_score_val = _safe_float(item.get("news_score", 0), 0)

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

    if 60 <= news_score_val < 80:
        score += 4
    elif news_score_val >= 80:
        score += 7

    score = max(0, min(100, score))
    return round(score, 1)


def build_stage_comment(item: dict) -> str:
    stage, reason_list = _classify_stage(item)

    comment_map = {
        "BOTTOM": "바닥 탐색 구간",
        "BOTTOM_REBOUND": "저점 반등 확인 구간",
        "TREND": "무난한 추세 구간",
        "TREND_STRONG": "강한 추세 구간",
        "OVERHEAT": "과열 주의 구간",
        "NEUTRAL": "중립 구간",
    }

    head = comment_map.get(stage, "중립 구간")
    reason = ", ".join(reason_list) if reason_list else ""
    return f"{head} / {reason}".strip(" /")
