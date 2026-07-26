import sys


def log(msg: str):
    """内部日志走 stderr，不污染 JSON 输出"""
    print(f"  {msg}", file=sys.stderr, flush=True)
