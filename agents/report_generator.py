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
    skipped = state.get("skipped_files", 0)
    if skipped:
        report_parts.append(f"| ⚠️ 跳过文件 | {skipped} 个（超出审查上限） |")
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
                    report_parts.append(f"  ```{lang if lang != 'unknown' else ''}")
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

    if error:
        report_parts.append(f"❌ **审查服务不可用：** 部分或全部审查 Agent 无法连接到 AI 服务，请稍后重试。")
        report_parts.append(f"")
        report_parts.append(f"这可能是因为 DeepSeek API 暂时不可用、网络连接异常或 API Key 配置问题。")
    elif total == 0:
        if skipped:
            report_parts.append(f"⚠️ 仅审查了部分文件，被跳过的 {skipped} 个文件未被检查。")
        else:
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


# ════════════════════════════════════════════════════════
#  HTML 报告渲染（自包含单文件，内联 CSS，可直接浏览器打开）
# ════════════════════════════════════════════════════════

_SEV_COLORS = {
    "critical": "#dc2626",
    "major": "#ea580c",
    "minor": "#d97706",
    "info": "#2563eb",
}
_CAT_LABELS = {"security": "安全", "performance": "性能", "style": "风格", "logic": "逻辑"}
_TYPE_LABELS = {"git_diff": "Git 变更", "file": "文件", "directory": "目录"}


def render_html_report(state: dict) -> str:
    """把审查结果渲染成自包含 HTML 报告。

    - 内联 CSS、无外部依赖，可直接浏览器打开或嵌入
    - 所有 AI 输出都做 HTML 转义，避免破坏结构 / XSS
    """
    import html as _html

    def esc(s) -> str:
        return _html.escape(str(s if s is not None else ""))

    input_path = state.get("input_path", "")
    input_type = state.get("input_type", "")
    error = state.get("error", "")
    stats = state.get("stats", {})
    summary = state.get("summary", "")
    total_files = state.get("total_files", 0)
    skipped = state.get("skipped_files", 0)
    findings = state.get("aggregated_findings", [])
    fixes = state.get("fix_suggestions", [])
    agent_errors = state.get("agent_errors", [])
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── CSS ──
    css = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#f3f4f6;color:#1f2937;padding:24px}
