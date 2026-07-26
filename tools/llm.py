"""
LLM 调用封装 — 统一接口，支持 DeepSeek API
============================================
用法：
    from tools.llm import llm
    resp = llm.invoke("你好")
    for chunk in llm.stream("你好"):
        print(chunk)
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# ── 尝试导入 langchain_deepseek ──
try:
    from langchain_deepseek import ChatDeepSeek as _ChatDeepSeek

    _llm = _ChatDeepSeek(
        model="deepseek-chat",
        temperature=0.3,
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        max_tokens=4096,
    )
except ImportError:
    _llm = None


def get_llm(temperature: float = 0.3, max_tokens: int = 4096):
    """获取 LLM 实例（延迟初始化，支持动态参数）"""
    if _llm is None:
        raise RuntimeError(
            "无法初始化 LLM。请安装 langchain-deepseek: pip install langchain-deepseek"
        )
    # 如果参数和默认值不同，创建新实例
    if temperature != 0.3 or max_tokens != 4096:
        return _ChatDeepSeek(
            model="deepseek-chat",
            temperature=temperature,
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            max_tokens=max_tokens,
        )
    return _llm


def check_api_key() -> bool:
    """检查 API Key 是否可用"""
    key = os.getenv("DEEPSEEK_API_KEY", "")
    if not key:
        print("[错误] 未设置 DEEPSEEK_API_KEY，请在 .env 中配置")
        return False
    return True


def invoke(prompt: str, temperature: float = 0.3) -> str:
    """同步调用 LLM，返回文本"""
    llm = get_llm(temperature=temperature)
    resp = llm.invoke(prompt)
    return resp.content if hasattr(resp, "content") else str(resp)
