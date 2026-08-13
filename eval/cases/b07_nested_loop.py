"""评估用例 b07 — 性能：去重用线性扫描（O(n²)）"""
def unique_items(items):
    seen = []
    for x in items:
        if x not in seen:
            seen.append(x)
    return seen
