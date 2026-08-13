"""评估用例 b03 — 安全：硬编码密钥"""
API_KEY = "sk-abcdefghijklmnopqrstuvwxyz123456"


def call_service():
    return {"Authorization": f"Bearer {API_KEY}"}
