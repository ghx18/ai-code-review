"""
③ 聚合 Agent — 去重、排序、分类所有审查结果
==============================================
"""
from state import CodeReviewState, SEVERITY_ORDER

# 4 个审查 Agent 的名字
_REVIEW_AGENTS = ["security", "performance", "style", "logic"]


def aggregator_node(state: CodeReviewState) -> dict:
    """
    聚合所有审查 Agent 的结果：
    1. 检查是否有 Agent 不可用
    2. 合并 4 个维度的 findings
    3. 去重（根据 file + line + title）
    4. 按严重度排序
    5. 统计各维度数量
    """
    all_findings = []
    all_findings.extend(state.get("security_findings", []))
    all_findings.extend(state.get("performance_findings", []))
    all_findings.extend(state.get("style_findings", []))
    all_findings.extend(state.get("logic_findings", []))

    # ── 检查 Agent 服务状态 ──
    agent_errors = state.get("agent_errors", [])
    failed_agents = [a for a in _REVIEW_AGENTS if a in agent_errors]
    all_agents_failed = len(failed_agents) == len(_REVIEW_AGENTS)

    # 所有 Agent 都挂了 → 服务不可用
    if all_agents_failed and not all_findings:
        return {
            "aggregated_findings": [],
            "summary": "❌ 审查服务暂时不可用，请稍后重试。",
            "stats": {},
            "has_critical_issues": False,
            "review_status": "reporting",
            "error": "所有审查 Agent 均无法连接 DeepSeek API",
        }

    if not all_findings:
        summary = "✅ 代码审查通过，未发现任何问题。"
        if failed_agents:
            summary += f" ⚠️ 部分 Agent 不可用（{', '.join(failed_agents)}），结果可能不完整。"
        return {
            "aggregated_findings": [],
            "summary": summary,
            "stats": {},
            "has_critical_issues": False,
            "review_status": "reporting",
        }

    # ── 去重 ──
    seen = set()
    unique_findings = []
    for f in all_findings:
        # 用 (file, line, title) 作为唯一键
        key = (f.get("file", ""), f.get("line", 0), f.get("title", ""))
        if key not in seen:
            seen.add(key)
            # 确保 category 字段存在
            if "category" not in f:
                f["category"] = "unknown"
            unique_findings.append(f)

    # ── 按严重度排序 ──
    unique_findings.sort(
        key=lambda x: (
            SEVERITY_ORDER.get(x.get("severity", "info"), 99),
            x.get("file", ""),
            x.get("line", 0),
        )
    )

    # ── 统计 ──
    stats = {
        "total": len(unique_findings),
        "critical": sum(1 for f in unique_findings if f.get("severity") == "critical"),
        "major": sum(1 for f in unique_findings if f.get("severity") == "major"),
        "minor": sum(1 for f in unique_findings if f.get("severity") == "minor"),
        "info": sum(1 for f in unique_findings if f.get("severity") == "info"),
    }

    # 各维度统计
    for cat in ["security", "performance", "style", "logic"]:
        stats[cat] = sum(1 for f in unique_findings if f.get("category") == cat)

    # ── 摘要 ──
    has_critical = stats["critical"] > 0
    summary_parts = []

    if has_critical:
        summary_parts.append(f"🔴 发现 {stats['critical']} 个严重问题")
    if stats["major"] > 0:
        summary_parts.append(f"🟠 {stats['major']} 个主要问题")
    if stats["minor"] > 0:
        summary_parts.append(f"🟡 {stats['minor']} 个次要问题")
    if stats["info"] > 0:
        summary_parts.append(f"🔵 {stats['info']} 个建议")

    summary = f"共发现 {stats['total']} 个问题。" + " ".join(summary_parts)

    if failed_agents:
        summary += f" ⚠️ 部分 Agent 不可用（{', '.join(failed_agents)}），结果可能不完整。"

    return {
        "aggregated_findings": unique_findings,
        "summary": summary,
        "stats": stats,
        "has_critical_issues": has_critical,
        "review_status": "fixing" if unique_findings else "reporting",
    }
