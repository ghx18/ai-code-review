"""评估用例 c02 — 干净对照：无缺陷的工具函数"""
def clamp(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


def split_into_pairs(items):
    return list(zip(items[::2], items[1::2]))
