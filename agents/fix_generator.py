"""
④ 修复建议 Agent — 对每个问题生成修复代码
===========================================
"""
from tools.llm import safe_invoke
from state import CodeReviewState
from utils import log


FIX_PROMPT = """你是一个自动代码修复专家。根据以下代码审查发现的问题，生成具体的修复建议。

对每个问题，返回 JSON 格式（只输出 JSON 数组，不要多余文字）：
[
  {{
    "file": "文件路径",
    "line": 行号,
    "original": "原文代码（需要替换的部分）",
    "suggested": "修复后的代码",
    "explanation": "为什么这么改"
  }}
]

如果没有需要修复的问题（如 info 级别），返回空数组 []。

审查发现的问题：
{findings}
"""


def fix_generator_node(state: CodeReviewState) -> dict:
    """修复建议 Agent 节点"""
    import json, re

    findings = state.get("aggregated_findings", [])
    if not findings:
        return {"fix_suggestions": []}

    # 只对 critical 和 major 级别生成修复
    fixable = [f for f in findings if f.get("severity") in ("critical", "major")]
    if not fixable:
        return {"fix_suggestions": []}

    # 简化 findings 用于 prompt（避免太长）
    simplified = []
    for f in fixable[:10]:  # 最多修复前 10 个问题
        simplified.append({
            "file": f.get("file", ""),
            "line": f.get("line", 0),
            "severity": f.get("severity", ""),
            "title": f.get("title", ""),
            "description": f.get("description", ""),
            "code_snippet": f.get("code_snippet", ""),
        })

    prompt = FIX_PROMPT.format(findings=json.dumps(simplified, ensure_ascii=False, indent=2))

    text, ok = safe_invoke(prompt, temperature=0.2)
    if not ok:
        log(f"[修复建议] 跳过（API不可用）: {text}")
        return {"fix_suggestions": []}

    json_match = re.search(r'\[.*\]', text, re.DOTALL)
    if json_match:
        suggestions = json.loads(json_match.group())
        return {"fix_suggestions": suggestions}
    return {"fix_suggestions": []}
