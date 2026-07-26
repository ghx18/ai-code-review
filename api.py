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
import concurrent.futures
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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from database import init_db, save_review, get_review, list_reviews, delete_review
from graph import run_review

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
    start = time.time()
    result = run_review(input_type, input_path)
    elapsed = time.time() - start

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
    from celery_app import review_task as rt

    if req.input_type not in ("git_diff", "file", "directory"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 input_type: {req.input_type}，可选: git_diff / file / directory",
        )

    task = rt.delay(req.input_type, req.input_path)
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

    try:
        result = get_task_result(task_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无效的 task_id: {e}")

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

@app.websocket("/ws/review")
async def review_websocket(websocket: WebSocket):
    """
    WebSocket 实时审查。

    客户端发送 JSON:
        {"input_type": "git_diff", "input_path": "HEAD"}

    服务端推送:
        {"type": "progress", "message": "..."}  — 进度更新
        {"type": "result", ...}                  — 最终结果
        {"type": "error", "message": "..."}      — 错误信息
    """
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

        await websocket.send_json({
            "type": "progress",
            "message": f"正在分析代码变更 ({input_type}: {input_path})...",
            "progress": 10,
        })

        # 在后台线程执行审查，同时通过 WebSocket 推送进度
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(_execute_review, input_type, input_path)

            # 轮询进度
            while not future.done():
                await websocket.send_json({
                    "type": "progress",
                    "message": "审查进行中（安全/性能/风格/逻辑 Agent 并行审查）...",
                    "progress": 50,
                })
                try:
                    await asyncio.wait_for(
                        asyncio.wrap_future(future), timeout=3.0
                    )
                except asyncio.TimeoutError:
                    continue

            result, elapsed, review_id = future.result()

        is_error = bool(result.get("error"))

        await websocket.send_json({
            "type": "progress",
            "message": "审查完成，正在生成报告...",
            "progress": 90,
        })

        await websocket.send_json({
            "type": "result",
            "review_id": review_id,
            "status": "failed" if is_error else "completed",
            "summary": result.get("summary", ""),
            "stats": result.get("stats", {}),
            "total_files": result.get("total_files", 0),
            "elapsed_seconds": round(elapsed, 2),
            "report": result.get("report", ""),
            "error": result.get("error") if is_error else None,
            "fix_suggestions": result.get("fix_suggestions", []),
        })

    except WebSocketDisconnect:
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
