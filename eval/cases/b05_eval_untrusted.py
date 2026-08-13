"""评估用例 b05 — 安全：对不可信输入执行 eval"""
def evaluate(expr: str):
    return eval(expr)
