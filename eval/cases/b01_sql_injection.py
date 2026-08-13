"""评估用例 b01 — 安全：SQL 注入（字符串拼接 SQL）"""
import sqlite3


def get_user(name: str):
    conn = sqlite3.connect("app.db")
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE name = '" + name + "'")
    return cur.fetchall()
