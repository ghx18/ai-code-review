"""
LangGraph 图构建 — 编排所有 Agent 节点
========================================
"""
import sys
import warnings
warnings.filterwarnings("ignore", message="The default value of `allowed_objects`")

from langgraph.graph import StateGraph, END
from state import CodeReviewState, empty_state

from agents.diff_analyzer import diff_analyzer_node
from agents.security_review import security_review_node
from agents.performance_review import performance_review_node
from agents.style_review import style_review_node
from agents.logic_review import logic_review_node
from agents.aggregator import aggregator_node
from agents.fix_generator import fix_generator_node
from agents.report_generator import report_generator_node


def router_after_diff_analyzer(state: CodeReviewState) -> str:
    """
    变更分析后的路由：
    - 有 error/无文件 → 直接去报告（跳过耗时的 LLM 审查）
    - 正常 → 去 fan_out（分发到并行审查）
    """
    if state.get("error") or not state.get("files_changed"):
        return "report"
    return "review"


def fan_out_node(state: CodeReviewState) -> dict:
    """空节点：只负责把状态传到并行审查节点"""
    return {}


def router_after_aggregator(state: CodeReviewState) -> str:
    """聚合后的条件路由"""
    if state.get("error"):
        return "error"
    if state.get("aggregated_findings"):
        return "has_findings"
    return "no_findings"


def build_graph():
    """
    LangGraph 图结构：

    diff_analyzer
        │
        ├── (error/无文件) → report_generator → END
        │
        └── (ok) → fan_out → security_review ──┐
                              ├→ performance ───┤
                              ├→ style ────────┤
                              └→ logic ────────┤
                                                │
                                             aggregator
                                                │
                                          ┌─────┴─────┐
                                          │           │
                                      fix_generator  │
                                          │           │
                                          └─────┬─────┘
                                                │
                                            report_generator
                                                │
                                                END
    """
    builder = StateGraph(CodeReviewState)

    # ── 添加所有节点 ──
    builder.add_node("diff_analyzer", diff_analyzer_node)
    builder.add_node("fan_out", fan_out_node)
    builder.add_node("security_review", security_review_node)
    builder.add_node("performance_review", performance_review_node)
    builder.add_node("style_review", style_review_node)
    builder.add_node("logic_review", logic_review_node)
    builder.add_node("aggregator", aggregator_node)
    builder.add_node("fix_generator", fix_generator_node)
    builder.add_node("report_generator", report_generator_node)

    # ── 入口 ──
    builder.set_entry_point("diff_analyzer")

    # ── 变更分析 → 条件路由 ──
    # 关键：只用条件边，不加无条件边，避免冲突
    builder.add_conditional_edges(
        "diff_analyzer",
        router_after_diff_analyzer,
        {
            "report": "report_generator",  # 出错 → 直接出报告
            "review": "fan_out",           # 正常 → 分发到并行审查
        },
    )

    # ── fan_out → 并行审查（fan_out 只有无条件边，不会有冲突）──
    builder.add_edge("fan_out", "security_review")
    builder.add_edge("fan_out", "performance_review")
    builder.add_edge("fan_out", "style_review")
    builder.add_edge("fan_out", "logic_review")

    # ── 并行审查 → 聚合 ──
    builder.add_edge("security_review", "aggregator")
    builder.add_edge("performance_review", "aggregator")
    builder.add_edge("style_review", "aggregator")
    builder.add_edge("logic_review", "aggregator")

    # ── 聚合 → 条件路由 ──
    builder.add_conditional_edges(
        "aggregator",
        router_after_aggregator,
        {
            "has_findings": "fix_generator",
            "no_findings": "report_generator",
            "error": "report_generator",
        },
    )

    # ── 修复 → 报告 ──
    builder.add_edge("fix_generator", "report_generator")

    # ── 报告 → 结束 ──
    builder.add_edge("report_generator", END)

    # （aggregator 通过条件边路由到 fix_generator 或 report_generator）

    # ── 编译 ──
    return builder.compile()


def run_review(input_type: str, input_path: str) -> CodeReviewState:
    """
    运行代码审查

    参数:
        input_type: "git_diff" / "file" / "directory"
        input_path: 分支名 / 文件路径 / 目录路径

    返回:
        最终 state（包含 report）
    """
    if hasattr(sys.stdin, "reconfigure"):
        try:
            sys.stdin.reconfigure(encoding="utf-8")
        except Exception:
            pass

    graph = build_graph()
    initial_state = empty_state()
    initial_state["input_type"] = input_type
    initial_state["input_path"] = input_path

    try:
        result = graph.invoke(initial_state)
        return result
    except Exception as e:
        initial_state["error"] = str(e)
        initial_state["review_status"] = "error"
        initial_state["report"] = f"# ❌ 审查失败\n\n系统错误: {e}"
        return initial_state
