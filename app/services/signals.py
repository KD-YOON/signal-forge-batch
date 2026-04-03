from __future__ import annotations


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
            out = value.to_dict()
            if isinstance(out, dict):
                return out
        except Exception:
            pass
    return {}


def _clamp(value, low, high):
    return max(low, min(high, value))


def _normalize_item(item=None, quote=None, daily=None, news_signal=None):
    item = _as_dict(item)
    quote = _as_dict(quote)
    news_signal = _as_dict(news_signal)

    daily_rows = []
    if isinstance(daily, list):
        daily_rows = [x for x in daily if isinstance(x, dict)]
    elif isinstance(daily, dict):
        daily_rows = [daily]

    latest_daily = daily_rows[0] if daily_rows else {}

    merged = {}
    merged.update(latest_daily)
    merged.update(quote)
    merged.update(item)

    price = _safe_float(
        merged.get("price")
        or merged.get("close")
        or quote.get("price")
        or latest_daily.get("close"),
        0,
    )
    prev_close = _safe_float(
        merged.get("prev_close")
        or quote.get("prev_close")
        or latest_daily.get("close")
        or merged.get("close"),
        0,
    )
    open_price = _safe_float(
        merged.get("open")
        or quote.get("open")
        or latest_daily.get("open"),
        0,
    )
    high = _safe_float(
        merged.get("high")
        or quote.get("high")
        or latest_daily.get("high"),
        0,
    )
    low = _safe_float(
        merged.get("low")
        or quote.get("low")
        or latest_daily.get("low"),
        0,
    )
    volume = _safe_float(
        merged.get("volume")
        or quote.get("volume")
        or latest_daily.get("volume"),
        0,
    )

    closes, highs, lows, volumes = [], [], [], []
    for row in daily_rows:
        c = _safe_float(row.get("close"), 0)
        h = _safe_float(row.get("high"), 0)
        l = _safe_float(row.get("low"), 0)
        v = _safe_float(row.get("volume"), 0)
        if c > 0:
            closes.append(c)
        if h > 0:
            highs.append(h)
        if l > 0:
            lows.append(l)
        if v >= 0:
            volumes.append(v)

    ma5 = sum(closes[:5]) / len(closes[:5]) if closes[:5] else price
    ma20 = sum(closes[:20]) / len(closes[:20]) if closes[:20] else ma5
    ma60 = sum(closes[:60]) / len(closes[:60]) if closes[:60] else ma20
    recent_high_20 = max(highs[:20]) if highs[:20] else high
    recent_low_20 = min(lows[:20]) if lows[:20] else low
    avg_vol_20 = sum(volumes[:20]) / len(volumes[:20]) if volumes[:20] else 0

    change_pct = _safe_float(merged.get("change_pct"), default=None)
    if change_pct is None:
        change_pct = ((price - prev_close) / prev_close) * 100 if prev_close > 0 else 0

    vol_rate = _safe_float(merged.get("vol_rate"), default=None)
    if vol_rate is None:
        vol_rate = (volume / avg_vol_20 * 100) if avg_vol_20 > 0 else 0

    rebound_from_low = _safe_float(merged.get("rebound_from_low"), default=None)
    if rebound_from_low is None:
        rebound_from_low = ((price - recent_low_20) / recent_low_20) * 100 if recent_low_20 > 0 else 0

    news_score = _safe_float(
        news_signal.get("score")
        or news_signal.get("signal_score")
        or news_signal.get("sentiment_score"),
        0,
    )
    news_bias = str(news_signal.get("bias", "NEUTRAL")).upper().strip()

    merged.update(
        {
            "price": price,
            "prev_close": prev_close,
            "open": open_price,
            "high": high,
            "low": low,
            "volume": volume,
            "change_pct": round(change_pct, 2),
            "vol_rate": round(vol_rate, 1),
            "rebound_from_low": round(rebound_from_low, 2),
            "ma5": round(ma5, 2),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "recent_high_20": round(recent_high_20, 2),
            "recent_low_20": round(recent_low_20, 2),
            "news_score": round(news_score, 1),
            "news_bias": news_bias,
        }
    )
    return merged


