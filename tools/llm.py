"""
LLM 调用封装 — 统一接口，支持 DeepSeek API + 重试 + 熔断
===========================================================
用法：
    from tools.llm import safe_invoke
    text, ok = safe_invoke("你好")  # 自动重试+熔断，返回 (内容, 是否成功)
"""
import os
import sys
import time
from dotenv import load_dotenv

load_dotenv()

# ── 重试配置 ──
_RETRY_TIMES = 2       # 失败后重试次数
_RETRY_DELAY = 2.0     # 每次重试间隔（秒）

# ── 熔断器配置 ──
_CIRCUIT_BREAK_THRESHOLD = 3   # 连续失败 N 次后熔断
_CIRCUIT_COOLDOWN = 30.0       # 熔断后等待 N 秒再试

# ── 熔断器状态 ──
_circuit_state = {
    "fail_count": 0,           # 当前连续失败次数
    "open_until": 0.0,         # 熔断状态持续到哪个时间点
}


def _circuit_breaker():
    """
    熔断器逻辑：
    - 正常: 放行请求
    - 连续失败超过阈值: 熔断，直接拒绝请求（fail fast）
    - 冷却期过后: 半开，放一个请求试试
    - 试成功了: 关闭熔断器
    - 试又失败: 继续熔断
    """
    now = time.time()

    # 熔断中
    if _circuit_state["fail_count"] >= _CIRCUIT_BREAK_THRESHOLD:
        if now < _circuit_state["open_until"]:
            return False, f"熔断中（连续失败{_circuit_state['fail_count']}次），{int(_circuit_state['open_until'] - now)}秒后重试"
        else:
            # 冷却期过了，半开状态，放行一次
            pass

    return True, ""


def _record_success():
    """调用成功 → 重置熔断器"""
    _circuit_state["fail_count"] = 0
    _circuit_state["open_until"] = 0.0


def _record_failure():
    """调用失败 → 累计失败次数"""
    _circuit_state["fail_count"] += 1
    if _circuit_state["fail_count"] >= _CIRCUIT_BREAK_THRESHOLD:
        _circuit_state["open_until"] = time.time() + _CIRCUIT_COOLDOWN


# ── 尝试导入 langchain_deepseek ──
try:
    from langchain_deepseek import ChatDeepSeek as _ChatDeepSeek

    _llm = _ChatDeepSeek(
        model="deepseek-chat",
        temperature=0.3,
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        max_tokens=4096,
        timeout=30,
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
    带自动重试 + 熔断的 LLM 调用。

    流程：
      熔断中 → 立即返回失败（不浪费重试）
      正常 → 调用 → 成功？→ 重置熔断 → 返回结果
                   → 失败？→ 累计失败 → 重试 → 都失败 → 返回错误

    返回:
        (text, success) — 调用成功时 success=True，text 为返回内容；
                          全部重试失败后 success=False，text 为错误描述。
    """
    # ── 第一步：检查熔断器 ──
    ok, msg = _circuit_breaker()
    if not ok:
        return f"[LLM 服务熔断] {msg}", False

    # ── 第二步：调用 + 重试 ──
    last_error = ""
    for attempt in range(1 + _RETRY_TIMES):
        try:
            text = invoke(prompt, temperature)
            _record_success()  # 成功了，重置熔断器
            return text, True
        except Exception as e:
            last_error = str(e)
            if attempt < _RETRY_TIMES:
                time.sleep(_RETRY_DELAY)

    # 全部失败 → 记录失败次数
    _record_failure()
    return f"[LLM 服务不可用] 重试 {_RETRY_TIMES} 次后仍失败: {last_error}", False
