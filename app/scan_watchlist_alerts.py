
from __future__ import annotations

from app.clients.telegram import send_telegram
from app.services.watchlist_alerts import scan_watchlist_alert_signals


def main() -> None:
    msgs = scan_watchlist_alert_signals()

    if not msgs:
        print("watchlist alert scan: no messages")
        return

    merged = "👀 WATCHLIST 타이밍 알림\n\n" + "\n\n".join(msgs)
    result = send_telegram(merged)
    print("watchlist alert scan telegram ok:", result)


if __name__ == "__main__":
    main()