def _build_component_scores(item):
    rsi = _safe_float(item.get("rsi"), 50)
    price = _safe_float(item.get("price"), 0)
    prev_close = _safe_float(item.get("prev_close"), 0)
    change_pct = _safe_float(item.get("change_pct"), 0)
    vol_rate = _safe_float(item.get("vol_rate"), 0)
    rebound = _safe_float(item.get("rebound_from_low"), 0)
    ma5 = _safe_float(item.get("ma5"), price)
    ma20 = _safe_float(item.get("ma20"), ma5)
    ma60 = _safe_float(item.get("ma60"), ma20)
    recent_high_20 = _safe_float(item.get("recent_high_20"), price)
    recent_low_20 = _safe_float(item.get("recent_low_20"), price)
    news_score = _safe_float(item.get("news_score"), 0)
    news_bias = str(item.get("news_bias", "NEUTRAL")).upper().strip()
    theme = str(item.get("theme", "")).lower()

    accumulation_flags = []
    breakout_flags = []
    risk_flags = []
    trend_flags = []

    accumulation_score = 0
    breakout_score = 0
    theme_score = 0
    sentiment_adj = 0
    risk_score = 0

    # 추세 정렬
    if ma5 > ma20 > ma60 and price >= ma20:
        accumulation_score += 8
        breakout_score += 10
        trend_flags.append("정배열")
    elif ma5 > ma20 and price >= ma20:
        accumulation_score += 5
        breakout_score += 5
        trend_flags.append("부분정렬")

    if price >= ma20:
        accumulation_score += 4
        trend_flags.append("가격>20일선")
    if price >= ma60:
        breakout_score += 4
        trend_flags.append("가격>60일선")
    else:
        risk_score += 5
        risk_flags.append("가격<60일선")

    # RSI / 반등
    if rsi < 35:
        accumulation_score += 14
        accumulation_flags.append("RSI과매도")
    elif 35 <= rsi <= 50:
        accumulation_score += 8
        accumulation_flags.append("저부담RSI")

    if rebound >= 1.0:
        accumulation_score += 8
        accumulation_flags.append("저점반등")
    if rebound >= 2.0:
        accumulation_score += 4

    # 거래량
    if 110 <= vol_rate <= 220:
        accumulation_score += 6
        breakout_score += 6
        accumulation_flags.append("거래량양호")
        breakout_flags.append("거래량동반")
    elif vol_rate > 220:
        breakout_score += 8
        breakout_flags.append("거래량급증")
    elif vol_rate < 80:
        risk_score += 4
        risk_flags.append("거래량부족")

    # 고점 근접 / 돌파
    if recent_high_20 > 0:
        dist_to_high = ((recent_high_20 - price) / recent_high_20) * 100
        if dist_to_high <= 1.5:
            breakout_score += 12
            breakout_flags.append("20일고점근접")
        elif dist_to_high <= 3.0:
            breakout_score += 8
            breakout_flags.append("고점접근")

    # 박스권 하단/상단
    if recent_low_20 > 0 and price <= recent_low_20 * 1.04:
        accumulation_score += 6
        accumulation_flags.append("지지권근접")

    # 상승률
    if 0.5 <= change_pct <= 4.5:
        breakout_score += 8
        breakout_flags.append("양호한상승률")
    elif change_pct > 12:
        risk_score += 7
        risk_flags.append("단기급등주의")
    elif change_pct > 18:
        risk_score += 12
        risk_flags.append("급등추격위험")
    elif change_pct < -4:
        risk_score += 6
        risk_flags.append("급락추세")

    # 뉴스 / 감성
    if news_bias == "POSITIVE":
        sentiment_adj += min(10, max(4, int(abs(news_score) / 2)))
    elif news_bias == "NEGATIVE":
        sentiment_adj -= min(12, max(6, int(abs(news_score) / 2)))
        risk_score += 8
        risk_flags.append("부정뉴스")

    # 테마
    for kw in ("ai", "반도체", "데이터센터", "전기차", "플랫폼", "전력", "해운"):
        if kw in theme:
            theme_score += 4

    # 과열
    if rsi >= 80:
        risk_score += 10
        risk_flags.append("RSI과열")
    elif rsi >= 75:
        risk_score += 6
        risk_flags.append("RSI고점")

    if vol_rate >= 300:
        risk_score += 8
        risk_flags.append("과열거래량")

    gap_pct = ((price - prev_close) / prev_close) * 100 if prev_close > 0 else 0
    if gap_pct >= 5:
        risk_score += 4
        risk_flags.append("갭상승과다")

    accumulation_score = int(_clamp(round(accumulation_score), 0, 30))
    breakout_score = int(_clamp(round(breakout_score), 0, 30))
    theme_score = int(_clamp(round(theme_score), 0, 15))
    sentiment_adj = int(_clamp(round(sentiment_adj), -15, 15))
    risk_score = int(_clamp(round(risk_score), 0, 30))

    return {
        "accumulation_score": accumulation_score,
        "breakout_score": breakout_score,
        "theme_score": theme_score,
        "sentiment_adj": sentiment_adj,
        "risk_score": risk_score,
        "accumulation_flags": accumulation_flags,
        "breakout_flags": breakout_flags,
        "risk_flags": risk_flags,
        "trend_flags": trend_flags,
    }


