#!/usr/bin/env python3
"""
FastAPI Application — REST API + WebSocket + MCP 挂载
=======================================================
AI Code Review 的统一 HTTP 服务层。

用法:
    # 开发模式
    uvicorn api:app --reload --port 8000

    # 生产模式
    uvicorn api:app --host 0.0.0.0 --port 8000

    # 直接运行
    python api.py

Docker 中默认使用此入口。
"""
import asyncio
import os
import sys
import time
import warnings
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# 确保项目根目录在 path 中
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

warnings.filterwarnings("ignore", message="The default value of `allowed_objects`")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from database import init_db, save_review, get_review, list_reviews, delete_review
from graph import run_review
from monitoring import metrics_endpoint, API_REQUESTS, API_LATENCY, REVIEW_TOTAL, REVIEW_LATENCY, REVIEW_ISSUES

# ── 启动时初始化数据库 ──
init_db()

# ── FastAPI 应用 ──
app = FastAPI(
    title="AI Code Review API",
    description="基于 LangGraph 的多 Agent 代码审查系统 — REST API + WebSocket + MCP",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS（给前端用）──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 简单 IP 限流（防恶意刷接口）──
_RATE_LIMIT = {
    "max_requests": 20,        # 每个 IP 每分钟最多 20 次
    "window": 60,              # 时间窗口（秒）
    "records": {},             # {ip: [timestamps]}
}


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # 静态文件和健康检查不限流
    path = request.url.path
    if path in ("/health", "/static", "/") or path.startswith("/static/"):
        return await call_next(request)

    ip = request.client.host
    now = time.time()
    window = _RATE_LIMIT["window"]
    max_req = _RATE_LIMIT["max_requests"]

    # 清理过期记录
    timestamps = _RATE_LIMIT["records"].get(ip, [])
    timestamps = [t for t in timestamps if now - t < window]
    _RATE_LIMIT["records"][ip] = timestamps

    if len(timestamps) >= max_req:
        return JSONResponse(
            status_code=429,
            content={
                "error": "请求过于频繁，请稍后再试",
                "message": f"每分钟最多 {max_req} 次请求",
            },
        )

    _RATE_LIMIT["records"][ip].append(now)
    return await call_next(request)

# ── 静态文件（前端页面）──
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    """前端页面"""
    return FileResponse("static/index.html")


# ═══════════════════════════════════════════════════════════
#  MCP SSE 子路由
# ═══════════════════════════════════════════════════════════

@app.on_event("startup")
async def mount_mcp():
    """延迟挂载 MCP SSE 子应用（避免循环导入）"""
    from mcp_server import mcp as mcp_server
    # sse_app() 默认 mount_path=""，因为 FastAPI 已经负责 /mcp 前缀
    mcp_sse = mcp_server.sse_app()
    app.mount("/mcp", mcp_sse, name="mcp")
    print(f"[api] MCP SSE mounted at /mcp")
    print(f"[api]   SSE endpoint:  /mcp/sse")
    print(f"[api]   Messages endpoint: /mcp/messages/")
    print(f"[api]   Swagger docs:  /docs")


# ═══════════════════════════════════════════════════════════
#  请求/响应模型
# ═══════════════════════════════════════════════════════════

class ReviewRequest(BaseModel):
    """审查请求"""
    input_type: str = Field(
        ..., description="输入类型: git_diff / file / directory",
        json_schema_extra={"example": "git_diff"},
    )
    input_path: str = Field(
        ..., description="路径: HEAD / 文件路径 / 目录路径",
        json_schema_extra={"example": "HEAD"},
    )


class CodeReviewRequest(BaseModel):
    """粘贴代码审查请求"""
    code: str = Field(..., description="要审查的代码内容")
    language: str = Field("python", description="代码语言")
    filename: str = Field("code.py", description="文件名标识")


class ReviewResponse(BaseModel):
    """审查响应"""
    review_id: Optional[int] = None
    status: str
    summary: str = ""
    stats: dict = {}
    total_files: int = 0
    elapsed_seconds: float = 0.0
    report: str = ""
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════════

def _execute_review(input_type: str, input_path: str) -> tuple[dict, float, Optional[int]]:
    """执行审查并保存到数据库，返回 (result, elapsed_seconds, review_id)"""
    with API_LATENCY.labels(endpoint="/api/review").time():
        start = time.time()
        result = run_review(input_type, input_path)
        elapsed = time.time() - start

    # 记录监控指标
    status = "failed" if result.get("error") else "completed"
    REVIEW_TOTAL.labels(input_type=input_type, status=status).inc()
    REVIEW_LATENCY.labels(input_type=input_type).observe(elapsed)

    stats = result.get("stats", {})
    if stats:
        for sev in ("critical", "major", "minor", "info"):
            count = stats.get(sev, 0)
            if count:
                REVIEW_ISSUES.labels(severity=sev).set(count)

    try:
        review_id = save_review(
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
    except Exception:
        review_id = None

    return result, elapsed, review_id


# ═══════════════════════════════════════════════════════════
#  REST API
# ═══════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "ok",
        "service": "ai-code-review",
        "version": "1.0.0",
    }


@app.get("/metrics")
async def metrics():
    """Prometheus 监控指标"""
    return Response(content=metrics_endpoint(), media_type="text/plain")


@app.post("/api/review", response_model=ReviewResponse)
async def start_review(req: ReviewRequest):
    """
    执行代码审查并返回结果。

    - `git_diff` 模式: `input_path` 可以是 `HEAD`、分支名、commit hash
    - `file` 模式: `input_path` 是文件路径
    - `directory` 模式: `input_path` 是目录路径
    """
    if req.input_type not in ("git_diff", "file", "directory"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 input_type: {req.input_type}，可选: git_diff / file / directory",
        )

    result, elapsed, review_id = await asyncio.to_thread(
        _execute_review, req.input_type, req.input_path
    )

    is_error = bool(result.get("error"))

    return ReviewResponse(
        review_id=review_id,
        status="failed" if is_error else "completed",
        summary=result.get("summary", ""),
        stats=result.get("stats", {}),
        total_files=result.get("total_files", 0),
        elapsed_seconds=round(elapsed, 2),
        report=result.get("report", ""),
        error=result.get("error") if is_error else None,
    )


@app.post("/api/review/code", response_model=ReviewResponse)
async def review_code(req: CodeReviewRequest):
    """
    审查粘贴的代码内容（无需文件路径，直接传代码）。
    """
    import tempfile

    # 写到临时文件
    suffix = Path(req.filename).suffix or ".py"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    ) as f:
        f.write(req.code)
        tmp_path = f.name

    try:
        result, elapsed, review_id = await asyncio.to_thread(
            _execute_review, "file", tmp_path
        )
    finally:
        os.unlink(tmp_path)

    is_error = bool(result.get("error"))

    return ReviewResponse(
        review_id=review_id,
        status="failed" if is_error else "completed",
        summary=result.get("summary", ""),
        stats=result.get("stats", {}),
        total_files=result.get("total_files", 0),
        elapsed_seconds=round(elapsed, 2),
        report=result.get("report", ""),
        error=result.get("error") if is_error else None,
    )


