"""评估用例 b09 — 逻辑：越界访问（len 直接当下标）"""
def last_item(items):
    return items[len(items)]
