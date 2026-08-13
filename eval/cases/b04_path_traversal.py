"""评估用例 b04 — 安全：路径遍历（未校验用户输入的文件路径）"""
import os


def serve_file(filename: str):
    path = os.path.join("/srv/static", filename)
    with open(path, "rb") as f:
        return f.read()
