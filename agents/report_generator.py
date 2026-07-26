"""
⑤ 报告生成 Agent — 生成 Markdown 格式审查报告
==============================================
"""
from datetime import datetime
from state import CodeReviewState
from tools.git_tools import get_file_language

SEVERITY_LABELS = {
    "critical": "🔴 严重",
    "major": "🟠 主要",
    "minor": "🟡 次要",
    "info": "🔵 建议",
}


def report_generator_node(state: CodeReviewState) -> dict:
    """报告生成 Agent 节点"""
    report_parts = []

    # ── 标题 ──
    input_path = state.get("input_path", "")
    report_parts.append(f"# 📋 AI 代码审查报告")
    report_parts.append(f"")
    report_parts.append(f"- **审查目标**: `{input_path}`")
    report_parts.append(f"- **审查时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_parts.append(f"- **审查类型**: {state.get('input_type', '')}")

    # ── 错误信息 ──
    error = state.get("error", "")
    if error:
        report_parts.append(f"")
        report_parts.append(f"## ⚠️ 审查过程出现错误")
        report_parts.append(f"")
        report_parts.append(f"```")
        report_parts.append(error)
        report_parts.append(f"```")

    # ── 总览 ──
    stats = state.get("stats", {})
    total = stats.get("total", 0)
    summary = state.get("summary", "")

    report_parts.append(f"")
    report_parts.append(f"## 📊 审查总览")
    report_parts.append(f"")
    report_parts.append(f"| 指标 | 数值 |")
    report_parts.append(f"|------|------|")
    report_parts.append(f"| 审查文件数 | {state.get('total_files', 0)} |")
    report_parts.append(f"| 发现问题数 | {total} |")

    if stats:
        report_parts.append(f"| 严重问题 | {stats.get('critical', 0)} |")
        report_parts.append(f"| 主要问题 | {stats.get('major', 0)} |")
        report_parts.append(f"| 次要问题 | {stats.get('minor', 0)} |")
        report_parts.append(f"| 建议 | {stats.get('info', 0)} |")

    report_parts.append(f"")
    report_parts.append(f"**{summary}**")
    report_parts.append(f"")

    # ── 各维度分布 ──
    if stats:
        report_parts.append(f"### 各维度分布")
        report_parts.append(f"")
        report_parts.append(f"| 维度 | 数量 |")
        report_parts.append(f"|------|------|")
        for cat_name in ["security", "performance", "style", "logic"]:
            cat_label = {"security": "安全", "performance": "性能", "style": "风格", "logic": "逻辑"}
            count = stats.get(cat_name, 0)
            if count > 0:
                report_parts.append(f"| {cat_label.get(cat_name, cat_name)} | {count} |")
        report_parts.append(f"")

    # ── 问题详情 ──
    findings = state.get("aggregated_findings", [])
    if findings:
        report_parts.append(f"## 🔍 问题详情")
        report_parts.append(f"")

        for sev in ["critical", "major", "minor", "info"]:
            sev_findings = [f for f in findings if f.get("severity") == sev]
            if not sev_findings:
                continue

            report_parts.append(f"### {SEVERITY_LABELS.get(sev, sev)} ({len(sev_findings)} 个)")
            report_parts.append(f"")

            for i, f in enumerate(sev_findings, 1):
                file_path = f.get("file", "")
                line = f.get("line", 0)
                title = f.get("title", "")
                desc = f.get("description", "")
                suggestion = f.get("suggestion", "")
                code = f.get("code_snippet", "")

                report_parts.append(f"**{i}. {title}**")
                report_parts.append(f"")
                if file_path:
                    loc = f"`{file_path}`" + (f":{line}" if line else "")
                    report_parts.append(f"- 📍 **位置**: {loc}")
                report_parts.append(f"- 💬 **说明**: {desc}")
                if suggestion:
                    report_parts.append(f"- 🔧 **建议**: {suggestion}")
                if code:
                    lang = get_file_language(file_path)
                    report_parts.append(f"")
                    report_parts.append(f"  ```{lang if lang != 'unknown' else 'python'}")
                    report_parts.append(f"  {code}")
                    report_parts.append(f"  ```")
                report_parts.append(f"")

    # ── 自动修复建议 ──
    fixes = state.get("fix_suggestions", [])
    if fixes:
        report_parts.append(f"## 🛠️ 自动修复建议")
        report_parts.append(f"")

        for i, fix in enumerate(fixes, 1):
            file_path = fix.get("file", "")
            line = fix.get("line", 0)
            original = fix.get("original", "")
            suggested = fix.get("suggested", "")
            explanation = fix.get("explanation", "")

            report_parts.append(f"### 修复 {i}: `{file_path}:{line}`")
            report_parts.append(f"")
            report_parts.append(f"**{explanation}**")
            report_parts.append(f"")
            if original:
                report_parts.append(f"```diff")
                report_parts.append(f"- {original}")
                report_parts.append(f"+ {suggested}")
                report_parts.append(f"```")
            report_parts.append(f"")

    # ── 总结建议 ──
    report_parts.append(f"## 📝 总结建议")
    report_parts.append(f"")

    if total == 0:
        report_parts.append(f"✅ 代码质量良好，未发现明显问题。")
    else:
        if stats.get("critical", 0) > 0:
            report_parts.append(f"⚠️ 存在严重问题，建议修复后再合并。")
        elif stats.get("major", 0) > 0:
            report_parts.append(f"📌 存在需要关注的问题，建议在合并前修复。")
        else:
            report_parts.append(f"💡 代码整体质量良好，少量次要问题和建议可选择性处理。")

        report_parts.append(f"")
        if stats.get("security", 0) > 0:
            report_parts.append(f"- 🛡️ **安全**方面存在 {stats['security']} 个问题，建议优先处理。")
        if stats.get("logic", 0) > 0:
            report_parts.append(f"- 🧠 **逻辑**方面存在 {stats['logic']} 个问题，建议在上线前确认。")

    report_parts.append(f"")
    report_parts.append(f"---")
    report_parts.append(f"*报告由 AI Code Review 系统自动生成*")

    report = "\n".join(report_parts)

    return {
        "report": report,
        "review_status": "done",
    }
