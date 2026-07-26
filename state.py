"""
Code Review State — 所有 Agent 共享的状态定义
===============================================
"""
from typing import TypedDict, Optional


class FileChange(TypedDict):
    """单个文件的变更信息"""
    path: str                  # 文件路径（相对于项目根目录）
    change_type: str           # added / modified / deleted / renamed
    language: str              # python / javascript / java / go / unknown
    additions: int             # 新增行数
    deletions: int             # 删除行数
    diff_content: str          # 该文件的 diff 内容
    content: str               # 文件完整内容（用于单文件审查模式）


class Finding(TypedDict):
    """单个审查发现的问题"""
    file: str                  # 文件路径
    line: int                  # 行号（0 = 不针对特定行）
    severity: str              # critical / major / minor / info
    title: str                 # 问题标题
    description: str           # 问题描述（为什么这是个问题）
    suggestion: str            # 修改建议（怎么改）
    category: str              # security / performance / style / logic
    code_snippet: str          # 相关的代码片段


class FixSuggestion(TypedDict):
    """自动修复建议"""
    file: str                  # 文件路径
    line: int                  # 行号
    original: str              # 原文（需要替换的代码）
    suggested: str             # 修复后的代码
    explanation: str           # 为什么这么改


class CodeReviewState(TypedDict):
    """
    LangGraph 共享状态
    所有 Agent 节点读写同一个 state 字典
    """
    # ── 输入 ──
    input_type: str            # "git_diff" / "file" / "directory"
    input_path: str            # 分支名/commit / 文件路径 / 目录路径

    # ── 阶段1: 变更分析 ──
    diff_content: str          # 原始 diff 内容
    files_changed: list        # List[FileChange]
    analysis_error: str        # 分析阶段的错误

    # ── 阶段2: 并行审查 ──
    security_findings: list    # List[Finding]
    performance_findings: list # List[Finding]
    style_findings: list       # List[Finding]
    logic_findings: list       # List[Finding]

    # ── 阶段3: 聚合 ──
    aggregated_findings: list  # List[Finding]（去重排序后）
    summary: str               # 一句话总结
    stats: dict                # 各维度统计

    # ── 阶段4: 修复建议 ──
    fix_suggestions: list      # List[FixSuggestion]

    # ── 阶段5: 报告 ──
    report: str                # Markdown 报告

    # ── 控制 ──
    error: str                 # 错误信息
    review_status: str         # analyzing / reviewing / aggregating / fixing / reporting / done / error
    has_critical_issues: bool  # 是否有严重问题
    total_files: int           # 审查的文件总数


def empty_state() -> CodeReviewState:
    """创建空状态"""
    return {
        "input_type": "",
        "input_path": "",
        "diff_content": "",
        "files_changed": [],
        "analysis_error": "",
        "security_findings": [],
        "performance_findings": [],
        "style_findings": [],
        "logic_findings": [],
        "aggregated_findings": [],
        "summary": "",
        "stats": {},
        "fix_suggestions": [],
        "report": "",
        "error": "",
        "review_status": "analyzing",
        "has_critical_issues": False,
        "total_files": 0,
    }


SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3}
