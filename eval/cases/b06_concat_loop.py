"""评估用例 b06 — 性能：循环内字符串拼接"""
def build_csv(rows):
    out = ""
    for r in rows:
        out += r + ","
    return out
