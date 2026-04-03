from app.clients.telegram import send_telegram
from app.services.reporter import build_report


def extract_entry_alerts(report_text: str) -> str:
    text = str(report_text or "").strip()
    if not text:
        return ""

    lines = text.splitlines()

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

    for i, line in enumerate(lines):
        raw = line.strip()

        if raw.startswith("모드:"):
            mode = raw.replace("모드:", "").strip()

        if raw.startswith("시각:"):
            timestamp = raw.replace("시각:", "").strip()

        if raw.startswith("🔥"):
            if i + 1 < len(lines):
                maybe_name = lines[i + 1].strip()
                if maybe_name and "(" in maybe_name and ")" in maybe_name:
                    top_name = maybe_name

        if raw.startswith("최종단계:"):
            stage = raw.replace("최종단계:", "").strip()

        if raw.startswith("진입판정:"):
            decision = raw.replace("진입판정:", "").strip()

        if raw.startswith("진입사유:"):
            reason = raw.replace("진입사유:", "").strip()

        if raw.startswith("전일종가 기준 제안매수가:"):
            proposed_entry = raw.replace("전일종가 기준 제안매수가:", "").strip()

        if raw.startswith("관심구간:"):
            entry_zone = raw.replace("관심구간:", "").strip()

        if raw.startswith("손절가:"):
            stop_loss = raw.replace("손절가:", "").strip()

        if raw.startswith("목표가1:"):
            target_line = raw.strip()

    if not decision.startswith("ENTRY"):
        return ""

    alert_lines = [
        "🚨 ENTRY ALERT",
    ]

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
