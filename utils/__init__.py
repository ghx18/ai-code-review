"""
结构化日志工具 — stdlib logging 封装，带 trace_id/request_id 链路追踪、分级日志、文件落盘 + 轮转
================================================================================================
用法：
    from utils import log_info, log_warn, log_error, set_trace_id

    set_trace_id("review-42")             # 设置追踪ID（一次审查一个）
    set_request_id("req-20260809-001")    # 设置请求ID（一个 HTTP 请求一个）
    log_info("开始审查", agent="security")    # 带标签
    log_warn("重试", attempt=2)               # 带上下文
    log_error("失败", exc=e)                  # 带异常

日志去向：
    - 控制台 → stderr（docker logs 可见；main.py JSON 模式要求 stdout 纯净，所以不碰 stdout）
    - 文件   → <LOG_DIR>/app.log（默认 <项目根>/data/logs/），10MB 轮转，保留 5 份历史

环境变量：
    LOG_LEVEL  日志级别（DEBUG / INFO / WARNING / ERROR，默认 INFO）
    LOG_DIR    日志目录（默认 <项目根>/data/logs）
"""
import logging
import os
import sys
import traceback
from contextvars import ContextVar
from datetime import datetime
from logging.handlers import RotatingFileHandler

# 线程/协程安全的 trace_id / request_id
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
    """设置请求 ID（FastAPI 中间件在每次 HTTP 请求时调用）"""
    _request_id.set(rid)


def get_request_id() -> str:
    return _request_id.get()


# ═══════════════════════════════════════════════════════════════
#  logger 初始化（模块加载时执行一次）
# ═══════════════════════════════════════════════════════════════

_LOG_LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO,
               "WARNING": logging.WARNING, "ERROR": logging.ERROR}
_LOG_LEVEL = _LOG_LEVELS.get(os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)


def _default_log_dir() -> str:
    """默认日志目录：<项目根>/data/logs（data/ 在容器里是持久化命名卷）"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "data", "logs")


_LOG_DIR = os.getenv("LOG_DIR", _default_log_dir())


class _ContextFormatter(logging.Formatter):
    """自定义 Formatter：把 trace_id / request_id 注入每条日志记录"""

    def format(self, record):
        record.trace_id = _trace_id.get() or "-"
        record.request_id = _request_id.get() or "-"
        return super().format(record)


# 格式：2026-08-09 22:00:31 [INFO] [trace_id] [request_id] 消息 key=val
_FMT = "%(asctime)s [%(levelname)s] [%(trace_id)s] [%(request_id)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_logger = logging.getLogger("ai_code_review")
_logger.setLevel(_LOG_LEVEL)
_logger.propagate = False  # 不向根 logger 传播，避免重复输出

# ── 控制台 handler（stderr）──
_console = logging.StreamHandler(sys.stderr)
_console.setLevel(_LOG_LEVEL)
_console.setFormatter(_ContextFormatter(_FMT, _DATEFMT))
_logger.addHandler(_console)

# ── 文件 handler（落盘 + 轮转；建目录/写文件失败则降级仅控制台，import 永不炸）──
_FILE_ENABLED = False
try:
    os.makedirs(_LOG_DIR, exist_ok=True)
    _file = RotatingFileHandler(
        os.path.join(_LOG_DIR, "app.log"),
        maxBytes=10 * 1024 * 1024,  # 10MB 触发轮转
        backupCount=5,              # 保留 app.log.1 ~ app.log.5
        encoding="utf-8",
    )
    _file.setLevel(_LOG_LEVEL)
    _file.setFormatter(_ContextFormatter(_FMT, _DATEFMT))
    _logger.addHandler(_file)
    _FILE_ENABLED = True
except Exception:
    _FILE_ENABLED = False
    _logger.warning("文件日志不可用（无法写入 %s），已降级为仅控制台输出", _LOG_DIR)


def _render(msg: str, **kwargs) -> str:
    """把 kwargs 内联渲染进消息：msg (key=val ...)，与旧版 print 格式保持一致"""
    ctx = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    return f"{msg} ({ctx})" if ctx else msg


def log_debug(msg: str, **kwargs) -> None:
    """DEBUG 级别日志（默认不输出，设 LOG_LEVEL=DEBUG 才显示）"""
    _logger.debug(_render(msg, **kwargs))


def log_info(msg: str, **kwargs) -> None:
    """INFO 级别日志"""
    _logger.info(_render(msg, **kwargs))


def log_warn(msg: str, **kwargs) -> None:
    """WARNING 级别日志"""
    _logger.warning(_render(msg, **kwargs))


def log_error(msg: str, exc=None, **kwargs) -> None:
    """ERROR 级别日志，可附带异常堆栈"""
    if exc is not None:
        _logger.error(_render(msg, **kwargs),
                      exc_info=(type(exc), exc, exc.__traceback__))
    else:
        _logger.error(_render(msg, **kwargs))


# ── 兼容旧代码的 log() 函数 ──
def log(msg: str):
    """兼容旧接口，默认 INFO 级别"""
    log_info(msg)
