import json
import os
from typing import Any

import httpx


DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _get_api_key() -> str:
    return os.getenv("GEMINI_API_KEY", "").strip()


def _call_gemini(payload: dict, model: str | None = None, timeout: float = 30.0) -> dict:
    api_key = _get_api_key()
    if not api_key:
        return {}

    model_name = model or DEFAULT_MODEL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


def _extract_text(data: dict) -> str:
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        return text.replace("\n", " ").strip()
    except Exception:
        return ""


def _parse_json_array_from_text(text: str) -> list[dict] | None:
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    cleaned = text.replace("```json", "```").replace("```", "").strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end != -1 and end > start:
        fragment = cleaned[start:end + 1]
        try:
            parsed = json.loads(fragment)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass

    return None


def build_news_summary_prompt(stock_name: str, news_items: list[dict]) -> str:
    prompt_lines = [
        "너는 한국 주식 단기매매용 뉴스 필터 분석기다.",
        f"종목명: {stock_name}",
        "",
        "[목표]",
        "입력된 기사 중 주가에 직접 영향을 줄 수 있는 투자 정보만 골라 1문장으로 요약한다.",
        "",
        "[반드시 지킬 규칙]",
        "1. 현재 시세를 추정하거나 만들어 쓰지 마라.",
        "2. 기사 내용에 없는 숫자·등락률·날짜를 임의로 쓰지 마라.",
        "3. 교육, 공공기관, 행사, 채용, 홍보성 기사, 일반 사회뉴스는 무시하라.",
        "4. 실적, 수주, 공급, 계약, 가이던스, 증권사 리포트, 투자심리, 정책 수혜만 반영하라.",
        "5. 기사들이 서로 애매하거나 투자 정보가 약하면 정확히 '관련 투자 뉴스 부족'이라고 답하라.",
        "6. 한 문장, 70자 안팎, 존댓말 없이 간결하게 써라.",
        "7. 출력은 문장 1개만, 불릿/번호/설명 추가 금지.",
        "",
        "[좋은 출력 예시]",
        "AI 서버용 반도체 수요 기대와 증권사 긍정 평가가 투자심리를 지지",
        "대규모 공급계약과 실적 개선 기대가 주가 모멘텀 요인으로 부각",
        "관련 투자 뉴스 부족",
        "",
        "[기사 목록]",
    ]

    for i, item in enumerate(news_items[:4], start=1):
        prompt_lines.append(f"{i}. 제목: {item.get('title', '')}")
        prompt_lines.append(f"   설명: {item.get('description', '')}")

    return "\n".join(prompt_lines)


def summarize_news(stock_name: str, news_items: list[dict]) -> str:
    api_key = _get_api_key()

    if not news_items:
        return "관련 투자 뉴스 부족"

    if not api_key:
        titles = [x.get("title", "").strip() for x in news_items[:2] if x.get("title")]
        return " / ".join(titles) if titles else "관련 투자 뉴스 부족"

    prompt = build_news_summary_prompt(stock_name, news_items)

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    try:
        data = _call_gemini(payload, model=DEFAULT_MODEL, timeout=30.0)
        text = _extract_text(data)
        if not text:
            return "관련 투자 뉴스 부족"
        if len(text) > 90:
            text = text[:89].rstrip() + "…"
        return text
    except Exception:
        return "관련 투자 뉴스 부족"


def _normalize_stage_label(label: str) -> str:
    raw = str(label or "").strip().upper()
    allowed = {"EARLY_ACCUMULATION", "BREAKOUT_READY", "MOMENTUM_BUY", "WATCH", "PASS"}
    return raw if raw in allowed else "WATCH"


