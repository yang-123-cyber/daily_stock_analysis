import json
import os
import smtplib
import sqlite3
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path


BUY_WORDS = ("\u4e70\u5165", "\u52a0\u4ed3", "\u4f4e\u5438", "\u5e03\u5c40", "buy")
SELL_WORDS = ("\u5356\u51fa", "\u51cf\u4ed3", "\u6e05\u4ed3", "sell")
HOLD_WORDS = (
    "\u89c2\u671b",
    "\u6301\u6709",
    "\u89c2\u5bdf",
    "\u7b49\u5f85",
    "\u4e0d\u9002\u5408",
    "\u8c28\u614e",
    "hold",
    "watch",
)


def get_stock_list():
    return [
        item.strip().split(".")[0].replace("sh", "").replace("sz", "")
        for item in os.getenv("STOCK_LIST", "").split(",")
        if item.strip()
    ]


def latest_close(conn, code):
    for table in ("stock_daily", "stock_history", "daily_data"):
        try:
            row = conn.execute(
                f"select close from {table} where code=? order by date desc limit 1",
                (code,),
            ).fetchone()
            return float(row[0]) if row and row[0] else None
        except sqlite3.Error:
            continue
    return None


def latest_analysis(conn, code):
    queries = [
        """
        select code,name,operation_advice,analysis_summary,ideal_buy,secondary_buy,
               stop_loss,take_profit,sentiment_score,created_at
        from analysis_history
        where code=?
        order by datetime(created_at) desc
        limit 1
        """,
        """
        select stock_code,stock_name,recommendation,analysis,ideal_buy_price,buy_price,
               stop_loss_price,take_profit_price,score,created_at
        from analysis_results
        where stock_code=?
        order by datetime(created_at) desc
        limit 1
        """,
    ]
    for query in queries:
        try:
            return conn.execute(query, (code,)).fetchone()
        except sqlite3.Error:
            continue
    return None


def infer_signal(row, close_price):
    (
        code,
        name,
        advice,
        summary,
        ideal_buy,
        secondary_buy,
        stop_loss,
        take_profit,
        score,
        created_at,
    ) = row
    mode = os.getenv("TRADE_SIGNAL_MODE", "conservative").strip().lower()
    advice_text = f"{advice or ''}".lower()
    full_text = f"{advice or ''} {summary or ''}".lower()
    score = int(score or 0)
    action = "hold"
    price = 0

    if mode == "aggressive":
        signal_text = full_text
    else:
        signal_text = advice_text

    if mode != "aggressive" and any(word in advice_text for word in HOLD_WORDS):
        action = "hold"
        price = 0
    elif any(word in signal_text for word in SELL_WORDS):
        action = "sell"
        price = close_price or stop_loss or 0
    elif any(word in signal_text for word in BUY_WORDS) and score >= int(
        os.getenv("TRADE_SIGNAL_MIN_SCORE", "65")
    ):
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
        "reason": f"{name or code}: {advice or 'no clear advice'}; mode={mode}; {summary or ''}"[:220],
        "source_time": str(created_at or ""),
    }


def hold_signal(code, reason):
    return {
        "symbol": code,
        "action": "hold",
        "price": 0,
        "amount": int(os.getenv("TRADE_SIGNAL_AMOUNT", "100")),
        "confidence": 1,
        "reason": reason,
        "source_time": datetime.now().isoformat(),
    }


def send_email(payload):
    sender = os.getenv("TRADE_SIGNAL_EMAIL") or os.getenv("EMAIL_SENDER")
    password = os.getenv("TRADE_SIGNAL_EMAIL_PASSWORD") or os.getenv("EMAIL_PASSWORD")
    receiver = (
        os.getenv("TRADE_SIGNAL_TO_EMAIL")
        or os.getenv("EMAIL_RECEIVERS", "").replace(";", ",").split(",")[0].strip()
        or sender
    )
    if not sender or not password or not receiver:
        raise RuntimeError(
            "Missing email config. Set TRADE_SIGNAL_EMAIL, "
            "TRADE_SIGNAL_EMAIL_PASSWORD and TRADE_SIGNAL_TO_EMAIL."
        )

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
    stock_codes = get_stock_list()
    if not stock_codes:
        raise RuntimeError("STOCK_LIST is empty.")

    signals = []
    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            for code in stock_codes:
                row = latest_analysis(conn, code)
                if not row:
                    signals.append(hold_signal(code, "No analysis record; hold for safety."))
                    continue
                signals.append(infer_signal(row, latest_close(conn, code)))
    else:
        for code in stock_codes:
            signals.append(hold_signal(code, f"Database not found: {db_path}; hold."))

    payload = {"signals": signals, "generated_at": datetime.now().isoformat()}
    Path("daily_signals.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    send_email(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