def compute_weighted_stage_score(
    item=None,
    early_score=None,
    breakout_score=None,
    theme_score=None,
    sentiment_adj=None,
    news_score=None,
    risk_score=None,
    **kwargs,
):
    # Apps Script computeWeightedStageScore_ 호환:
    # base 20 + early + breakout + theme + sentimentAdj - 1.3 * risk
    if isinstance(item, dict) and all(
        x is None for x in [early_score, breakout_score, theme_score, sentiment_adj, news_score, risk_score]
    ):
        normalized = _normalize_item(item)
        comp = _build_component_scores(normalized)
        e = _safe_float(comp["accumulation_score"], 0)
        b = _safe_float(comp["breakout_score"], 0)
        t = _safe_float(comp["theme_score"], 0)
        s = _safe_float(comp["sentiment_adj"], 0)
        r = _safe_float(comp["risk_score"], 0)
        total = 20 + e + b + t + s - 1.3 * r
        return round(_clamp(round(total), 0, 100), 1)

    e = _safe_float(early_score, 0)
    b = _safe_float(breakout_score, 0)
    t = _safe_float(theme_score, 0)
    s = _safe_float(sentiment_adj if sentiment_adj is not None else news_score, 0)
    r = _safe_float(risk_score, 0)
    total = 20 + e + b + t + s - 1.3 * r
    return round(_clamp(round(total), 0, 100), 1)


