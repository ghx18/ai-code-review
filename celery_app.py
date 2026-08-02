"""
Celery — 异步任务队列
======================
让审查任务在后台 Worker 中执行，不阻塞 API。

用法:
    # 启动 Worker（开发）
    celery -A celery_app worker --loglevel=info --pool=solo

    # Docker 中自动启动
    docker compose up -d
"""
import os
import time
from typing import Optional

from celery import Celery
from dotenv import load_dotenv

load_dotenv()

# ── Redis 连接 ──
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ── Celery 应用（Broker + Result Backend 都用 Redis）──
celery_app = Celery(
    "ai_code_review",
    broker=REDIS_URL,
    backend=REDIS_URL,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)

# ── 可选配置 ──
celery_app.conf.update(
    task_track_started=True,                 # 跟踪 STARTED 状态
    task_acks_late=True,                     # Worker 崩溃后重试
    worker_prefetch_multiplier=1,            # 一次只取一个任务（公平调度）
    result_expires=3600 * 24 * 7,            # 结果保留 7 天
)

# ── 重试策略：只对瞬时错误重试，并指数退避 ──
# 永久错误（认证失败、参数非法、代码 bug）重试多少次都一样失败，
# 而每次重试都会重新跑整轮审查（4 个 Agent × 多次 LLM 调用），纯烧钱。
_TRANSIENT_KEYWORDS = (
    "rate limit", "rate_limit", "too many requests", "429",
    "timeout", "timed out", "temporarily", "connection",
    "502", "503", "504", "server error",
)
_PERMANENT_KEYWORDS = (
    "401", "403", "auth", "unauthorized", "invalid api key",
    "invalid key", "forbidden", "not authorized",
)


def _is_retryable_error(exc: Exception) -> bool:
    """
    判断错误是否值得重试：
    - 瞬时错误（限流/超时/网络抖动）→ 重试有意义
    - 永久错误（认证失败、参数错误、代码 bug）→ 重试等于烧钱
    """
    msg = str(exc).lower()
    for kw in _PERMANENT_KEYWORDS:
        if kw in msg:
            return False
    for kw in _TRANSIENT_KEYWORDS:
        if kw in msg:
            return True
    return False


def _retry_backoff(retries: int) -> int:
    """指数退避：第 1 次重试等 5s，第 2 次等 10s，最多 60s"""
    return min(5 * (2 ** retries), 60)


def worker_available() -> bool:
    """
    检查是否有可用的 Celery worker。

    通过广播 ping 检测（1 秒超时）。返回空列表 = 没有 worker 在跑，
    此时任务提交了也会永远排队，不如提前让调用方知道。
    """
    try:
        # control.ping() 向所有 worker 广播，返回 [{worker_name: {'ok': 'pong'}}]
        return bool(celery_app.control.ping(timeout=1.0))
    except Exception:
        # Redis 不可达等异常 → 视为不可用
        return False


# ── 进度阶段 → 百分比（前端进度条用，配合 graph 的 progress_callback）──
_STAGE_PROGRESS = {
    "diff_analyzer": 15,        # 变更分析完成
    "security_review": 30,      # 安全审查完成
    "performance_review": 40,   # 性能审查完成
    "style_review": 50,         # 风格审查完成
    "logic_review": 60,         # 逻辑审查完成
    "aggregator": 70,           # 结果聚合完成
    "fix_generator": 85,        # 修复建议生成完成
    "report_generator": 95,     # 报告生成完成
}
_STAGE_MESSAGES = {
    "diff_analyzer": "变更分析完成",
    "security_review": "安全审查完成",
    "performance_review": "性能审查完成",
    "style_review": "风格审查完成",
    "logic_review": "逻辑审查完成",
    "aggregator": "结果聚合完成",
    "fix_generator": "修复建议生成完成",
    "report_generator": "报告生成完成",
}


def _make_progress_callback(task):
    """把图节点完成事件转成 Celery 任务的真实进度更新（5→15→…→95）"""
    def cb(stage: str):
        pct = _STAGE_PROGRESS.get(stage, 90)
        msg = _STAGE_MESSAGES.get(stage, "审查进行中")
        task.update_state(state="PROGRESS", meta={"progress": pct, "message": msg})
    return cb


