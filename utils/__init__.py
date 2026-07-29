"""
结构化日志工具 — 带 trace_id 链路追踪和分级日志
================================================
用法：
    from utils import log_info, log_warn, log_error, set_trace_id

    set_trace_id("review-42")          # 设置追踪ID
    log_info("开始审查", agent="security")  # 带标签
    log_warn("重试", attempt=2)             # 带上下文
    log_error("失败", exc=e)                # 带异常
"""
import sys
import traceback
from datetime import datetime
from contextvars import ContextVar

# 线程/协程安全的 trace_id
_trace_id: ContextVar[str] = ContextVar("trace_id", default="")
_request_id: ContextVar[str] = ContextVar("request_id", default="")


def set_trace_id(trace_id: str = "") -> str:
    """设置 trace_id，不传则自动生成（基于时间戳）"""
    if not trace_id:
        trace_id = datetime.now().strftime("%H%M%S") + f"-{id(trace_id) % 10000:04d}"
    _trace_id.set(trace_id)
    return trace_id


def get_trace_id() -> str:
    return _trace_id.get()


def set_request_id(rid: str) -> None:
    _request_id.set(rid)


def _format(level: str, msg: str, **kwargs) -> str:
    """格式化日志行：时间 [级别] [trace_id] 消息 key=val"""
    ts = datetime.now().strftime("%H:%M:%S")
    tid = get_trace_id()
    ctx = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    extra = f" ({ctx})" if ctx else ""
    return f"{ts} [{level}] [{tid}] {msg}{extra}"


def log_info(msg: str, **kwargs) -> None:
    """INFO 级别日志"""
    print(_format("INFO", msg, **kwargs), file=sys.stderr, flush=True)


def log_warn(msg: str, **kwargs) -> None:
    """WARN 级别日志"""
    print(_format("WARN", msg, **kwargs), file=sys.stderr, flush=True)


def log_error(msg: str, exc=None, **kwargs) -> None:
    """ERROR 级别日志，可附带异常堆栈"""
    output = _format("ERROR", msg, **kwargs)
    if exc:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        output += f"\n{tb}"
    print(output, file=sys.stderr, flush=True)


# ── 兼容旧代码的 log() 函数 ──
def log(msg: str):
    """兼容旧接口，默认 INFO 级别"""
    log_info(msg)