def _quality_score(item, comp, total_score):
    accumulation_score = _safe_float(comp["accumulation_score"], 0)
    early_score = _safe_float(comp["accumulation_score"], 0)
    breakout_score = _safe_float(comp["breakout_score"], 0)
    risk_score = _safe_float(comp["risk_score"], 0)
    theme_score = _safe_float(comp["theme_score"], 0)
    rsi = _safe_float(item.get("rsi"), 0)
    vol_rate = _safe_float(item.get("vol_rate"), 0)
    change_pct = _safe_float(item.get("change_pct"), 0)

    score = 50

    if accumulation_score >= 24:
        score += 16
    elif accumulation_score >= 18:
        score += 10
    elif accumulation_score >= 12:
        score += 5

    if early_score >= 22:
        score += 10
    elif early_score >= 16:
        score += 6

    if breakout_score >= 22:
        score += 8
    elif breakout_score >= 15:
        score += 4

    score -= risk_score * 0.8

    if rsi >= 80:
        score -= 12
    elif rsi >= 75:
        score -= 7

    if change_pct >= 18:
        score -= 14
    elif change_pct >= 12:
        score -= 8
    elif change_pct <= -4:
        score -= 5

    if 110 <= vol_rate <= 230:
        score += 8
    elif 230 < vol_rate <= 320:
        score += 2
    elif vol_rate > 320:
        score -= 8
    elif vol_rate < 80:
        score -= 6

    stage = decide_stage_label(
        early_score=early_score,
        breakout_score=breakout_score,
        risk_score=risk_score,
        theme_score=theme_score,
        total_score=total_score,
        rsi=rsi,
        vol_rate=vol_rate,
    )

    if stage == "EARLY_ACCUMULATION":
        score += 8
    elif stage == "BREAKOUT_READY":
        score += 6
    elif stage == "MOMENTUM_BUY":
        score -= 4
    elif stage == "WATCH":
        score -= 2
    elif stage == "PASS":
        score -= 20

    if theme_score >= 8 and accumulation_score < 12 and early_score < 14:
        score -= 8

    return int(_clamp(round(score), 0, 100))


def _quality_flags(item, comp):
    flags = []

    accumulation_score = _safe_float(comp["accumulation_score"], 0)
    early_score = _safe_float(comp["accumulation_score"], 0)
    breakout_score = _safe_float(comp["breakout_score"], 0)
    risk_score = _safe_float(comp["risk_score"], 0)
    rsi = _safe_float(item.get("rsi"), 0)
    vol_rate = _safe_float(item.get("vol_rate"), 0)
    change_pct = _safe_float(item.get("change_pct"), 0)
    theme_score = _safe_float(comp["theme_score"], 0)

    if accumulation_score >= 18:
        flags.append("매집근거양호")
    if early_score >= 18:
        flags.append("조기포착형")
    if breakout_score >= 18:
        flags.append("돌파준비형")

    if risk_score >= 18:
        flags.append("리스크높음")
    if rsi >= 75:
        flags.append("RSI과열주의")
    if change_pct >= 12:
        flags.append("급등추격주의")
    if vol_rate > 320:
        flags.append("과열거래량주의")
    if theme_score >= 8 and accumulation_score < 12:
        flags.append("뉴스의존주의")

    return flags


def _pass_quality_gate(item, comp, total_score, quality_score):
    stage = decide_stage_label(
        early_score=comp["accumulation_score"],
        breakout_score=comp["breakout_score"],
        risk_score=comp["risk_score"],
        theme_score=comp["theme_score"],
        total_score=total_score,
        rsi=item.get("rsi"),
        vol_rate=item.get("vol_rate"),
    )

    accumulation_score = _safe_float(comp["accumulation_score"], 0)
    early_score = _safe_float(comp["accumulation_score"], 0)
    breakout_score = _safe_float(comp["breakout_score"], 0)
    risk_score = _safe_float(comp["risk_score"], 0)
    theme_score = _safe_float(comp["theme_score"], 0)
    rsi = _safe_float(item.get("rsi"), 0)
    vol_rate = _safe_float(item.get("vol_rate"), 0)
    change_pct = _safe_float(item.get("change_pct"), 0)

    if stage == "PASS":
        return False
    if quality_score < 45:
        return False
    if risk_score >= 28:
        return False
    if rsi >= 84 and change_pct >= 10:
        return False
    if vol_rate > 420 and accumulation_score < 15:
        return False
    if theme_score >= 8 and accumulation_score < 10 and early_score < 12 and breakout_score < 12:
        return False

    if stage == "EARLY_ACCUMULATION":
        if accumulation_score >= 18 and early_score >= 16 and risk_score <= 14:
            return True
        return quality_score >= 55

    if stage == "BREAKOUT_READY":
        return breakout_score >= 16 and risk_score <= 18 and quality_score >= 55

    if stage == "MOMENTUM_BUY":
        return (
            breakout_score >= 22
            and risk_score <= 14
            and rsi < 78
            and change_pct < 12
            and quality_score >= 62
        )

    if stage == "WATCH":
        return quality_score >= 60 and accumulation_score >= 16 and risk_score <= 12

    return True


