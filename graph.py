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
from utils import set_trace_id, log_info
from database import query_review_memory, save_review_memory


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


BATCH_SIZE = 5  # 每批处理的文件数


def _run_batched_review(directory: str) -> CodeReviewState:
    """
    分批审查目录下的所有文件。

    流程：
      1. 扫描目录获取所有文件
      2. 每 BATCH_SIZE 个文件为一批，逐批运行完整图
      3. 合并所有审查结果，生成一份统一报告
    """
    from tools.git_tools import scan_directory, get_file_language
    from agents.report_generator import report_generator_node
    from agents.aggregator import aggregator_node
    from datetime import datetime

    all_files = scan_directory(directory)
    if not all_files:
        state = empty_state()
        state["input_type"] = "directory"
        state["input_path"] = directory
        state["error"] = "目录中没有可审查的代码文件"
        state["report"] = "# ❌ 审查失败\n\n目录中没有可审查的代码文件。"
        state["review_status"] = "error"
        return state

    total_files = len(all_files)
    num_batches = (total_files + BATCH_SIZE - 1) // BATCH_SIZE
    graph = build_graph()

    all_findings = []
    all_fixes = []
    agent_errors = set()

    for batch_idx in range(num_batches):
        start = batch_idx * BATCH_SIZE
        end = start + BATCH_SIZE
        batch_files = all_files[start:end]

        state = empty_state()
        state["input_type"] = "directory"
        state["input_path"] = directory
        state["files_changed"] = batch_files
        state["total_files"] = len(batch_files)
        state["_batch_mode"] = True

        result = graph.invoke(state)

        all_findings.extend(result.get("aggregated_findings", []))
        all_fixes.extend(result.get("fix_suggestions", []))
        agent_errors.update(result.get("agent_errors", []))

    # ── 合并所有批次的结果，生成统一报告 ──
    merged_state = empty_state()
    merged_state["input_type"] = "directory"
    merged_state["input_path"] = directory
    merged_state["total_files"] = total_files
    merged_state["agent_errors"] = list(agent_errors)

    # 用聚合器处理合并后的 findings
    if all_findings or agent_errors:
        merge_state_for_agg = {
            "security_findings": [f for f in all_findings if f.get("category") == "security"],
            "performance_findings": [f for f in all_findings if f.get("category") == "performance"],
            "style_findings": [f for f in all_findings if f.get("category") == "style"],
            "logic_findings": [f for f in all_findings if f.get("category") == "logic"],
            "agent_errors": list(agent_errors),
            "error": "",
            "review_status": "aggregating",
        }
        agg_result = aggregator_node({**empty_state(), **merge_state_for_agg})
        merged_state.update(agg_result)
        merged_state["aggregated_findings"] = agg_result.get("aggregated_findings", all_findings)
        merged_state["summary"] = agg_result.get("summary", "")
        merged_state["stats"] = agg_result.get("stats", {})

        if agg_result.get("aggregated_findings"):
            # 有发现 → 尝试生成修复建议
            from agents.fix_generator import fix_generator_node
            fix_state = {**merged_state, "aggregated_findings": agg_result.get("aggregated_findings", [])}
            fix_result = fix_generator_node(fix_state)
            merged_state["fix_suggestions"] = fix_result.get("fix_suggestions", all_fixes)
        else:
            merged_state["fix_suggestions"] = []
    else:
        merged_state["aggregated_findings"] = []
        merged_state["summary"] = "✅ 代码审查通过，未发现任何问题。"
        merged_state["stats"] = {}
        merged_state["fix_suggestions"] = []

    # 生成统一报告
    final_state = {**empty_state(), **merged_state}
    report_result = report_generator_node(final_state)
    merged_state["report"] = report_result.get("report", "")
    merged_state["review_status"] = "done"

    # 添加批次信息到报告
    if num_batches > 1:
        batch_info = f"\n\n> 📦 共审查 {total_files} 个文件，分 {num_batches} 批完成。"
        merged_state["report"] += batch_info

    return merged_state


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

    # 设置链路追踪 ID
    trace_id = set_trace_id()
    log_info(f"审查开始", input_type=input_type, input_path=input_path, trace=trace_id)

    # 目录 → 分批处理
    if input_type == "directory":
        return _run_batched_review(input_path)

    graph = build_graph()
    initial_state = empty_state()
    initial_state["input_type"] = input_type
    initial_state["input_path"] = input_path

    # ── Agent 记忆注入：查询该文件的历史审查结果 ──
    if input_type == "file" and input_path:
        memory = query_review_memory(file_path=input_path, top_k=5)
        if memory:
            memory_summary = "\n".join(
                f"[{m['severity']}][{m['category']}] {m['title']} — {m['description'][:100]}"
                for m in memory
            )
            initial_state["_memory_context"] = (
                f"## 该文件历史审查记录\n以下是从前的审查发现，请注意这些是否已修复：\n{memory_summary}\n"
            )
            log_info(f"注入 {len(memory)} 条历史记忆", file_path=input_path, trace=trace_id)

    try:
        result = graph.invoke(initial_state)

        # 将本次结果存入记忆
        findings = result.get("aggregated_findings", [])
        review_id = result.get("review_id", None)
        if findings and review_id:
            save_review_memory(findings, review_id)

        elapsed = result.get("elapsed_seconds", 0)
        status = "成功" if not result.get("error") else "失败"
        log_info(f"审查{status}", trace=trace_id, elapsed=f"{elapsed}s")
        return result
    except Exception as e:
        initial_state["error"] = str(e)
        initial_state["review_status"] = "error"
        initial_state["report"] = f"# ❌ 审查失败\n\n系统错误: {e}"
        log_error("审查异常", exc=e, trace=trace_id)
        return initial_state
