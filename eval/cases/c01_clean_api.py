"""评估用例 c01 — 干净对照：无缺陷的 API 处理函数"""
import json
from typing import Optional


def format_response(status: str, data: dict) -> str:
    payload = {"status": status, "data": data}
    return json.dumps(payload, ensure_ascii=False)


def parse_payload(raw: str) -> Optional[dict]:
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None