def decide_stage_label(
    item=None,
    early_score=None,
    breakout_score=None,
    risk_score=None,
    theme_score=None,
    total_score=None,
    rsi=None,
    vol_rate=None,
    **kwargs,
):
    if any(v is not None for v in [early_score, breakout_score, risk_score, theme_score, total_score, rsi, vol_rate]):
        early = _safe_float(early_score, 0)
        breakout = _safe_float(breakout_score, 0)
        risk = _safe_float(risk_score, 0)
        theme = _safe_float(theme_score, 0)
        total = _safe_float(total_score, 0)
        rsi_val = _safe_float(rsi, 0)
        vol_val = _safe_float(vol_rate, 0)

        if total < 55:
            return "PASS"

        if (
            breakout >= 24
            and risk <= 18
            and total >= 72
            and vol_val >= 160
            and rsi_val >= 55
        ):
            return "MOMENTUM_BUY"

        if (
            early >= 16
            and breakout >= 14
            and risk <= 18
            and vol_val >= 120
        ):
            return "BREAKOUT_READY"

        if (
            theme >= 8
            and early >= 16
            and risk <= 18
            and vol_val >= 120
        ):
            return "BREAKOUT_READY"

        if (
            early >= 20
            and breakout <= 17
            and risk <= 14
            and (rsi_val == 0 or (38 <= rsi_val <= 68))
        ):
            return "EARLY_ACCUMULATION"

        return "WATCH"

    if isinstance(item, dict):
        normalized = _normalize_item(item)
        comp = _build_component_scores(normalized)
        total = compute_weighted_stage_score(item=normalized)
        return decide_stage_label(
            early_score=comp["accumulation_score"],
            breakout_score=comp["breakout_score"],
            risk_score=comp["risk_score"],
            theme_score=comp["theme_score"],
            total_score=total,
            rsi=normalized.get("rsi"),
            vol_rate=normalized.get("vol_rate"),
        )

    total = _safe_float(item, 0)
    if total < 55:
        return "PASS"
    if total >= 72:
        return "BREAKOUT_READY"
    return "WATCH"