def build_candidate_review_prompt(
    rows: list[dict],
    run_type: str,
    market_news_summary: str,
    macro_summary: str,
) -> str:
    lightweight_rows = []
    for r in rows:
        lightweight_rows.append(
            {
                "code": str(r.get("code", "")),
                "name": str(r.get("name", "")),
                "source": str(r.get("candidate_source", "")),
                "market": str(r.get("market", "KOR")),
                "theme": str(r.get("theme", "")),
                "price": float(r.get("price", 0) or 0),
                "changePct": float(r.get("change_pct", 0) or 0),
                "rsi": float(r.get("rsi", 0) or 0),
                "volRate": float(r.get("vol_rate", 0) or 0),
                "accumulationScore": int(r.get("accumulation_score", 0) or 0),
                "breakoutScore": int(r.get("breakout_score", 0) or 0),
                "riskScore": int(r.get("risk_score", 0) or 0),
                "themeScore": int(r.get("theme_score", 0) or 0),
                "sentimentAdj": int(r.get("sentiment_adj", 0) or 0),
                "totalScore": int(r.get("total_score", 0) or 0),
                "qualityScore": int(r.get("quality_score", 0) or 0),
                "stage": str(r.get("stage", "")),
                "entryDecision": str(r.get("entry_decision", "")),
                "entryReason": str(r.get("entry_reason", "")),
                "hardFilterPassed": bool(r.get("hard_filter_passed", True)),
                "hardFilterReasons": list(r.get("hard_filter_reasons", []) or []),
                "newsBias": str((r.get("news_signal") or {}).get("bias", "")),
                "newsKeywords": str((r.get("news_signal") or {}).get("keyword_summary", "")),
                "newsSummary": str(r.get("news_summary", "")),
            }
        )

    return (
        f"[실행구분]\n{run_type}\n\n"
        f"[시장요약]\n{market_news_summary}\n\n"
        f"[매크로요약]\n{macro_summary}\n\n"
        "너는 한국 주식시장 단기매매용 수석 애널리스트다.\n"
        "역할은 단순 요약이 아니라 후보 종목들을 비교해 최종 매매 적합도를 보수적으로 판정하는 것이다.\n\n"
        "[최우선 원칙]\n"
        "1. 하드필터 탈락 종목은 PASS 우선이다.\n"
        "2. 초저가, 테마 과열, 인버스/레버리지, 급등 추격형은 매우 보수적으로 본다.\n"
        "3. 뉴스만 좋고 차트 근거가 약한 종목은 과대평가 금지.\n"
        "4. totalScore, qualityScore, riskScore, entryDecision을 함께 보라.\n"
        "5. 판단이 애매하면 WATCH 또는 PASS로 보수 판정하라.\n"
        "6. 출력은 반드시 JSON 배열만 반환하라.\n\n"
        "[허용 finalSignal]\n"
        "EARLY_ACCUMULATION, BREAKOUT_READY, MOMENTUM_BUY, WATCH, PASS\n\n"
        "[출력 형식]\n"
        '[{"code":"005930","finalSignal":"BREAKOUT_READY","aiVerdict":"거래량과 가격 구조가 안정적이라 돌파 준비형으로 적절","aiRisk":"추세 재확인 필요","confidence":74}]\n\n'
        "[입력 데이터]\n"
        f"{json.dumps(lightweight_rows, ensure_ascii=False)}"
    )


def review_candidates_with_gemini(
    rows: list[dict],
    run_type: str,
    market_news_summary: str,
    macro_summary: str,
) -> list[dict]:
    api_key = _get_api_key()
    if not rows or not api_key:
        return rows

    prompt = build_candidate_review_prompt(
        rows=rows,
        run_type=run_type,
        market_news_summary=market_news_summary,
        macro_summary=macro_summary,
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    try:
        data = _call_gemini(payload, model=DEFAULT_MODEL, timeout=60.0)
        raw_text = _extract_text(data)
        parsed = _parse_json_array_from_text(raw_text)
    except Exception:
        parsed = None

    if not parsed:
        return rows

    by_code: dict[str, dict[str, Any]] = {}
    for item in parsed:
        code = str(item.get("code", "")).strip()
        if code:
            by_code[code] = item

    out = []
    for r in rows:
        code = str(r.get("code", "")).strip()
        ai = by_code.get(code, {})

        final_signal = _normalize_stage_label(ai.get("finalSignal", r.get("stage", "WATCH")))
        ai_verdict = str(ai.get("aiVerdict", "")).strip()
        ai_risk = str(ai.get("aiRisk", "")).strip()

        try:
            confidence = int(float(ai.get("confidence", 50) or 50))
        except Exception:
            confidence = 50

        new_row = {
            **r,
            "final_stage": final_signal,
            "ai_verdict": ai_verdict or str(r.get("entry_reason", "")),
            "ai_risk": ai_risk or ", ".join(r.get("hard_filter_reasons", []) or []),
            "ai_confidence": max(0, min(confidence, 100)),
        }

        if final_signal == "PASS":
            new_row["entry_decision"] = "PASS"
            if ai_risk:
                new_row["entry_reason"] = ai_risk

        out.append(new_row)

    return out
