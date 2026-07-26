#!/usr/bin/env python3
"""
AI Code Review — CLI 入口
==========================

用法：
    # 审查 git 最近的变更
    python main.py --git HEAD

    # 审查某个分支的变更
    python main.py --git feature/my-branch

    # 审查单个文件
    python main.py --file path/to/file.py

    # 审查整个目录
    python main.py --dir path/to/dir

    # 输出到文件
    python main.py --git HEAD --output report.md

    # JSON 格式输出
    python main.py --git HEAD --format json
"""
import argparse
import json
import os
import sys
import time
import warnings

# 确保从项目根目录可以 import tools.* / agents.* / graph
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
warnings.filterwarnings("ignore", message="The default value of `allowed_objects`")


def ensure_utf8():
    """确保 stdin/stdout 支持 UTF-8"""
    if hasattr(sys.stdin, "reconfigure"):
        try:
            sys.stdin.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass


def resolve_path(path: str) -> str:
    """
    解析文件/目录路径：
    - 如果是相对路径，基于当前工作目录解析
    - 如果是绝对路径，直接使用
    - 对于 git diff 模式，直接返回原值
    """
    if os.path.isabs(path):
        return path
    # 相对于 cwd 解析
    abs_path = os.path.abspath(path)
    return abs_path


def main():
    ensure_utf8()

    parser = argparse.ArgumentParser(
        description="AI Code Review — 基于 LangGraph 的多 Agent 代码审查系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python main.py --git HEAD             审查最近未提交的变更
  python main.py --git HEAD~1           审查上一次 commit
  python main.py --file foo.py          审查单个文件
  python main.py --dir ./src            审查整个目录
  python main.py --git main --output report.md --format markdown
        """,
    )

    # 输入来源（三选一）
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--git", type=str, nargs="?", const="HEAD",
                             help="审查 git diff（默认 HEAD，可指定分支/commit）")
    input_group.add_argument("--file", type=str, help="审查单个文件路径")
    input_group.add_argument("--dir", type=str, help="审查目录路径")

    # 输出选项
    parser.add_argument("--output", "-o", type=str, help="输出到文件")
    parser.add_argument("--format", "-f", choices=["markdown", "json"], default="markdown",
                        help="输出格式（默认 markdown）")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细进度")

    args = parser.parse_args()

    is_json = args.format == "json"

    # ── 确定输入类型和路径 ──
    if args.git:
        input_type = "git_diff"
        input_path = args.git
    elif args.file:
        input_type = "file"
        input_path = resolve_path(args.file)
        if not os.path.exists(input_path):
            _fatal(f"文件不存在: {input_path}")
    elif args.dir:
        input_type = "directory"
        input_path = resolve_path(args.dir)
        if not os.path.isdir(input_path):
            _fatal(f"目录不存在: {input_path}")
    else:
        parser.print_help()
        sys.exit(1)

    # 检查 API Key
    from tools.llm import check_api_key
    if not check_api_key():
        sys.exit(1)

    # ── 开始审查（JSON 模式不输出过程）──
    if not is_json:
        print("\n" + "=" * 60)
        print("  🤖 AI Code Review")
        print("=" * 60)
        print(f"  输入类型: {input_type}")
        print(f"  输入路径: {input_path}")
        print()
        print_progress("🔍 分析代码变更...")

    start_time = time.time()
    from graph import run_review

    result = run_review(input_type, input_path)
    elapsed = time.time() - start_time

    # ── 检查错误（JSON 模式也输出错误）──
    if result.get("error") and result.get("review_status") in ("error", "analyzing"):
        if is_json:
            print(json.dumps({
                "success": False,
                "error": result["error"],
                "elapsed_seconds": round(elapsed, 1),
            }, ensure_ascii=False))
        else:
            print(f"\n  ❌ 审查失败: {result['error']}")
        sys.exit(1)

    stats = result.get("stats", {})
    total_files = result.get("total_files", 0)

    # ── JSON 输出（纯净 JSON，无其他文字）──
    if is_json:
        output = json.dumps({
            "success": True,
            "summary": result.get("summary", ""),
            "stats": stats,
            "total_files": total_files,
            "findings": result.get("aggregated_findings", []),
            "fix_suggestions": result.get("fix_suggestions", []),
            "report": result.get("report", ""),
            "elapsed_seconds": round(elapsed, 1),
        }, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
        else:
            print(output)
        return

    # ── Markdown 输出 ──
    if total_files == 0:
        print(f"  ⚠️  没有找到可审查的文件")
    else:
        print(f"  📊 审查完成: {total_files} 个文件, {stats.get('total', 0)} 个问题")

    output = result.get("report", "")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"  ✅ 报告已保存到: {args.output}")
    else:
        print("\n" + "=" * 60)
        print("  审查报告")
        print("=" * 60)
        print()
        print(output)

    print(f"  ⏱  耗时: {elapsed:.1f} 秒")


def print_progress(msg: str):
    """打印进度信息"""
    print(f"  {msg}", flush=True)


def _fatal(msg: str):
    """打印错误并退出"""
    print(f"\n  ❌ {msg}")
    sys.exit(1)


if __name__ == "__main__":
    main()