def _decide_entry_timing(item, comp, total_score, quality_score, stage):
    risk_score = _safe_float(comp["risk_score"], 0)
    accumulation_score = _safe_float(comp["accumulation_score"], 0)
    breakout_score = _safe_float(comp["breakout_score"], 0)
    rsi = _safe_float(item.get("rsi"), 0)
    vol_rate = _safe_float(item.get("vol_rate"), 0)
    change_pct = _safe_float(item.get("change_pct"), 0)
    sentiment_score = _safe_float(item.get("news_score"), 0)
    sentiment_confidence = 60 if abs(sentiment_score) > 0 else 0
    news_bias = str(item.get("news_bias", "NEUTRAL")).upper().strip()
    news_trade_pass = news_bias == "POSITIVE"
    sentiment_spike = sentiment_score >= 70 and sentiment_confidence >= 65

    entry_score = 50
    reason = "중립 구간"

    if total_score >= 75:
        entry_score += 12
    elif total_score >= 65:
        entry_score += 6

    if quality_score >= 70:
        entry_score += 12
    elif quality_score >= 60:
        entry_score += 6

    if accumulation_score >= 20:
        entry_score += 4
    if breakout_score >= 20:
        entry_score += 4

    if stage == "EARLY_ACCUMULATION":
        entry_score += 12
        if accumulation_score >= 20 and risk_score <= 12:
            reason = "조기 매집형으로 선매수 가능 구간"
        else:
            reason = "조기 매집형이지만 근거 보강 필요"

    if stage == "BREAKOUT_READY":
        entry_score += 8
        if breakout_score >= 18 and risk_score <= 16:
            reason = "돌파 준비형으로 분할 진입 가능"
        else:
            reason = "돌파 준비형이나 과열/리스크 확인 필요"

    if stage == "MOMENTUM_BUY":
        entry_score -= 6
        reason = "이미 분출 시작, 신규 진입은 보수적 접근 필요"

    if stage == "WATCH":
        entry_score -= 8
        reason = "아직 관찰 우선"

    if stage == "PASS":
        entry_score -= 30
        reason = "현재 진입 매력 낮음"

    if news_trade_pass:
        entry_score += 8
        reason = "뉴스 매수 필터 통과"

    if sentiment_score >= 70 and sentiment_confidence >= 65:
        entry_score += 14
        reason = "감성 강세로 ENTRY 우선권 부여"
    elif sentiment_score >= 50 and sentiment_confidence >= 55:
        entry_score += 8
    elif sentiment_score <= -40 and sentiment_confidence >= 50:
        entry_score -= 18
        reason = "부정 감성 강해 진입 보류"

    if sentiment_spike:
        entry_score += 6
        reason = "감성 급등으로 단기 모멘텀 우위"

    if news_bias == "NEGATIVE":
        entry_score -= 14
        reason = "뉴스 악재 필터에 걸려 보수적 접근"

    if rsi >= 80:
        entry_score -= 14
        reason = "RSI 과열 구간"
    elif rsi >= 75:
        entry_score -= 8
        reason = "RSI 높은 편, 추격 주의"

    if change_pct >= 15:
        entry_score -= 14
        reason = "당일 급등으로 추격 위험 큼"
    elif change_pct >= 10:
        entry_score -= 8
        reason = "당일 상승폭 커서 분할 접근 필요"

    if vol_rate > 320:
        entry_score -= 10
        reason = "거래량 과열 가능성"
    elif 110 <= vol_rate <= 220:
        entry_score += 4

    entry_score = int(_clamp(round(entry_score), 0, 100))

    decision = "WAIT"
    if entry_score >= 68 and risk_score <= 14 and stage in ("EARLY_ACCUMULATION", "BREAKOUT_READY"):
        decision = "ENTRY"
    elif entry_score >= 52 and risk_score <= 20:
        decision = "WAIT"
    else:
        decision = "PASS"

    if (
        sentiment_score >= 70
        and sentiment_confidence >= 65
        and news_trade_pass
        and risk_score <= 16
        and change_pct <= 9
        and rsi < 75
        and stage != "PASS"
    ):
        decision = "ENTRY"
        reason = "감성 강세 + 뉴스 필터 통과로 즉시 진입 우선"

    if (
        sentiment_spike
        and breakout_score >= 18
        and risk_score <= 16
        and change_pct <= 8
        and stage != "PASS"
    ):
        decision = "ENTRY"
        reason = "감성 급등 + 돌파 준비형 결합"

    if stage == "MOMENTUM_BUY" and change_pct >= 10 and rsi >= 75:
        decision = "PASS"
        reason = "모멘텀 구간이지만 추격 위험이 커서 패스"

    if stage == "EARLY_ACCUMULATION" and accumulation_score >= 22 and risk_score <= 10 and change_pct <= 5:
        decision = "ENTRY"
        reason = "조기 매집형 우수, 선매수 유리"

    if news_bias == "NEGATIVE":
        decision = "PASS"
        reason = "부정 뉴스/감성으로 매수 차단"

    return {
        "entry_decision": decision,
        "entry_reason": reason,
        "entry_score": entry_score,
    }


