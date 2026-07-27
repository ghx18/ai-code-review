"""
LLM 调用封装 — 统一接口，支持 DeepSeek API + 自动重试
=======================================================
用法：
    from tools.llm import safe_invoke
    text, ok = safe_invoke("你好")  # 自动重试，返回 (内容, 是否成功)
"""
import os
import sys
import time
from dotenv import load_dotenv

load_dotenv()

_RETRY_TIMES = 2       # 失败后重试次数
_RETRY_DELAY = 2.0     # 每次重试间隔（秒）

# ── 尝试导入 langchain_deepseek ──
try:
    from langchain_deepseek import ChatDeepSeek as _ChatDeepSeek

    _llm = _ChatDeepSeek(
        model="deepseek-chat",
        temperature=0.3,
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        max_tokens=4096,
        timeout=30,         # 单次请求超时30秒
    )
except ImportError:
    _llm = None


def get_llm(temperature: float = 0.3, max_tokens: int = 4096):
    """获取 LLM 实例（延迟初始化，支持动态参数）"""
    if _llm is None:
        raise RuntimeError(
            "无法初始化 LLM。请安装 langchain-deepseek: pip install langchain-deepseek"
        )
    if temperature != 0.3 or max_tokens != 4096:
        return _ChatDeepSeek(
            model="deepseek-chat",
            temperature=temperature,
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            max_tokens=max_tokens,
            timeout=30,
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
    """同步调用 LLM，返回文本（无重试）"""
    llm = get_llm(temperature=temperature)
    resp = llm.invoke(prompt)
    return resp.content if hasattr(resp, "content") else str(resp)


def safe_invoke(prompt: str, temperature: float = 0.3) -> tuple[str, bool]:
    """
    带自动重试的 LLM 调用。

    返回:
        (text, success) — 调用成功时 success=True，text 为返回内容；
                          全部重试失败后 success=False，text 为错误描述。
    """
    last_error = ""
    for attempt in range(1 + _RETRY_TIMES):
        try:
            text = invoke(prompt, temperature)
            return text, True
        except Exception as e:
            last_error = str(e)
            if attempt < _RETRY_TIMES:
                time.sleep(_RETRY_DELAY)
    return f"[LLM 服务不可用] 重试 {_RETRY_TIMES} 次后仍失败: {last_error}", False
