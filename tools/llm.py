"""
LLM 调用封装 — 统一接口，支持 DeepSeek API + 重试 + 熔断
===========================================================
用法：
    from tools.llm import safe_invoke
    text, ok = safe_invoke("你好")  # 自动重试+熔断，返回 (内容, 是否成功)
"""
import os
import sys
import threading
import time
from dotenv import load_dotenv

load_dotenv()

# ── 重试配置 ──
_RETRY_TIMES = 2       # 失败后重试次数
_RETRY_DELAY = 2.0     # 每次重试间隔（秒）

# ── 熔断器配置 ──
_CIRCUIT_BREAK_THRESHOLD = 3   # 连续失败 N 次后熔断
_CIRCUIT_COOLDOWN = 30.0       # 熔断后等待 N 秒再试

# ── 熔断器状态（加锁：并行 Agent 同时失败时避免竞态）──
_circuit_state = {
    "fail_count": 0,           # 当前连续失败次数
    "open_until": 0.0,         # 熔断状态持续到哪个时间点
}
_circuit_lock = threading.Lock()

# ── 并发限流：限制同时打到 LLM API 的请求数 ──
# 4 个审查 Agent 并发调 API，不加控制会同时打爆 DeepSeek 限流
LLM_MAX_CONCURRENCY = int(os.getenv("LLM_MAX_CONCURRENCY", "16"))
_llm_semaphore = threading.Semaphore(LLM_MAX_CONCURRENCY)

# ── Prometheus 指标埋点（缺 prometheus_client 时自动降级，不影响功能）──
try:
    from monitoring import LLM_CALLS, LLM_CIRCUIT_BREAKER, AGENT_CALLS, AGENT_LATENCY
except Exception:
    LLM_CALLS = LLM_CIRCUIT_BREAKER = AGENT_CALLS = AGENT_LATENCY = None


def _metric_inc(counter, **labels):
    """指标自增（指标未初始化时静默跳过）"""
    if counter is not None:
        counter.labels(**labels).inc()


def _metric_set(gauge, value):
    """指标赋值（指标未初始化时静默跳过）"""
    if gauge is not None:
        gauge.set(value)


def _metric_observe(hist, agent_name, value):
    """直方图观测（指标未初始化时静默跳过）"""
    if hist is not None:
        hist.labels(agent=agent_name).observe(value)


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

    # 熔断中（加锁：并行调用时读状态也要一致）
    with _circuit_lock:
        if _circuit_state["fail_count"] >= _CIRCUIT_BREAK_THRESHOLD:
            if now < _circuit_state["open_until"]:
                return False, f"熔断中（连续失败{_circuit_state['fail_count']}次），{int(_circuit_state['open_until'] - now)}秒后重试"
            # 冷却期过了，半开状态，放行一次

    return True, ""


def _record_success():
    """调用成功 → 重置熔断器（加锁）"""
    with _circuit_lock:
        _circuit_state["fail_count"] = 0
        _circuit_state["open_until"] = 0.0


def _record_failure():
    """调用失败 → 累计失败次数（加锁，避免并发自增竞态）"""
    with _circuit_lock:
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
    with _llm_semaphore:  # 并发限流：同时最多 LLM_MAX_CONCURRENCY 个请求
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
        _metric_set(LLM_CIRCUIT_BREAKER, 1)
        _metric_inc(LLM_CALLS, status="rejected")
        return f"[LLM 服务熔断] {msg}", False

    # ── 第二步：调用 + 重试 ──
    last_error = ""
    for attempt in range(1 + _RETRY_TIMES):
        try:
            text = invoke(prompt, temperature)
            _record_success()  # 成功了，重置熔断器
            _metric_set(LLM_CIRCUIT_BREAKER, 0)
            _metric_inc(LLM_CALLS, status="success")
            return text, True
        except Exception as e:
            last_error = str(e)
            if attempt < _RETRY_TIMES:
                time.sleep(_RETRY_DELAY)

    # 全部失败 → 记录失败次数
    _record_failure()
    _metric_set(LLM_CIRCUIT_BREAKER, 1)
    _metric_inc(LLM_CALLS, status="error")
    return f"[LLM 服务不可用] 重试 {_RETRY_TIMES} 次后仍失败: {last_error}", False


def timed_invoke(agent_name: str, prompt: str, temperature: float = 0.3) -> tuple[str, bool]:
    """
    带耗时埋点的 safe_invoke —— 观察各 Agent 的调用耗时和并行度。

    用法：
        text, ok = timed_invoke("security", prompt, temperature=0.1)

    验证并行度：
        一次审查总耗时 ≈ 最慢 Agent 耗时  → 真并行
        一次审查总耗时 ≈ 各 Agent 耗时之和 → 串行
    """
    from utils import log
    t0 = time.time()
    text, ok = safe_invoke(prompt, temperature)
    elapsed = time.time() - t0
    _metric_inc(AGENT_CALLS, agent=agent_name, status="ok" if ok else "error")
    _metric_observe(AGENT_LATENCY, agent_name, elapsed)
    log(f"[{agent_name}] LLM 调用耗时 {elapsed:.1f}s, 成功={ok}")
    return text, ok


def extract_json_array(text: str) -> tuple:
    """
    从 LLM 响应文本中稳健提取 JSON 数组。

    替代原来脆弱的 re.search(r'\\[.*\\]', text)：
    - 原来的正则从第一个 [ 贪心吃到最后一个 ]，LLM 在数组后面补一句
      带 [ ] 的话（如 "[仅供参考]"）就会把尾巴吞进 JSON → 解析失败；
    - 本函数用 json.JSONDecoder.raw_decode 只解析"第一个合法 JSON 值"，
      天然忽略数组后面的任何废话；
    - 同时剥掉 ```json ... ``` markdown 代码围栏。

    关键设计：解析失败返回 (None, 错误描述)，由调用方决定怎么处理
    （应当记入 agent_errors 让报告显示"结果可能不完整"，而不是静默返回空数组
    把"审查失败"伪装成"没问题"）。

    用法:
        data, err = extract_json_array(text)
        if err:
            return {"security_findings": [], "agent_errors": ["security"]}
        return {"security_findings": data}

    返回:
        (list, None)  成功（data 一定是 list，空数组 [] 也是合法结果）
        (None, str)   失败，str 是错误描述
    """
    import json, re

    if not text or not text.strip():
        return None, "LLM 返回空响应"

    t = text.strip()
    # 剥掉 ```json ... ``` markdown 代码围栏
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)

    # 从头扫描，在第一个 [ 或 { 处用 raw_decode 只解析第一个合法 JSON 值
    decoder = json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch in "[{":
            try:
                data, _ = decoder.raw_decode(t[i:])
            except json.JSONDecodeError:
                continue  # 这个位置的 [ 或 { 不是合法 JSON 开头，继续往后找
            if isinstance(data, list):
                return data, None
            return None, "响应中的 JSON 不是数组（可能是对象或单个值）"
    return None, "响应中没有找到 JSON"