# ═══════════════════════════════════════════════════════════
#  异步任务 (Celery + Redis)
# ═══════════════════════════════════════════════════════════

@app.post("/api/review/async", status_code=202)
async def start_review_async(req: ReviewRequest):
    """
    异步提交代码审查任务（不阻塞，立即返回 task_id）。

    用返回的 task_id 轮询 GET /api/tasks/{task_id} 获取结果。
    """
    from celery_app import review_task as rt, worker_available
    from database import save_task

    if req.input_type not in ("git_diff", "file", "directory"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 input_type: {req.input_type}，可选: git_diff / file / directory",
        )

    # 没有 worker 的话任务永远排队，直接 503，别让客户端干等
    if not worker_available():
        raise HTTPException(
            status_code=503,
            detail="没有可用的 Celery worker（或 Redis 不可达），任务无法执行，请稍后再试",
        )

    task = rt.delay(req.input_type, req.input_path)

    # 落库：让 GET /api/tasks/{id} 能区分"任务不存在"和"任务在排队"
    #（否则 Celery 对不存在的 task_id 也返回 PENDING，前端会一直误以为在排队）
    try:
        save_task(task.id, req.input_type, req.input_path)
    except Exception:
        pass  # 落库失败不阻塞任务提交

    return {
        "task_id": task.id,
        "status": "pending",
        "detail": f"任务已提交，使用 GET /api/tasks/{task.id} 查询进度",
    }


