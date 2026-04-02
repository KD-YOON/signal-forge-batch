from __future__ import annotations

from statistics import mean


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_mean(values: list[float]) -> float:
    cleaned = [float(v) for v in values if v is not None]
    return mean(cleaned) if cleaned else 0.0


def linear_slope(values: list[float]) -> float:
    vals = [float(v) for v in values]
    n = len(vals)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2
    y_mean = sum(vals) / n
    num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(vals))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / den if den else 0.0


def build_obv_series(closes_oldest_first: list[float], vols_oldest_first: list[float]) -> list[float]:
    if not closes_oldest_first or len(closes_oldest_first) != len(vols_oldest_first):
        return []
    obv = [0.0]
    for i in range(1, len(closes_oldest_first)):
        prev = closes_oldest_first[i - 1]
        curr = closes_oldest_first[i]
        vol = float(vols_oldest_first[i] or 0)
        if curr > prev:
            obv.append(obv[-1] + vol)
        elif curr < prev:
            obv.append(obv[-1] - vol)
        else:
            obv.append(obv[-1])
    return obv


def calc_stop_loss(entry_price: float, quote_low: float | None = None) -> int:
    entry = float(entry_price or 0)
    low = float(quote_low or 0)
    if entry <= 0:
        return 0
    hard = entry * 0.96
    if low > 0:
        return int(round(min(hard, low * 0.995)))
    return int(round(hard))


def calc_targets(entry_price: float, stage: str) -> tuple[int, int]:
    entry = float(entry_price or 0)
    if entry <= 0:
        return 0, 0
    if stage == "EARLY_ACCUMULATION":
        return int(round(entry * 1.04)), int(round(entry * 1.07))
    if stage == "BREAKOUT_READY":
        return int(round(entry * 1.03)), int(round(entry * 1.06))
    if stage == "MOMENTUM_BUY":
        return int(round(entry * 1.025)), int(round(entry * 1.05))
    return int(round(entry * 1.03)), int(round(entry * 1.05))


def calc_entry_zone(prev_close: float, pullback_pct: float = -5.0, near_pct: float = 1.2) -> dict:
    prev_close = float(prev_close or 0)
    if prev_close <= 0:
        return {
            "prev_close": 0,
            "proposed_entry": 0,
            "zone_low": 0,
            "zone_high": 0,
        }
    proposed = prev_close * (1 + pullback_pct / 100)
    zone_low = proposed * (1 - near_pct / 100)
    zone_high = proposed * (1 + near_pct / 100)
    return {
        "prev_close": prev_close,
        "proposed_entry": int(round(proposed)),
        "zone_low": int(round(zone_low)),
        "zone_high": int(round(zone_high)),
    }


