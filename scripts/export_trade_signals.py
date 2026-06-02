    if any(word in text for word in SELL_WORDS):
        action = "sell"
        price = close_price or stop_loss or 0
    elif any(word in text for word in BUY_WORDS) and score >= int(os.getenv("TRADE_SIGNAL_MIN_SCORE", "65")):
        action = "buy"
        price = ideal_buy or secondary_buy or close_price or 0

    if action in ("buy", "sell") and not price:
        action = "hold"
        price = 0

    return {
        "symbol": code,
        "action": action,
        "price": round(float(price), 2) if price else 0,
        "amount": int(os.getenv("TRADE_SIGNAL_AMOUNT", "100")),
        "confidence": max(1, min(10, round(score / 10))) if score else 5,
        "reason": f"{name or code}: {advice or '无明确建议'}；{summary or ''}"[:220],
        "source_time": str(created_at or ""),
    }


def send_email(payload):
    sender = os.environ["TRADE_SIGNAL_EMAIL"]
    password = os.environ["TRADE_SIGNAL_EMAIL_PASSWORD"]
    receiver = os.getenv("TRADE_SIGNAL_TO_EMAIL", sender)

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = "[daily-stock-signals] daily_signals.json"
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    msg.set_content(body)
    msg.add_attachment(
        body.encode("utf-8"),
        maintype="application",
        subtype="json",
        filename="daily_signals.json",
    )

    host = os.getenv("TRADE_SIGNAL_SMTP_HOST", "smtp.163.com")
    port = int(os.getenv("TRADE_SIGNAL_SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)


def main():
    db_path = Path(os.getenv("DATABASE_PATH", "./data/stock_analysis.db"))
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    stock_codes = get_stock_list()
    if not stock_codes:
        raise RuntimeError("STOCK_LIST is empty.")

    signals = []
    with sqlite3.connect(db_path) as conn:
        for code in stock_codes:
            row = latest_analysis(conn, code)
            if not row:
                signals.append({
                    "symbol": code,
                    "action": "hold",
                    "price": 0,
                    "amount": 100,
                    "confidence": 1,
                    "reason": "未找到当日分析记录，安全起见观望",
                    "source_time": datetime.now().isoformat(),
                })
                continue
            signals.append(infer_signal(row, latest_close(conn, code)))

    payload = {"signals": signals, "generated_at": datetime.now().isoformat()}
    Path("daily_signals.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    send_email(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