@celery_app.task(bind=True, max_retries=2)
def review_task(self, input_type: str, input_path: str) -> dict:
    """
    异步执行代码审查。

    返回:
        {
            "review_id": int | None,
            "status": "completed" | "failed",
            "summary": str,
            "stats": dict,
            "total_files": int,
            "elapsed_seconds": float,
            "report": str,
            "error": str | None,
        }
    """
    # ── 延迟导入：避免 Worker 启动时加载全部依赖 ──
    from graph import run_review
    from database import save_review as db_save

    self.update_state(
        state="PROGRESS",
        meta={"progress": 5, "message": "正在初始化审查..."},
    )

    try:
        start = time.time()
        # 传入进度回调：run_review 每个节点完成后上报真实进度
        result = run_review(input_type, input_path, progress_callback=_make_progress_callback(self))
        elapsed = time.time() - start
    except Exception as exc:
        if not _is_retryable_error(exc):
            # 永久错误（认证失败、代码 bug 等）：不重试，直接失败
            self.update_state(
                state="FAILURE",
                meta={"progress": 0, "message": f"不可重试的错误: {exc}"},
            )
            raise
        # 瞬时错误（限流/超时/网络）：指数退避重试
        countdown = _retry_backoff(self.request.retries)
        self.update_state(
            state="FAILURE",
            meta={"progress": 0, "message": f"瞬时错误，{countdown}s 后自动重试: {exc}"},
        )
        raise self.retry(exc=exc, countdown=countdown)

    # run_review 通常不抛异常，而是把错误吞进 state（如文件不存在）
    # 这里也要捞出来分类：瞬时错误→重试；永久错误→不重试，但要"响亮"地失败
    if result.get("error"):
        err = result["error"]
        if _is_retryable_error(Exception(err)):
            countdown = _retry_backoff(self.request.retries)
            self.update_state(
                state="FAILURE",
                meta={"progress": 0, "message": f"瞬时错误，{countdown}s 后自动重试: {err}"},
            )
            raise self.retry(exc=Exception(err), countdown=countdown)
        # 永久错误（输入不合法等）：不重试，返回清晰的失败结果
        return {
            "review_id": None,
            "status": "failed",
            "summary": "",
            "stats": {},
            "total_files": 0,
            "elapsed_seconds": round(elapsed, 2),
            "report": result.get("report", ""),
            "error": err,
            "fix_suggestions": [],
        }

    self.update_state(
        state="PROGRESS",
        meta={"progress": 98, "message": "审查完成，正在保存结果..."},
    )

    # 保存到数据库
    try:
        review_id = db_save(
            input_type=input_type,
            input_path=input_path,
            summary=result.get("summary", ""),
            report=result.get("report", ""),
            stats=result.get("stats", {}),
            status="completed" if not result.get("error") else "failed",
            error=result.get("error", ""),
            total_files=result.get("total_files", 0),
            elapsed_seconds=elapsed,
            findings=result.get("aggregated_findings", []),
            fix_suggestions=result.get("fix_suggestions", []),
        )
    except Exception as exc:
        review_id = None

    self.update_state(
        state="PROGRESS",
        meta={"progress": 100, "message": "已完成"},
    )

    return {
        "review_id": review_id,
        "status": "completed" if not result.get("error") else "failed",
        "summary": result.get("summary", ""),
        "stats": result.get("stats", {}),
        "total_files": result.get("total_files", 0),
        "elapsed_seconds": round(elapsed, 2),
        "report": result.get("report", ""),
        "error": result.get("error") if result.get("error") else None,
        "fix_suggestions": result.get("fix_suggestions", []),
    }


def get_task_result(task_id: str) -> dict:
    """
    查询任务状态和结果。

    返回:
        {
            "task_id": str,
            "state": "PENDING" | "PROGRESS" | "SUCCESS" | "FAILURE",
            "progress": int,
            "message": str,
            "result": dict | None,
            "error": str | None,
        }
    """
    task = celery_app.AsyncResult(task_id)

    base = {
        "task_id": task_id,
        "state": task.state,
    }

    if task.state == "PENDING":
        return {**base, "progress": 0, "message": "任务排队中...", "result": None, "error": None}

    if task.state == "PROGRESS":
        meta = task.info or {}
        return {
            **base,
            "progress": meta.get("progress", 0),
            "message": meta.get("message", "处理中..."),
            "result": None,
            "error": None,
        }

    if task.state == "SUCCESS":
        payload = task.result
        # 审查失败的结果要"响亮"地暴露，不能返回 error=None 让前端以为成功了
        if isinstance(payload, dict) and payload.get("error"):
            return {
                **base,
                "progress": 100,
                "message": "已完成",
                "result": payload,
                "error": payload.get("error"),
            }
        return {**base, "progress": 100, "message": "已完成", "result": payload, "error": None}

    if task.state == "FAILURE":
        # task.info 是 ExceptionInfo(type, value, traceback)，提取 .value 拿到干净的错误信息
        error = "未知错误"
        if task.info:
            error = str(getattr(task.info, "value", None) or task.info)
        return {
            **base,
            "progress": 0,
            "message": "任务失败",
            "result": None,
            "error": error,
        }

    # STARTED / RETRY 等中间状态
    return {**base, "progress": 0, "message": f"状态: {task.state}", "result": None, "error": None}
