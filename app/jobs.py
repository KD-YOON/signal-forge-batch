from app.clients.telegram import send_telegram
from app.services.reporter import build_report


TITLE_MARKERS = {
    "🔥 오늘 최우선 종목",
    "🔥 오전 우선 종목",
    "🔥 점심 체크 종목",
    "🔥 저녁 준비 종목",
}

BLOCK_END_MARKERS = {
    "➕ 차순위 후보",
    "제외 기준:",
    "💡 전략:",
    "💡 오전 전략:",
    "💡 점심 전략:",
    "💡 저녁 전략:",
}


def _extract_top_block(lines: list[str]) -> list[str]:
    """
    리포트 전체에서 '최우선 종목 블록'만 잘라낸다.
    차순위 후보 이하가 섞이지 않도록 차단한다.
    """
    start_idx = -1
    for i, line in enumerate(lines):
        raw = str(line or "").strip()
        if raw in TITLE_MARKERS:
            start_idx = i
            break

    if start_idx < 0:
        return []

    block = []
    for i in range(start_idx, len(lines)):
        raw = str(lines[i] or "").rstrip()

        if i > start_idx:
            stripped = raw.strip()
            if stripped in BLOCK_END_MARKERS:
                break
            if any(stripped.startswith(marker) for marker in BLOCK_END_MARKERS):
                break

        block.append(raw)

    return block


def extract_entry_alerts(report_text: str) -> str:
    text = str(report_text or "").strip()
    if not text:
        return ""

    lines = text.splitlines()
    top_block = _extract_top_block(lines)
    if not top_block:
        return ""

    stage = ""
    decision = ""
    reason = ""
    proposed_entry = ""
    entry_zone = ""
    stop_loss = ""
    target_line = ""
    top_name = ""
    mode = ""
    timestamp = ""

    # 모드/시각은 전체 문서 상단에서 추출
    for line in lines:
        raw = str(line or "").strip()
        if raw.startswith("모드:") and not mode:
            mode = raw.replace("모드:", "", 1).strip()
        elif raw.startswith("시각:") and not timestamp:
            timestamp = raw.replace("시각:", "", 1).strip()

        if mode and timestamp:
            break

    # 최상위 종목 블록 내부에서만 추출
    for i, line in enumerate(top_block):
        raw = str(line or "").strip()

        if raw in TITLE_MARKERS:
            if i + 1 < len(top_block):
                maybe_name = str(top_block[i + 1] or "").strip()
                if maybe_name and "(" in maybe_name and ")" in maybe_name:
                    top_name = maybe_name

        elif raw.startswith("최종단계:"):
            stage = raw.replace("최종단계:", "", 1).strip()

        elif raw.startswith("진입판정:"):
            decision = raw.replace("진입판정:", "", 1).strip()

        elif raw.startswith("진입사유:"):
            reason = raw.replace("진입사유:", "", 1).strip()

        elif raw.startswith("전일종가 기준 제안매수가:"):
            proposed_entry = raw.replace("전일종가 기준 제안매수가:", "", 1).strip()

        elif raw.startswith("관심구간:"):
            entry_zone = raw.replace("관심구간:", "", 1).strip()

        elif raw.startswith("손절가:"):
            stop_loss = raw.replace("손절가:", "", 1).strip()

        elif raw.startswith("목표가1:"):
            target_line = raw.strip()

    # ENTRY가 아니면 알림 전송 안 함
    if not decision.startswith("ENTRY"):
        return ""

    alert_lines = ["🚨 ENTRY ALERT"]

    if top_name:
        alert_lines.append(top_name)
    if mode:
        alert_lines.append(f"모드: {mode}")
    if timestamp:
        alert_lines.append(f"시각: {timestamp}")

    alert_lines.append("")

    if stage:
        alert_lines.append(f"단계: {stage}")
    if decision:
        alert_lines.append(f"진입판정: {decision}")
    if reason:
        alert_lines.append(f"진입사유: {reason}")
    if proposed_entry:
        alert_lines.append(f"제안매수가: {proposed_entry}")
    if entry_zone:
        alert_lines.append(f"관심구간: {entry_zone}")
    if stop_loss:
        alert_lines.append(f"손절가: {stop_loss}")
    if target_line:
        alert_lines.append(target_line)

    alert_lines += [
        "",
        "메모: 관심구간 접근 후 분할·반등 확인 우선",
    ]

    return "\n".join(alert_lines)


def main():
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"

    report_text = build_report(mode)
    result = send_telegram(report_text)
    print("report telegram ok:", result)

    entry_alert_text = extract_entry_alerts(report_text)
    if entry_alert_text:
        entry_result = send_telegram(entry_alert_text)
        print("entry telegram ok:", entry_result)
    else:
        print("entry telegram skipped")


if __name__ == "__main__":
    main()
