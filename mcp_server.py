#!/usr/bin/env python3
"""
MCP Server — AI Code Review 的 MCP 协议封装
=============================================
让 Claude 可以直接通过 MCP 工具调用代码审查系统。

用法:
    # stdio 传输（默认，用于 Claude Code / Desktop）
    python mcp_server.py

    # SSE 传输（用于 Docker 部署）
    python mcp_server.py --transport sse --port 8080

注册到 Claude Code:
    在 claude.json / settings.json 中添加:
    {
        "mcpServers": {
            "ai-code-review": {
                "command": "python",
                "args": ["path/to/mcp_server.py"]
            }
        }
    }
"""
import argparse
import os
import sys
import time
import warnings

from dotenv import load_dotenv

load_dotenv()

# 确保可以 import 项目内的模块
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

warnings.filterwarnings("ignore", message="The default value of `allowed_objects`")

from mcp.server.fastmcp import FastMCP

from database import init_db, save_review, get_review, list_reviews, delete_review
from graph import run_review

# ── 启动时初始化数据库 ──
init_db()

# ── MCP Server 实例 ──
# host/port 仅在 SSE 模式生效；stdio 模式忽略它们
mcp = FastMCP(
    "AI Code Review",
    instructions="基于 LangGraph 的多 Agent 代码审查系统 — 审查代码安全、性能、风格、逻辑问题",
    host="0.0.0.0",
    port=8080,
)


# ═══════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════

def _do_review(input_type: str, input_path: str) -> str:
    """执行审查并保存到数据库，返回格式化的结果摘要"""
    start = time.time()
    state = run_review(input_type, input_path)
    elapsed = time.time() - start

    # 保存到数据库
    try:
        review_id = save_review(
            input_type=input_type,
            input_path=input_path,
            summary=state.get("summary", ""),
            report=state.get("report", ""),
            stats=state.get("stats", {}),
            status="completed" if not state.get("error") else "failed",
            error=state.get("error", ""),
            total_files=state.get("total_files", 0),
            elapsed_seconds=elapsed,
            findings=state.get("aggregated_findings", []),
            fix_suggestions=state.get("fix_suggestions", []),
        )
    except Exception as e:
        review_id = None

    # 拼装结果摘要
    stats = state.get("stats", {})
    total_issues = stats.get("total", 0)
    by_severity = {
        "critical": stats.get("critical", 0),
        "major": stats.get("major", 0),
        "minor": stats.get("minor", 0),
        "info": stats.get("info", 0),
    }
    by_category = {
        "security": stats.get("security", 0),
        "performance": stats.get("performance", 0),
        "style": stats.get("style", 0),
        "logic": stats.get("logic", 0),
    }

    if state.get("error") and not state.get("report"):
        return (
            f"## ❌ 审查失败\n\n"
            f"错误: {state['error']}\n"
            f"耗时: {elapsed:.1f}s\n"
        )

    report = state.get("report", "（审查未生成报告）")

    header = (
        f"**Review #{review_id}** | ⏱ {elapsed:.1f}s | "
        f"📁 {state.get('total_files', 0)} 个文件 | "
        f"🔍 {total_issues} 个问题\n\n"
    )

    if total_issues > 0:
        header += (
            f"| 严重度 | 数量 | | 类别 | 数量 |\n"
            f"|--------|------|-|------|------|\n"
            f"| 🔴 Critical | {by_severity['critical']} | | 🛡 安全 | {by_category['security']} |\n"
            f"| 🟠 Major | {by_severity['major']} | | ⚡ 性能 | {by_category['performance']} |\n"
            f"| 🟡 Minor | {by_severity['minor']} | | 🎨 风格 | {by_category['style']} |\n"
            f"| 🔵 Info | {by_severity['info']} | | 🧠 逻辑 | {by_category['logic']} |\n"
        )

    return header + "\n" + report


# ═══════════════════════════════════════════════════════════
#  MCP Tools
# ═══════════════════════════════════════════════════════════

@mcp.tool(description="审查 git 最新变更（默认 HEAD，可指定分支或 commit）")
def review_git_diff(ref: str = "HEAD") -> str:
    """
    审查 git diff 中的代码变更。

    参数:
        ref: Git 引用 — HEAD（未提交变更）、分支名、commit hash、HEAD~1 等
    返回:
        Markdown 格式的审查报告
    """
    return _do_review("git_diff", ref)


@mcp.tool(description="审查单个文件")
def review_file(file_path: str) -> str:
    """
    审查指定文件的内容。

    参数:
        file_path: 文件路径（绝对路径或相对于当前工作目录的路径）
    返回:
        Markdown 格式的审查报告
    """
    return _do_review("file", file_path)


@mcp.tool(description="审查整个目录下的所有代码文件")
def review_directory(dir_path: str) -> str:
    """
    审查目录下所有代码文件。

    参数:
        dir_path: 目录路径（绝对路径或相对于当前工作目录的路径）
    返回:
        Markdown 格式的审查报告
    """
    return _do_review("directory", dir_path)