def detect_accumulation_signals(daily: list[dict], quote: dict) -> dict:
    rows = [x for x in (daily or []) if float(x.get("close", 0) or 0) > 0][:30]
    if len(rows) < 20:
        return {"score": 0, "flags": []}

    closes = [float(x.get("close", 0) or 0) for x in rows]
    highs = [float(x.get("high", 0) or 0) for x in rows]
    lows = [float(x.get("low", 0) or 0) for x in rows]
    opens = [float(x.get("open", 0) or 0) for x in rows]
    vols = [float(x.get("volume", 0) or 0) for x in rows]

    score = 0
    flags: list[str] = []

    high20 = max(highs[:20])
    low20 = min(lows[:20])
    range_pct20 = ((high20 - low20) / low20 * 100) if low20 > 0 else 999
    avg_vol_10 = safe_mean(vols[:10])
    avg_vol_prev = safe_mean(vols[10:30])
    price = float(quote.get("price", 0) or 0)
    price_near_top = (price / high20 * 100) if high20 > 0 else 0

    if range_pct20 <= 12 and avg_vol_10 > avg_vol_prev * 1.15 and price_near_top >= 94:
        score += 12
        flags.append("박스권압축+거래증가")
    elif range_pct20 <= 16 and avg_vol_10 > avg_vol_prev * 1.05 and price_near_top >= 92:
        score += 6
        flags.append("약한박스매집")

    up_vol = 0.0
    down_vol = 0.0
    up_move = 0.0
    down_move = 0.0
    for i in range(min(len(rows) - 1, 15)):
        diff = closes[i] - closes[i + 1]
        if diff >= 0:
            up_vol += vols[i]
            up_move += diff
        else:
            down_vol += vols[i]
            down_move += abs(diff)

    if up_vol > down_vol * 1.3 and up_move >= down_move * 0.9:
        score += 10
        flags.append("상승봉거래우위")
    elif up_vol > down_vol * 1.1:
        score += 5
        flags.append("약한수급우위")

    oldest_closes = list(reversed(closes))
    oldest_vols = list(reversed(vols))
    obv_series = build_obv_series(oldest_closes, oldest_vols)
    obv_slope = linear_slope(obv_series[-15:])
    price_slope = linear_slope(oldest_closes[-15:])

    if obv_slope > 0 and price_slope >= -0.05:
        score += 14
        flags.append("OBV상승다이버전스")
    elif obv_slope > 0:
        score += 7
        flags.append("OBV완만상승")

    upper_close_count = 0
    small_upper_wick_count = 0
    for i in range(min(len(rows), 10)):
        h, l, c, o = highs[i], lows[i], closes[i], opens[i]
        rng = h - l
        pos = ((c - l) / rng * 100) if rng > 0 else 50
        upper_wick = h - max(c, o)
        if pos >= 65:
            upper_close_count += 1
        if rng > 0 and upper_wick / rng <= 0.25:
            small_upper_wick_count += 1

    if upper_close_count >= 7 and small_upper_wick_count >= 6:
        score += 8
        flags.append("종가상단고정")
    elif upper_close_count >= 5:
        score += 4
        flags.append("종가강세유지")

    high30 = max(highs)
    near_high_pct = (price / high30 * 100) if high30 > 0 else 0
    recent_pullback = ((high30 - price) / high30 * 100) if high30 > 0 else 999
    if near_high_pct >= 97 and recent_pullback <= 3 and avg_vol_10 > avg_vol_prev:
        score += 15
        flags.append("신고가직전체류")
    elif near_high_pct >= 94 and recent_pullback <= 5:
        score += 8
        flags.append("고점부근체류")

    return {"score": int(round(score)), "flags": flags}


def detect_breakout_signals(daily: list[dict], quote: dict, vol_rate: float) -> dict:
    rows = (daily or [])[:20]
    if not rows:
        return {"score": 0, "flags": []}

    highs = [float(x.get("high", 0) or 0) for x in rows if float(x.get("high", 0) or 0) > 0]
    lows = [float(x.get("low", 0) or 0) for x in rows if float(x.get("low", 0) or 0) > 0]
    closes = [float(x.get("close", 0) or 0) for x in rows if float(x.get("close", 0) or 0) > 0]

    score = 0
    flags: list[str] = []

    high20 = max(highs) if highs else 0
    low20 = min(lows) if lows else 0
    price = float(quote.get("price", 0) or 0)
    day_high = float(quote.get("high", 0) or 0)
    day_open = float(quote.get("open", 0) or 0)
    prev_close = float(closes[1] if len(closes) > 1 else closes[0] if closes else 0)
    gap_pct = ((day_open - prev_close) / prev_close * 100) if prev_close > 0 else 0

    if high20 > 0 and price >= high20 * 0.995:
        score += 12
        flags.append("20일고점근접")

    if high20 > 0 and day_high >= high20 and price >= high20 * 0.99:
        score += 10
        flags.append("돌파시도")

    high_retention = (price / day_high * 100) if day_high > 0 else 0
    if high_retention >= 97:
        score += 8
        flags.append("고가유지강함")
    elif high_retention >= 94:
        score += 4
        flags.append("고가유지양호")

    if vol_rate > 220:
        score += 8
        flags.append("거래량폭발")
    elif vol_rate > 150:
        score += 4
        flags.append("거래량증가")

    if low20 > 0 and high20 > 0:
        range_pct = ((high20 - low20) / low20) * 100
        if range_pct <= 20 and price >= high20 * 0.995:
            score += 5
            flags.append("좁은범위돌파형")

    if gap_pct >= 2.5 and high_retention >= 95:
        score += 6
        flags.append("갭업후고가유지")
    elif gap_pct >= 2.5 and high_retention < 93:
        score -= 6
        flags.append("갭업후윗꼬리주의")

    return {"score": int(round(score)), "flags": flags}


