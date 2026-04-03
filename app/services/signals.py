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
        or merged.get("close")
        or latest_daily.get("close"),
        0,
    )
    low = _safe_float(
        merged.get("low")
        or quote.get("low")
        or latest_daily.get("low"),
        0,
    )
    high = _safe_float(
        merged.get("high")
        or quote.get("high")
        or latest_daily.get("high"),
        0,
    )
    open_price = _safe_float(
        merged.get("open")
        or quote.get("open")
        or latest_daily.get("open"),
        0,
    )

    closes = []
    volumes = []
    highs = []
    lows = []
    for row in daily_rows:
        c = _safe_float(row.get("close"), 0)
        v = _safe_float(row.get("volume"), 0)
        h = _safe_float(row.get("high"), 0)
        l = _safe_float(row.get("low"), 0)
        if c > 0:
            closes.append(c)
        if v >= 0:
            volumes.append(v)
        if h > 0:
            highs.append(h)
        if l > 0:
            lows.append(l)

    ma5 = sum(closes[:5]) / len(closes[:5]) if closes[:5] else price
    ma20 = sum(closes[:20]) / len(closes[:20]) if closes[:20] else ma5
    recent_high_20 = max(highs[:20]) if highs[:20] else high
    recent_low_20 = min(lows[:20]) if lows[:20] else low
    avg_vol_20 = sum(volumes[:20]) / len(volumes[:20]) if volumes[:20] else 0

    change_pct = _safe_float(merged.get("change_pct"), None)
    if change_pct is None:
        change_pct = ((price - prev_close) / prev_close) * 100 if prev_close > 0 else 0

    vol_rate = _safe_float(merged.get("vol_rate"), None)
    if vol_rate is None:
        current_vol = _safe_float(merged.get("volume") or quote.get("volume"), 0)
        vol_rate = (current_vol / avg_vol_20 * 100) if avg_vol_20 > 0 else 0

    rebound_from_low = _safe_float(merged.get("rebound_from_low"), None)
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
            "change_pct": round(change_pct, 2),
            "vol_rate": round(vol_rate, 1),
            "rebound_from_low": round(rebound_from_low, 2),
            "ma5": round(ma5, 2),
            "ma20": round(ma20, 2),
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
    recent_high_20 = _safe_float(item.get("recent_high_20"), price)
    recent_low_20 = _safe_float(item.get("recent_low_20"), price)
    news_score = _safe_float(item.get("news_score"), 0)
    news_bias = str(item.get("news_bias", "NEUTRAL")).upper().strip()
    theme = str(item.get("theme", "")).lower()

    accumulation_flags = []
    breakout_flags = []
    risk_flags = []

    accumulation_score = 0
    breakout_score = 0
    theme_score = 0
    sentiment_adj = 0
    risk_score = 0

    if rsi < 35:
        accumulation_score += 18
        accumulation_flags.append("RSI과매도")
    elif 35 <= rsi <= 50:
        accumulation_score += 10
        accumulation_flags.append("저부담RSI")

    if rebound >= 1.0:
        accumulation_score += 8
        accumulation_flags.append("저점반등")
    if rebound >= 2.0:
        accumulation_score += 4

    if price > 0 and ma5 > 0 and ma20 > 0:
        if price >= ma5 >= ma20:
            accumulation_score += 10
            breakout_score += 10
            accumulation_flags.append("단기정배열")
            breakout_flags.append("정배열")
        elif price >= ma5:
            accumulation_score += 4

    if vol_rate >= 120:
        accumulation_score += 8
        breakout_score += 8
        accumulation_flags.append("거래량증가")
        breakout_flags.append("거래량동반")
    if vol_rate >= 200:
        breakout_score += 6
        breakout_flags.append("거래량급증")

    if recent_high_20 > 0:
        dist_to_high = ((recent_high_20 - price) / recent_high_20) * 100
        if dist_to_high <= 1.5:
            breakout_score += 16
            breakout_flags.append("20일고점근접")
        elif dist_to_high <= 3.0:
            breakout_score += 8
            breakout_flags.append("고점접근")

    if 0.5 <= change_pct <= 4.5:
        breakout_score += 8
        breakout_flags.append("양호한상승률")
    elif change_pct > 6:
        risk_score += 8
        risk_flags.append("단기급등")
    elif change_pct < -4:
        risk_score += 8
        risk_flags.append("급락추세")

    if news_bias == "POSITIVE":
        sentiment_adj += max(4, min(12, int(news_score)))
    elif news_bias == "NEGATIVE":
        sentiment_adj -= max(6, min(15, int(abs(news_score))))
        risk_score += 10
        risk_flags.append("부정뉴스")

    for kw in ("ai", "반도체", "데이터센터", "전기차", "플랫폼"):
        if kw in theme:
            theme_score += 4

    if rsi > 75:
        risk_score += 10
        risk_flags.append("RSI과열")
    elif rsi > 70:
        risk_score += 6
        risk_flags.append("RSI경계")

    if price > 0 and prev_close > 0:
        gap_pct = ((price - prev_close) / prev_close) * 100
        if gap_pct >= 5:
            risk_score += 6
            risk_flags.append("갭상승과다")

    accumulation_score = max(0, min(30, int(round(accumulation_score))))
    breakout_score = max(0, min(30, int(round(breakout_score))))
    theme_score = max(0, min(15, int(round(theme_score))))
    sentiment_adj = max(-15, min(15, int(round(sentiment_adj))))
    risk_score = max(0, min(30, int(round(risk_score))))

    return {
        "accumulation_score": accumulation_score,
        "breakout_score": breakout_score,
        "theme_score": theme_score,
        "sentiment_adj": sentiment_adj,
        "risk_score": risk_score,
        "accumulation_flags": accumulation_flags,
        "breakout_flags": breakout_flags,
        "risk_flags": risk_flags,
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
        total = 35 + e + b + t + s - r
        return round(max(0, min(100, total)), 1)

    e = _safe_float(early_score, 0)
    b = _safe_float(breakout_score, 0)
    t = _safe_float(theme_score, 0)
    s = _safe_float(sentiment_adj if sentiment_adj is not None else news_score, 0)
    r = _safe_float(risk_score, 0)
    total = 35 + e + b + t + s - r
    return round(max(0, min(100, total)), 1)


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
    # 1) reporter.py에서 개별 점수 인자로 호출하는 경우
    if any(v is not None for v in [early_score, breakout_score, risk_score, theme_score, total_score, rsi, vol_rate]):
        total = _safe_float(total_score, 0)
        risk = _safe_float(risk_score, 0)
        rsi_val = _safe_float(rsi, 50)
        vol_val = _safe_float(vol_rate, 0)
        early = _safe_float(early_score, 0)
        breakout = _safe_float(breakout_score, 0)

        if risk >= 18 and total < 55:
            return "과열주의"
        if total >= 85:
            return "강매수"
        if total >= 70:
            return "매수관심"
        if total >= 55:
            return "관심"
        if early >= 15 and breakout >= 10 and risk <= 12:
            return "바닥탐색"
        if rsi_val < 35 and vol_val >= 100:
            return "반등대기"
        return "관망"

    # 2) item dict로 호출하는 경우
    if isinstance(item, dict):
        total = compute_weighted_stage_score(item=item)
        comp = _build_component_scores(_normalize_item(item))
        risk = _safe_float(comp.get("risk_score"), 0)
        rsi_val = _safe_float(item.get("rsi"), 50)
        vol_val = _safe_float(item.get("vol_rate"), 0)
        early = _safe_float(comp.get("accumulation_score"), 0)
        breakout = _safe_float(comp.get("breakout_score"), 0)

        if risk >= 18 and total < 55:
            return "과열주의"
        if total >= 85:
            return "강매수"
        if total >= 70:
            return "매수관심"
        if total >= 55:
            return "관심"
        if early >= 15 and breakout >= 10 and risk <= 12:
            return "바닥탐색"
        if rsi_val < 35 and vol_val >= 100:
            return "반등대기"
        return "관망"

    # 3) 숫자 하나만 들어온 경우
    total = _safe_float(item, 0)
    if total >= 85:
        return "강매수"
    if total >= 70:
        return "매수관심"
    if total >= 55:
        return "관심"
    return "관망"

def build_stage_comment(item):
    normalized = _normalize_item(item)
    comp = _build_component_scores(normalized)
    total_score = compute_weighted_stage_score(item=normalized)
    stage = decide_stage_label(total_score=total_score, rsi=normalized.get("rsi"), risk_score=comp["risk_score"])

    reasons = []
    if comp["accumulation_flags"]:
        reasons.append("매집:" + ",".join(comp["accumulation_flags"][:2]))
    if comp["breakout_flags"]:
        reasons.append("돌파:" + ",".join(comp["breakout_flags"][:2]))
    if comp["risk_flags"]:
        reasons.append("리스크:" + ",".join(comp["risk_flags"][:2]))

    tail = " / ".join(reasons) if reasons else "특이사항 없음"
    return f"{stage} / {tail}"


def _build_entry_plan(normalized, comp, total_score):
    price = _safe_float(normalized.get("price"), 0)
    recent_low_20 = _safe_float(normalized.get("recent_low_20"), price)
    change_pct = _safe_float(normalized.get("change_pct"), 0)
    news_bias = str(normalized.get("news_bias", "NEUTRAL")).upper().strip()

    proposed_entry = int(round(price * 0.95)) if price > 0 else 0
    entry_zone_low = int(round(proposed_entry * 0.99)) if proposed_entry > 0 else 0
    entry_zone_high = int(round(proposed_entry * 1.01)) if proposed_entry > 0 else 0

    stop_base = min(recent_low_20, proposed_entry * 0.97 if proposed_entry > 0 else 0)
    stop_loss = int(round(stop_base)) if stop_base > 0 else 0

    target1 = int(round(proposed_entry * 1.05)) if proposed_entry > 0 else 0
    target2 = int(round(proposed_entry * 1.10)) if proposed_entry > 0 else 0

    entry_score = int(
        max(
            0,
            min(
                100,
                total_score
                + min(10, comp["breakout_score"] // 2)
                + min(8, comp["accumulation_score"] // 3)
                - min(12, comp["risk_score"] // 2),
            ),
        )
    )

    reasons = []
    if comp["accumulation_score"] >= 12:
        reasons.append("매집신호유효")
    if comp["breakout_score"] >= 12:
        reasons.append("돌파구간근접")
    if news_bias == "POSITIVE":
        reasons.append("뉴스우호적")
    if change_pct > 6:
        reasons.append("단기과열주의")

    if entry_score >= 70 and comp["risk_score"] <= 14:
        entry_decision = "ENTRY"
    elif entry_score >= 50:
        entry_decision = "WAIT"
    else:
        entry_decision = "PASS"

    return {
        "proposed_entry": proposed_entry,
        "entry_zone_low": entry_zone_low,
        "entry_zone_high": entry_zone_high,
        "stop_loss": stop_loss,
        "target1": target1,
        "target2": target2,
        "entry_score": entry_score,
        "entry_decision": entry_decision,
        "entry_reason": ", ".join(reasons) if reasons else "신호 보통",
    }


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
        total_score=total_score,
        rsi=normalized.get("rsi"),
        risk_score=comp["risk_score"],
    )
    entry_plan = _build_entry_plan(normalized, comp, total_score)

    return {
        "stage": stage,
        "stage_reason": build_stage_comment({**normalized, **comp}),
        "stage_score": int(total_score),
        "stage_label": stage,
        "stage_comment": build_stage_comment({**normalized, **comp}),
        **comp,
        **entry_plan,
    }
