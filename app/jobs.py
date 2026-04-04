
from app.clients.telegram import send_telegram
from app.services.entry_alerts import sync_report_entry_alerts
from app.services.reporter import build_report_bundle
from app.services.watchlist_alerts import sync_auto_watchlist_from_rows


def main():
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"

    bundle = build_report_bundle(mode)

    report_text = str(bundle.get("report_text", "") or "").strip()
    if not report_text:
        raise RuntimeError("report_text is empty")

    result = send_telegram(report_text)
    print("report telegram ok:", result)

    entry_alert_text = str(bundle.get("entry_alert_text", "") or "").strip()
    if entry_alert_text:
        entry_result = send_telegram(entry_alert_text)
        print("entry telegram ok:", entry_result)
    else:
        print("entry telegram skipped")

    rows = bundle.get("rows", []) or []
    run_type = str(bundle.get("mode", "") or "").upper()
    run_id = str(bundle.get("timestamp", "") or "")

    synced = sync_report_entry_alerts(rows=rows, run_type=run_type, run_id=run_id)
    print("entry alerts synced:", len(synced))

    auto_watch_synced = sync_auto_watchlist_from_rows(rows=rows, run_type=run_type, run_id=run_id)
    print("auto watchlist synced:", len(auto_watch_synced))

    top_code = ""
    top_name = ""
    top_market = ""
    if rows:
        top = rows[0] or {}
        top_code = str(top.get("code", "") or "").strip()
        top_name = str(top.get("name", "") or "").strip()
        top_market = str(top.get("market", "") or "").strip().upper()

    print(
        "pipeline summary:",
        {
            "mode": bundle.get("mode"),
            "timestamp": bundle.get("timestamp"),
            "rows_count": len(rows),
            "top_market": top_market,
            "top_code": top_code,
            "top_name": top_name,
            "has_entry_alert": bool(entry_alert_text),
            "auto_watchlist_count": len(auto_watch_synced),
        },
    )


if __name__ == "__main__":
    main()