def detect_risk_signals(daily: list[dict], quote: dict, rsi: float, vol_rate: float) -> dict:
    score = 0
    flags: list[str] = []
    change_pct = float(quote.get("change_pct", 0) or 0)
    price = float(quote.get("price", 0) or 0)
    day_high = float(quote.get("high", 0) or 0)
    day_low = float(quote.get("low", 0) or 0)
    day_open = float(quote.get("open", 0) or 0)

    if rsi >= 80:
        score += 10
        flags.append("RSI과열")
    elif rsi >= 75:
        score += 6
        flags.append("RSI고열")

    if change_pct >= 18:
        score += 12
        flags.append("당일급등과열")
    elif change_pct >= 12:
        score += 7
        flags.append("상승과열")

    if vol_rate >= 300:
        score += 8
        flags.append("거래량과열")

    if day_high > 0:
        retention = price / day_high * 100
        if retention < 94:
            score += 8
            flags.append("고가유지약함")
        elif retention < 97:
            score += 4
            flags.append("고가유지보통")

    if day_high > 0 and day_low > 0 and day_open > 0:
        rng = day_high - day_low
        upper_wick = day_high - max(price, day_open)
        if rng > 0 and (upper_wick / rng) * 100 >= 40 and vol_rate >= 180:
            score += 8
            flags.append("분배형윗꼬리")

    return {"score": int(round(score)), "flags": flags}


def compute_weighted_stage_score(
    early_score: float,
    breakout_score: float,
    theme_score: float,
    sentiment_adj: float,
    risk_score: float,
) -> int:
    score = 20 + early_score + breakout_score + theme_score + sentiment_adj - 1.3 * risk_score
    return int(round(clamp(score, 0, 100)))


def decide_stage_label(
    early_score: float,
    breakout_score: float,
    risk_score: float,
    theme_score: float,
    total_score: float,
    rsi: float,
    vol_rate: float,
) -> str:
    if total_score < 55:
        return "PASS"
    if breakout_score >= 24 and risk_score <= 18 and total_score >= 72 and vol_rate >= 160 and rsi >= 55:
        return "MOMENTUM_BUY"
    if early_score >= 16 and breakout_score >= 14 and risk_score <= 18 and vol_rate >= 120:
        return "BREAKOUT_READY"
    if theme_score >= 8 and early_score >= 16 and risk_score <= 18 and vol_rate >= 120:
        return "BREAKOUT_READY"
    if early_score >= 20 and breakout_score <= 17 and risk_score <= 14 and (rsi == 0 or (38 <= rsi <= 68)):
        return "EARLY_ACCUMULATION"
    return "WATCH"


def evaluate_entry_timing(
    stage: str,
    accumulation_score: float,
    breakout_score: float,
    risk_score: float,
    rsi: float,
    vol_rate: float,
    change_pct: float,
    sentiment_score: float = 0.0,
    sentiment_confidence: float = 50.0,
    news_trade_pass: bool = False,
    news_trade_bias: str = "NEUTRAL",
) -> dict:
    entry_score = 50.0
    reason = "기본 관찰"

    if stage == "EARLY_ACCUMULATION":
        entry_score += 14
        reason = "매집 구간 우위"
    elif stage == "BREAKOUT_READY":
        entry_score += 18
        reason = "돌파 준비형"
    elif stage == "MOMENTUM_BUY":
        entry_score += 10
        reason = "모멘텀 강함"

    entry_score += min(12, accumulation_score * 0.35)
    entry_score += min(14, breakout_score * 0.45)
    entry_score -= min(22, risk_score * 0.9)

    if 42 <= rsi <= 68:
        entry_score += 8
    elif rsi >= 75:
        entry_score -= 10
        reason = "RSI 과열"
    elif rsi < 35:
        entry_score -= 4

    if change_pct >= 15:
        entry_score -= 15
        reason = "당일 급등으로 추격 위험 큼"
    elif change_pct >= 10:
        entry_score -= 8
        reason = "당일 상승폭 커서 분할 접근 필요"

    if vol_rate > 320:
        entry_score -= 10
        reason = "거래량 과열 가능성"
    elif 110 <= vol_rate <= 220:
        entry_score += 4

    entry_score = clamp(round(entry_score), 0, 100)
    decision = "WAIT"

    if entry_score >= 68 and risk_score <= 14 and stage in ("EARLY_ACCUMULATION", "BREAKOUT_READY"):
        decision = "ENTRY"
    elif entry_score >= 52 and risk_score <= 20:
        decision = "WAIT"
    else:
        decision = "PASS"

    if (
        sentiment_score >= 70 and sentiment_confidence >= 65 and news_trade_pass
        and risk_score <= 16 and change_pct <= 9 and rsi < 75 and stage != "PASS"
    ):
        decision = "ENTRY"
        reason = "감성 강세 + 뉴스 필터 통과로 즉시 진입 우선"

    if stage == "MOMENTUM_BUY" and change_pct >= 10 and rsi >= 75:
        decision = "PASS"
        reason = "모멘텀 구간이지만 추격 위험이 커서 패스"

    if stage == "EARLY_ACCUMULATION" and accumulation_score >= 22 and risk_score <= 10 and change_pct <= 5:
        decision = "ENTRY"
        reason = "조기 매집형 우수, 선매수 유리"

    if news_trade_bias == "NEGATIVE":
        decision = "PASS"
        reason = "부정 뉴스로 매수 차단"

    return {
        "decision": decision,
        "reason": reason,
        "score": int(entry_score),
    }