def _build_entry_plan(item):
    price = _safe_float(item.get("price"), 0)
    low = _safe_float(item.get("recent_low_20"), price)
    proposed_entry = int(round(price * 0.95)) if price > 0 else 0
    entry_zone_low = int(round(proposed_entry * 0.99)) if proposed_entry > 0 else 0
    entry_zone_high = int(round(proposed_entry * 1.01)) if proposed_entry > 0 else 0

    stop_base = min(low, proposed_entry * 0.96 if proposed_entry > 0 else 0)
    stop_loss = int(round(stop_base)) if stop_base > 0 else 0

    target1 = int(round(proposed_entry * 1.05)) if proposed_entry > 0 else 0
    target2 = int(round(proposed_entry * 1.10)) if proposed_entry > 0 else 0

    return {
        "proposed_entry": proposed_entry,
        "entry_zone_low": entry_zone_low,
        "entry_zone_high": entry_zone_high,
        "stop_loss": stop_loss,
        "target1": target1,
        "target2": target2,
    }


def build_stage_comment(item):
    normalized = _normalize_item(item)
    comp = _build_component_scores(normalized)
    total_score = compute_weighted_stage_score(item=normalized)
    stage = decide_stage_label(
        early_score=comp["accumulation_score"],
        breakout_score=comp["breakout_score"],
        risk_score=comp["risk_score"],
        theme_score=comp["theme_score"],
        total_score=total_score,
        rsi=normalized.get("rsi"),
        vol_rate=normalized.get("vol_rate"),
    )

    reasons = []
    if comp["accumulation_flags"]:
        reasons.append("매집:" + ",".join(comp["accumulation_flags"][:2]))
    if comp["breakout_flags"]:
        reasons.append("돌파:" + ",".join(comp["breakout_flags"][:2]))
    if comp["risk_flags"]:
        reasons.append("리스크:" + ",".join(comp["risk_flags"][:2]))

    tail = " / ".join(reasons) if reasons else "특이사항 없음"
    return f"{stage} / {tail}"


def analyze_stage_signals(item, quote=None, daily=None, news_signal=None):
    normalized = _normalize_item(item, quote, daily, news_signal)
    comp = _build_component_scores(normalized)

    total_score = compute_weighted_stage_score(
        early_score=comp["accumulation_score"],
        breakout_score=comp["breakout_score"],
        theme_score=comp["theme_score"],
        sentiment_adj=comp["sentiment_adj"],
        risk_score=comp["risk_score"],
    )

    stage = decide_stage_label(
        early_score=comp["accumulation_score"],
        breakout_score=comp["breakout_score"],
        risk_score=comp["risk_score"],
        theme_score=comp["theme_score"],
        total_score=total_score,
        rsi=normalized.get("rsi"),
        vol_rate=normalized.get("vol_rate"),
    )

    quality_score = _quality_score(normalized, comp, total_score)
    quality_flags = _quality_flags(normalized, comp)
    pass_quality = _pass_quality_gate(normalized, comp, total_score, quality_score)

    if not pass_quality and stage != "PASS":
        stage = "PASS"

    entry_timing = _decide_entry_timing(normalized, comp, total_score, quality_score, stage)
    entry_plan = _build_entry_plan(normalized)

    accumulation_flags = comp["accumulation_flags"] + comp["trend_flags"]

    return {
        "stage": stage,
        "stage_reason": build_stage_comment({**normalized, **comp}),
        "stage_score": int(total_score),
        "stage_label": stage,
        "stage_comment": build_stage_comment({**normalized, **comp}),
        "total_score": int(total_score),
        "quality_score": int(quality_score),
        "quality_flags": quality_flags,
        "pass_quality": pass_quality,
        "accumulation_score": comp["accumulation_score"],
        "breakout_score": comp["breakout_score"],
        "theme_score": comp["theme_score"],
        "sentiment_adj": comp["sentiment_adj"],
        "risk_score": comp["risk_score"],
        "accumulation_flags": accumulation_flags,
        "breakout_flags": comp["breakout_flags"],
        "risk_flags": comp["risk_flags"],
        "trend_flags": comp["trend_flags"],
        **entry_timing,
        **entry_plan,
    }
