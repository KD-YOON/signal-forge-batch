from app.clients.telegram import send_telegram
from app.services.reporter import build_report


def main():
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    text = build_report(mode)
    result = send_telegram(text)
    print("telegram ok:", result)


if __name__ == "__main__":
    main()
