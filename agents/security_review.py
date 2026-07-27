"""
② 安全审查 Agent — SQL注入、XSS、敏感信息泄露等（多语言）
===========================================================
"""
from tools.llm import safe_invoke
from tools.git_tools import format_diff_for_review
from state import CodeReviewState
from utils import log


def _get_languages(files: list) -> str:
    """提取文件列表中涉及的语言"""
    langs = set()
    for f in files:
        lang = f.get("language", "unknown")
        if lang and lang != "unknown":
            langs.add(lang)
    return "、".join(sorted(langs)) if langs else "未知"


SECURITY_PROMPT = """你是一个资深安全工程师，负责安全审查。

当前审查的语言：{language}

请严格审查以下代码变更中的安全问题，只关注安全漏洞，不要管其他问题。

审查维度（根据语言调整）：
1. SQL注入风险 — 直接拼接 SQL 字符串、未使用参数化查询
2. 命令注入 — 拼接 shell 命令、使用 exec/subprocess/ProcessBuilder 处理用户输入
3. 敏感信息泄露 — 硬编码密码/密钥/token/API Key
4. XSS 风险 — 未转义直接输出用户输入
5. 路径遍历 — 未校验用户输入的文件路径
6. 不安全的反序列化 — pickle/json/eval/unsafe deserialization
7. 权限缺失 — 未校验用户权限的操作
8. CSRF / SSRF — 服务端发起未经验证的请求
9. 依赖安全 — 使用已知有漏洞的库/版本
10. 输入验证缺失 — 未校验用户输入的合法性

对每个找到的问题，按 JSON 格式返回（只输出 JSON 数组，不要多余文字）：
[
  {{
    "file": "文件路径",
    "line": 行号,
    "severity": "critical|major|minor|info",
    "title": "问题标题",
    "description": "为什么这是个安全问题",
    "suggestion": "怎么修复",
    "category": "security",
    "code_snippet": "相关代码片段"
  }}
]

如果没有安全问题，返回空数组 []。

代码变更：
{code}
"""


def security_review_node(state: CodeReviewState) -> dict:
    """安全审查 Agent 节点"""
    import json, re

    files = state.get("files_changed", [])
    if not files:
        return {"security_findings": []}

    # 只审查新增/修改的文件
    review_files = [f for f in files if f.get("change_type") in ("added", "modified")]
    if not review_files:
        return {"security_findings": []}

    code = format_diff_for_review(review_files)
    if not code.strip():
        return {"security_findings": []}

    lang = _get_languages(review_files)
    prompt = SECURITY_PROMPT.replace("{language}", lang).replace("{code}", code)

    text, ok = safe_invoke(prompt, temperature=0.1)
    if not ok:
        log(f"[安全审查] 跳过（API不可用）: {text}")
        return {"security_findings": [], "agent_errors": ["security"]}

    # 提取 JSON
    json_match = re.search(r'\[.*\]', text, re.DOTALL)
    if json_match:
        findings = json.loads(json_match.group())
        return {"security_findings": findings}
    return {"security_findings": []}