def analyze_stage_signals(item: dict, quote: dict, daily: list[dict], news_signal: dict | None = None) -> dict:
    news_signal = news_signal or {}
    closes_oldest = [float(x.get("close", 0) or 0) for x in reversed(daily or []) if float(x.get("close", 0) or 0) > 0]
    daily_volumes = [float(x.get("volume", 0) or 0) for x in (daily or []) if float(x.get("volume", 0) or 0) >= 0]
    rsi = float(item.get("rsi", 50) or 50)
    vol_rate = float(item.get("vol_rate", 0) or 0)

    accumulation = detect_accumulation_signals(daily, quote)
    breakout = detect_breakout_signals(daily, quote, vol_rate)
    risk = detect_risk_signals(daily, quote, rsi, vol_rate)

    early_score = accumulation["score"]
    if 42 <= rsi <= 65:
        early_score += 6
    elif rsi < 35:
        early_score += 3
    if 110 <= vol_rate <= 220:
        early_score += 6
    elif vol_rate > 220:
        early_score += 2

    breakout_score = breakout["score"]
    change_pct = float(quote.get("change_pct", 0) or 0)
    if vol_rate > 200:
        breakout_score += 12
    elif vol_rate > 150:
        breakout_score += 8
    elif vol_rate > 120:
        breakout_score += 4

    if 2 < change_pct < 15:
        breakout_score += 12
    elif change_pct >= 15:
        breakout_score -= 8
    elif change_pct < -3:
        breakout_score -= 6

    risk_score = risk["score"]
    theme_score = 10 if ("AI" in str(item.get("theme", "")) or "반도체" in str(item.get("theme", ""))) else 4 if str(item.get("theme", "")).strip() else 0
    sentiment_adj = int(news_signal.get("score", 0) or 0)

    total_score = compute_weighted_stage_score(early_score, breakout_score, theme_score, sentiment_adj, risk_score)
    stage = decide_stage_label(early_score, breakout_score, risk_score, theme_score, total_score, rsi, vol_rate)

    entry = evaluate_entry_timing(
        stage=stage,
        accumulation_score=accumulation["score"],
        breakout_score=breakout_score,
        risk_score=risk_score,
        rsi=rsi,
        vol_rate=vol_rate,
        change_pct=change_pct,
        sentiment_score=70 if news_signal.get("bias") == "POSITIVE" else 0,
        sentiment_confidence=65 if news_signal.get("bias") == "POSITIVE" else 50,
        news_trade_pass=news_signal.get("bias") == "POSITIVE",
        news_trade_bias=str(news_signal.get("bias", "NEUTRAL")),
    )

    prev_close = float(closes_oldest[-1] if closes_oldest else quote.get("price", 0) or 0)
    entry_zone = calc_entry_zone(prev_close)
    stop_loss = calc_stop_loss(float(quote.get("price", 0) or 0), float(quote.get("low", 0) or 0))
    target1, target2 = calc_targets(float(quote.get("price", 0) or 0), stage)

    return {
        "accumulation_score": int(accumulation["score"]),
        "accumulation_flags": accumulation["flags"],
        "breakout_score": int(breakout_score),
        "breakout_flags": breakout["flags"],
        "risk_score": int(risk_score),
        "risk_flags": risk["flags"],
        "theme_score": int(theme_score),
        "sentiment_adj": int(sentiment_adj),
        "total_score": int(total_score),
        "stage": stage,
        "entry_score": int(entry["score"]),
        "entry_decision": entry["decision"],
        "entry_reason": entry["reason"],
        "proposed_entry": entry_zone["proposed_entry"],
        "entry_zone_low": entry_zone["zone_low"],
        "entry_zone_high": entry_zone["zone_high"],
        "prev_close": entry_zone["prev_close"],
        "stop_loss": stop_loss,
        "target1": target1,
        "target2": target2,
    }