@mcp.tool(description="列出最近的审查记录")
def list_review_history(limit: int = 10) -> str:
    """
    查看最近的代码审查历史记录。

    参数:
        limit: 返回的记录条数上限（默认 10）
    返回:
        审查记录列表（Markdown 表格）
    """
    records = list_reviews(limit=limit)
    if not records:
        return "暂无审查记录。"

    lines = ["## 📋 审查历史\n", "| ID | 类型 | 路径 | 状态 | 文件数 | 问题数 | 耗时 | 时间 |"]
    lines.append("|----|------|------|------|--------|--------|------|------|")

    for r in records:
        total = r.get("stats", {}).get("total", 0) if r.get("stats") else 0
        lines.append(
            f"| {r['id']} "
            f"| {r['input_type']} "
            f"| {r['input_path'][:40]} "
            f"| {'✅' if r['status'] == 'completed' else '❌'} "
            f"| {r['total_files']} "
            f"| {total} "
            f"| {r['elapsed_seconds']:.1f}s "
            f"| {r['created_at'][:19] if r.get('created_at') else '-'} |"
        )

    return "\n".join(lines)


@mcp.tool(description="查看某次审查的详细结果")
def get_review_detail(review_id: int) -> str:
    """
    根据 ID 获取某次审查的完整报告。

    参数:
        review_id: 审查记录 ID
    返回:
        完整的审查报告（Markdown）
    """
    record = get_review(review_id)
    if not record:
        return f"❌ 未找到 ID 为 {review_id} 的审查记录。"

    if record["status"] == "failed":
        return f"## ❌ 审查 #{review_id} 失败\n\n错误: {record.get('error', '未知错误')}"

    # 如果有 report 直接返回
    if record.get("report"):
        return record["report"]

    # 否则拼装
    findings = record.get("findings", [])
    fixes = record.get("fix_suggestions", [])

    lines = [f"# 📋 审查 #{review_id} 详情\n"]
    lines.append(f"**类型**: {record['input_type']} | **路径**: {record['input_path']}")
    lines.append(f"**状态**: ✅ 完成 | **文件**: {record['total_files']} | **耗时**: {record['elapsed_seconds']}s\n")

    if record.get("summary"):
        lines.append(f"**总结**: {record['summary']}\n")

    if findings:
        lines.append(f"## 发现的问题（共 {len(findings)} 个）\n")
        for f in findings:
            severity_icon = {"critical": "🔴", "major": "🟠", "minor": "🟡", "info": "🔵"}
            icon = severity_icon.get(f["severity"], "⚪")
            lines.append(f"### {icon} [{f['severity'].upper()}] {f['title']}")
            lines.append(f"- **文件**: {f['file']}:{f['line']}")
            lines.append(f"- **类别**: {f['category']}")
            if f["description"]:
                lines.append(f"- **描述**: {f['description']}")
            if f["suggestion"]:
                lines.append(f"- **建议**: {f['suggestion']}")
            if f["code_snippet"]:
                lines.append(f"```\n{f['code_snippet']}\n```")
            lines.append("")

    if fixes:
        lines.append(f"## 自动修复建议（共 {len(fixes)} 条）\n")
        for fx in fixes:
            lines.append(f"### {fx['file']}:{fx['line']}")
            lines.append(f"- **说明**: {fx['explanation']}")
            if fx["original"]:
                lines.append(f"- **原文**:\n```\n{fx['original']}\n```")
            if fx["suggested"]:
                lines.append(f"- **修复**:\n```\n{fx['suggested']}\n```")
            lines.append("")

    return "\n".join(lines)


@mcp.tool(description="删除指定的审查记录")
def delete_review_record(review_id: int) -> str:
    """
    删除某次审查记录及其关联数据。

    参数:
        review_id: 要删除的审查记录 ID
    返回:
        操作结果
    """
    ok = delete_review(review_id)
    return f"✅ 已删除审查 #{review_id}" if ok else f"❌ 未找到审查 #{review_id}"


# ═══════════════════════════════════════════════════════════
#  MCP Resources（可读资源，用于 Claude 主动访问）
# ═══════════════════════════════════════════════════════════

@mcp.resource("review://latest", description="获取最新的审查报告")
def get_latest_review() -> str:
    """获取最近一次审查的完整报告"""
    records = list_reviews(limit=1)
    if not records:
        return "暂无审查记录。"
    return get_review_detail(records[0]["id"])


@mcp.resource("review://{review_id}", description="获取指定 ID 的审查报告")
def get_review_by_id(review_id: int) -> str:
    """获取指定 ID 的审查报告"""
    return get_review_detail(review_id)


# ═══════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Code Review MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="传输协议: stdio（默认，供 Claude 调用）或 sse（HTTP 服务）",
    )
    parser.add_argument("--port", type=int, default=8080, help="SSE 模式监听端口（默认 8080）")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="SSE 模式监听地址（默认 0.0.0.0）")
    args = parser.parse_args()

    print(f"🤖 AI Code Review MCP Server 启动中...", file=sys.stderr)
    print(f"  📡 传输协议: {args.transport}", file=sys.stderr)
    if args.transport == "sse":
        print(f"  🌐 监听地址: {args.host}:{args.port}", file=sys.stderr)
    print(f"  💾 数据库: {os.getenv('DATABASE_URL', 'sqlite:///./data/reviews.db')}", file=sys.stderr)

    mcp.run(transport=args.transport)
