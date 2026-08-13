"""评估用例 c03 — 干净对照：无缺陷的处理逻辑"""
def process(items, limit=10):
    if limit <= 0:
        return []
    result = []
    for item in items[:limit]:
        if item and item.get("enabled"):
            result.append(item["value"])
    return sorted(result)
