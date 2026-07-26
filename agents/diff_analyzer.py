"""
① 变更分析 Agent — 解析 git diff / 文件，提取变更信息
====================================================
不调 LLM，纯代码工具。
"""
import os
from state import CodeReviewState
from tools.git_tools import (
    get_git_diff,
    parse_diff,
    read_file_content,
    scan_directory,
    format_diff_for_review,
)


def diff_analyzer_node(state: CodeReviewState) -> dict:
    """
    LangGraph 节点：分析变更

    根据 input_type 选择解析方式：
      - "git_diff": 解析 git diff
      - "file": 读取单个文件
      - "directory": 扫描目录
    """
    try:
        input_type = state.get("input_type", "")
        input_path = state.get("input_path", "")

        if input_type == "git_diff":
            return _handle_git_diff(input_path)
        elif input_type == "file":
            return _handle_single_file(input_path)
        elif input_type == "directory":
            return _handle_directory(input_path)
        else:
            return {"error": f"不支持的输入类型: {input_type}", "review_status": "error"}

    except Exception as e:
        return {"error": f"变更分析失败: {e}", "review_status": "error"}


def _handle_git_diff(ref: str) -> dict:
    """处理 git diff 输入"""
    diff_content = get_git_diff(ref)
    if not diff_content or not diff_content.strip():
        return {
            "error": f"没有找到变更内容（{ref}），请检查分支名或 commit",
            "review_status": "error",
        }

    files = parse_diff(diff_content)
    if not files:
        return {
            "error": "没有检测到可审查的代码文件变更",
            "review_status": "error",
        }

    review_content = format_diff_for_review(files)

    return {
        "diff_content": diff_content,
        "files_changed": files,
        "total_files": len(files),
        "review_status": "reviewing",
    }


def _handle_single_file(filepath: str) -> dict:
    """处理单文件输入"""
    if not os.path.exists(filepath):
        return {"error": f"文件不存在: {filepath}", "review_status": "error"}

    content = read_file_content(filepath)
    if content is None:
        return {"error": f"无法读取文件（可能不是文本文件）: {filepath}", "review_status": "error"}

    from tools.git_tools import get_file_language, should_skip_file
    if should_skip_file(filepath):
        return {"error": f"跳过非审查文件: {filepath}", "review_status": "error"}

    filename = os.path.basename(filepath)
    lang = get_file_language(filepath)

    files = [{
        "path": filepath,
        "change_type": "added",
        "language": lang,
        "additions": len(content.splitlines()),
        "deletions": 0,
        "diff_content": "",
        "content": content,
    }]

    return {
        "files_changed": files,
        "total_files": 1,
        "review_status": "reviewing",
    }


def _handle_directory(directory: str) -> dict:
    """处理目录输入（最多处理 5 个文件，避免超时）"""
    MAX_FILES = 5

    if not os.path.isdir(directory):
        return {"error": f"目录不存在: {directory}", "review_status": "error"}

    files = scan_directory(directory)
    if not files:
        return {"error": f"目录中没有找到可审查的代码文件: {directory}", "review_status": "error"}

    # 限制文件数，避免 LLM 上下文超长
    if len(files) > MAX_FILES:
        from utils import log
        log(f"⚠️ 目录中有 {len(files)} 个文件，仅审查前 {MAX_FILES} 个（用 --file 逐个审查）")
        files = files[:MAX_FILES]

    return {
        "files_changed": files,
        "total_files": len(files),
        "review_status": "reviewing",
    }