@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    """
    查询异步任务的当前状态和结果。

    状态流转:
        PENDING → PROGRESS → SUCCESS / FAILURE
    """
    from celery_app import get_task_result
    from database import get_task

    # 先查注册表：没提交过的 task_id 直接 404
    #（否则 Celery 对不存在的任务也返回 PENDING，用户会误以为"排队中"）
    record = get_task(task_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    try:
        result = get_task_result(task_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无效的 task_id: {e}")

    # 结果 7 天过期（celery_app.result_expires）。过期后 Celery 也返回 PENDING，
    # 需要按注册表里的创建时间区分"真在排队" vs "结果已过期"
    if result.get("state") == "PENDING" and time.time() - record["created_at"] > 7 * 24 * 3600:
        result = {**result, "state": "EXPIRED", "message": "任务结果已过期（保留 7 天），请重新提交"}

    return result


@app.get("/api/reviews")
async def list_reviews_endpoint(
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
):
    """查询审查历史记录"""
    records = list_reviews(limit=limit, offset=offset)
    return {
        "total": len(records),
        "offset": offset,
        "limit": limit,
        "reviews": records,
    }


@app.get("/api/reviews/{review_id}")
async def get_review_endpoint(review_id: int):
    """获取单次审查的详细信息"""
    record = get_review(review_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"审查记录 #{review_id} 不存在")
    return record


@app.delete("/api/reviews/{review_id}", status_code=204)
async def delete_review_endpoint(review_id: int):
    """删除指定的审查记录"""
    if not delete_review(review_id):
        raise HTTPException(status_code=404, detail=f"审查记录 #{review_id} 不存在")


@app.get("/api/stats")
async def get_stats():
    """获取审查统计概览"""
    records = list_reviews(limit=1000)
    total = len(records)
    completed = sum(1 for r in records if r["status"] == "completed")
    failed = sum(1 for r in records if r["status"] == "failed")
    total_issues = sum(
        r.get("stats", {}).get("total", 0)
        for r in records if r.get("stats")
    )

    return {
        "total_reviews": total,
        "completed": completed,
        "failed": failed,
        "total_issues_found": total_issues,
    }


# ═══════════════════════════════════════════════════════════
#  WebSocket — 实时审查推送
# ═══════════════════════════════════════════════════════════

# 任务提交后超过这么久还停留在"排队中"，判定 worker 不可用，给用户报错而不是无限等
_WS_STUCK_AFTER_SECONDS = 120


@app.websocket("/ws/review")
async def review_websocket(websocket: WebSocket):
    """
    WebSocket 实时审查 — 基于 Celery 异步任务。

    客户端发送 JSON:
        {"input_type": "git_diff", "input_path": "HEAD"}

    服务端推送:
        {"type": "progress", "message": "...", "progress": N}  — 任务真实进度
        {"type": "result", ...}                               — 最终结果
        {"type": "error", "message": "..."}                   — 错误信息
    """
    from celery_app import review_task as rt, get_task_result, worker_available
    from database import save_task

    await websocket.accept()
    try:
        data = await websocket.receive_json()
        input_type = data.get("input_type", "")
        input_path = data.get("input_path", "")

        if not input_type or not input_path:
            await websocket.send_json({
                "type": "error",
                "message": "缺少 input_type 或 input_path",
            })
            return
        if input_type not in ("git_diff", "file", "directory"):
            await websocket.send_json({
                "type": "error",
                "message": f"不支持的 input_type: {input_type}，可选: git_diff / file / directory",
            })
            return

        # 提交前先探活：没有 worker 的话任务永远排队，不如直接报错
        if not worker_available():
            await websocket.send_json({
                "type": "error",
                "message": "没有可用的 Celery worker（或 Redis 不可达），任务无法执行。请确认 redis 和 worker 已启动。",
            })
            return

        # 提交到 Celery 队列（复用 worker，不再自己开线程）
        try:
            task = rt.delay(input_type, input_path)
        except Exception as e:
            await websocket.send_json({
                "type": "error",
                "message": f"任务提交失败（Redis 可能未运行）: {e}",
            })
            return
        try:
            save_task(task.id, input_type, input_path)
        except Exception:
            pass  # 落库失败不阻塞

        await websocket.send_json({
            "type": "progress",
            "message": "任务已提交，排队中...",
            "progress": 5,
        })

        # 轮询任务状态：客户端断开只会停止轮询，worker 里的审查继续跑，不阻塞事件循环
        start = time.time()
        while True:
            status = get_task_result(task.id)
            state = status.get("state")

            if state == "SUCCESS":
                payload = status.get("result") or {}
                await websocket.send_json({
                    "type": "result",
                    "review_id": payload.get("review_id"),
                    "status": payload.get("status", "completed"),
                    "summary": payload.get("summary", ""),
                    "stats": payload.get("stats", {}),
                    "total_files": payload.get("total_files", 0),
                    "elapsed_seconds": payload.get("elapsed_seconds", 0),
                    "report": payload.get("report", ""),
                    "error": payload.get("error"),
                    "fix_suggestions": payload.get("fix_suggestions", []),
                })
                break

            if state in ("FAILURE", "EXPIRED"):
                await websocket.send_json({
                    "type": "error",
                    "message": status.get("message", "任务失败"),
                    "error": status.get("error", "未知错误"),
                })
                break

            # 卡死兜底：提交后很久还在排队，多半是 worker 挂了/被卡，别再让用户无限等
            if state == "PENDING" and time.time() - start > _WS_STUCK_AFTER_SECONDS:
                await websocket.send_json({
                    "type": "error",
                    "message": "任务长时间未开始执行（可能 worker 不可用），请检查 worker 状态后重新提交。",
                })
                break

            # 还在排队/进行中：推送 worker 上报的真实进度（5→15→…→95）
            await websocket.send_json({
                "type": "progress",
                "message": f"{status.get('message', '审查进行中')}（已耗时 {int(time.time() - start)}s）",
                "progress": status.get("progress", 5),
            })

            # 非阻塞轮询间隔 1 秒
            await asyncio.sleep(1.0)

    except WebSocketDisconnect:
        # 客户端断开：只退出轮询。Celery 任务在 worker 里继续，事件循环不受影响
        pass
    except Exception as e:
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"审查异常: {str(e)}",
            })
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))

    print(f"🤖 AI Code Review API 启动中...")
    print(f"  🌐 http://{host}:{port}")
    print(f"  📋 Docs: http://{host}:{port}/docs")
    print(f"  🔌 MCP:  http://{host}:{port}/mcp/sse")

    uvicorn.run(
        app,  # 直接传 app 对象，不用字符串模块路径
        host=host,
        port=port,
        reload=os.getenv("API_RELOAD", "false").lower() == "true",
    )
