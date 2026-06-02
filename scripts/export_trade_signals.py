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
