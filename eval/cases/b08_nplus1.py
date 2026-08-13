"""评估用例 b08 — 性能：循环内查询数据库（N+1 问题）"""
def load_orders(user_ids):
    orders = []
    for uid in user_ids:
        orders.extend(db.query("SELECT * FROM orders WHERE user_id=?", uid))
    return orders
