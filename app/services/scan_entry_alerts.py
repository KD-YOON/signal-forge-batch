from app.clients.telegram import send_telegram
from app.services.entry_alerts import scan_entry_alert_signals


def main():
    msgs = scan_entry_alert_signals()
    if not msgs:
        print("entry alert scan: no messages")
        return

    merged = "📥 리포트 기반 매수시점 알림\n\n" + "\n\n".join(msgs)
    result = send_telegram(merged)
    print("entry alert scan telegram ok:", result)


if __name__ == "__main__":
    main()
