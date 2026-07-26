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


@celery_app.task(bind=True, max_retries=2, default_retry_delay=5)
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
        result = run_review(input_type, input_path)
        elapsed = time.time() - start

        self.update_state(
            state="PROGRESS",
            meta={"progress": 70, "message": "审查完成，正在保存结果..."},
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
        }

    except Exception as exc:
        self.update_state(
            state="FAILURE",
            meta={"progress": 0, "message": f"审查异常: {exc}"},
        )
        raise self.retry(exc=exc)


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
        return {**base, "progress": 100, "message": "已完成", "result": task.result, "error": None}

    if task.state == "FAILURE":
        return {
            **base,
            "progress": 0,
            "message": "任务失败",
            "result": None,
            "error": str(task.info) if task.info else "未知错误",
        }

    # STARTED / RETRY 等中间状态
    return {**base, "progress": 0, "message": f"状态: {task.state}", "result": None, "error": None}