.container{max-width:880px;margin:0 auto}
header{background:linear-gradient(135deg,#111827,#374151);color:#fff;border-radius:12px;padding:22px 26px;margin-bottom:16px}
header h1{font-size:22px;margin-bottom:8px}
header .meta{font-size:13px;color:#d1d5db;line-height:1.9}
.panel{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:20px 24px;margin-bottom:16px}
.panel h2{font-size:16px;margin-bottom:14px;padding-bottom:8px;border-bottom:2px solid #f3f4f6}
.summary-line{font-size:15px;font-weight:600}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin-top:14px}
.card{flex:1;min-width:88px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;padding:12px;text-align:center}
.card .num{font-size:24px;font-weight:700}
.card .label{font-size:12px;color:#6b7280;margin-top:2px}
.card.critical .num{color:#dc2626}.card.major .num{color:#ea580c}
.card.minor .num{color:#d97706}.card.info .num{color:#2563eb}
.badges{display:flex;gap:8px;flex-wrap:wrap}
.badge{font-size:12px;padding:4px 10px;border-radius:999px;background:#f3f4f6;color:#374151}
.badge.warn{background:#fef2f2;color:#dc2626}
.finding{border:1px solid #e5e7eb;border-left:4px solid #9ca3af;border-radius:8px;padding:14px 16px;margin-bottom:12px}
.finding .head{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px}
.finding .title{font-weight:600;font-size:14px}
.finding .loc{font-size:12px;color:#6b7280;font-family:Consolas,monospace}
.finding .desc{font-size:13px;color:#374151;line-height:1.7;margin-bottom:6px}
.finding .sugg{font-size:13px;color:#065f46;background:#ecfdf5;border-radius:6px;padding:8px 10px;margin-top:4px}
.finding pre{margin-top:8px;background:#0f172a;color:#e2e8f0;border-radius:6px;padding:10px 12px;overflow-x:auto;font-size:12px;line-height:1.5}
.severity-tag{font-size:11px;color:#fff;padding:2px 8px;border-radius:999px}
.fix{border:1px solid #e5e7eb;border-radius:8px;padding:12px 16px;margin-bottom:10px}
.fix .loc{font-family:Consolas,monospace;font-size:12px;color:#6b7280}
.fix .exp{font-size:13px;margin:6px 0}
.diff{background:#0f172a;color:#e2e8f0;border-radius:6px;padding:10px 12px;font-size:12px;font-family:Consolas,monospace;line-height:1.6;overflow-x:auto}
.diff .minus{color:#f87171}.diff .plus{color:#4ade80}
.err{background:#fef2f2;border:1px solid #fecaca;color:#b91c1c;border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:13px}
footer{text-align:center;font-size:12px;color:#9ca3af;margin-top:8px;padding-bottom:12px}
@media(max-width:600px){body{padding:12px}}
"""

    parts = []
    parts.append('<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    parts.append(f"<title>AI 代码审查报告</title><style>{css}</style></head><body><div class=\"container\">")

    # ── 头部 ──
    parts.append("<header><h1>🤖 AI 代码审查报告</h1>")
    parts.append(f"<div class=\"meta\">审查目标: <code>{esc(input_path)}</code><br>")
    parts.append(f"审查类型: {_TYPE_LABELS.get(input_type, esc(input_type))} ｜ 审查时间: {now}</div></header>")

    # ── 错误提示 ──
    if error:
        parts.append(f"<div class=\"err\">⚠️ 审查过程出现错误: {esc(error)}</div>")
    if agent_errors:
        bad = "、".join(_CAT_LABELS.get(e, e) for e in agent_errors)
        parts.append(f"<div class=\"err\">⚠️ 部分审查 Agent 不可用: {esc(bad)}，对应维度可能缺失</div>")

    # ── 总览 ──
    total = stats.get("total", 0)
    parts.append('<div class="panel"><h2>📊 审查总览</h2>')
    if summary:
        parts.append(f'<div class="summary-line">{esc(summary)}</div>')
    parts.append('<div class="cards">')
    parts.append(f'<div class="card"><div class="num">{total_files}</div><div class="label">审查文件</div></div>')
    parts.append(f'<div class="card"><div class="num">{total}</div><div class="label">问题总数</div></div>')
    for sev, label in [("critical", "严重"), ("major", "主要"), ("minor", "次要"), ("info", "建议")]:
        parts.append(f'<div class="card {sev}"><div class="num">{stats.get(sev, 0)}</div><div class="label">{label}</div></div>')
    parts.append("</div>")
    if skipped:
        parts.append(f'<div class="badges" style="margin-top:12px"><span class="badge warn">⚠️ 跳过 {skipped} 个文件（超出上限）</span></div>')
    # 维度分布
    cat_counts = [(c, stats.get(c, 0)) for c in ["security", "performance", "style", "logic"] if stats.get(c, 0) > 0]
    if cat_counts:
        parts.append('<div class="badges" style="margin-top:10px">')
        for c, n in cat_counts:
            parts.append(f'<span class="badge">{_CAT_LABELS.get(c, c)} {n}</span>')
        parts.append("</div>")
    parts.append("</div>")

    # ── 问题详情 ──
    if findings:
        parts.append('<div class="panel"><h2>🔍 问题详情</h2>')
        for sev in ["critical", "major", "minor", "info"]:
            sev_findings = [f for f in findings if f.get("severity") == sev]
            if not sev_findings:
                continue
            color = _SEV_COLORS.get(sev, "#6b7280")
            sev_name = SEVERITY_LABELS.get(sev, sev)
            parts.append(f'<h3 style="font-size:14px;margin:14px 0 10px"><span class="severity-tag" style="background:{color}">{sev_name}</span> {len(sev_findings)} 个</h3>')
            for f in sev_findings:
                title = esc(f.get("title", ""))
                desc = esc(f.get("description", ""))
                sugg = esc(f.get("suggestion", ""))
                code = f.get("code_snippet", "")
                file_path = f.get("file", "")
                line = f.get("line", 0)
                loc = f"{esc(file_path)}:{line}" if line else esc(file_path)
                cat = _CAT_LABELS.get(f.get("category", ""), f.get("category", ""))
                parts.append(f'<div class="finding {sev}">')
                parts.append(f'<div class="head"><span class="title">{title}</span>'
                             f'<span class="loc">📍 {loc}</span>'
                             f'<span class="badge">{esc(cat)}</span></div>')
                parts.append(f'<div class="desc">{desc}</div>')
                if sugg:
                    parts.append(f'<div class="sugg">🔧 建议: {sugg}</div>')
                if code:
                    lang = get_file_language(file_path)
                    parts.append(f"<pre><code>{esc(code)}</code></pre>")
                parts.append("</div>")
        parts.append("</div>")

    # ── 自动修复建议 ──
    if fixes:
        parts.append('<div class="panel"><h2>🛠️ 自动修复建议</h2>')
        for i, fix in enumerate(fixes, 1):
            f_path = esc(fix.get("file", ""))
            f_line = fix.get("line", 0)
            original = str(fix.get("original", ""))
            suggested = str(fix.get("suggested", ""))
            explanation = esc(fix.get("explanation", ""))
            parts.append('<div class="fix">')
            parts.append(f'<div class="loc">修复 {i}: {f_path}:{f_line}</div>')
            if explanation:
                parts.append(f'<div class="exp">{explanation}</div>')
            if original or suggested:
                parts.append('<div class="diff">')
                for line in original.splitlines():
                    parts.append(f'<div class="minus">- {esc(line)}</div>')
                for line in suggested.splitlines():
                    parts.append(f'<div class="plus">+ {esc(line)}</div>')
                parts.append("</div>")
            parts.append("</div>")
        parts.append("</div>")

    # ── 总结建议 ──
    parts.append('<div class="panel"><h2>📝 总结建议</h2>')
    if error:
        parts.append("<div>❌ 审查服务不可用：部分或全部审查 Agent 无法连接 AI 服务，请稍后重试。</div>")
    elif total == 0:
        if skipped:
            parts.append(f"⚠️ 仅审查了部分文件，被跳过的 {skipped} 个文件未被检查。")
        else:
            parts.append("✅ 代码质量良好，未发现明显问题。")
    else:
        if stats.get("critical", 0) > 0:
            parts.append("⚠️ 存在严重问题，建议修复后再合并。")
        elif stats.get("major", 0) > 0:
            parts.append("📌 存在需要关注的问题，建议在合并前修复。")
        else:
            parts.append("💡 代码整体质量良好，少量次要问题和建议可选择性处理。")
        notes = []
        if stats.get("security", 0) > 0:
            notes.append(f"🛡️ 安全方面存在 {stats['security']} 个问题，建议优先处理。")
        if stats.get("logic", 0) > 0:
            notes.append(f"🧠 逻辑方面存在 {stats['logic']} 个问题，建议在上线前确认。")
        if notes:
            parts.append(f'<div style="margin-top:8px">{"<br>".join(notes)}</div>')
    parts.append("</div>")

    parts.append('<footer>报告由 AI Code Review 系统自动生成</footer>')
    parts.append("</div></body></html>")
    return "\n".join(parts)
