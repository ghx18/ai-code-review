"""
② 风格审查 Agent — 命名规范、代码风格、最佳实践（多语言）
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


STYLE_PROMPT = """你是一个资深代码评审专家，专注于代码风格和最佳实践。

当前审查的语言：{language}

请严格审查以下代码变更中的风格问题，只关注代码风格和最佳实践。
注意：根据语言自身的惯例来判断（如 Python 用 PEP8、Java 用 Google Style、Go 用 gofmt、Rust 用 rustfmt 等）。

审查维度：
1. 命名规范 — 不符合该语言约定俗成的命名惯例（大小写、分隔符等）
2. 函数/类过长 — 函数过长、类职责过多
3. 缺少类型声明 — 该语言支持类型注解但未使用
4. 缺少文档注释 — 公开函数/类没有文档注释
5. 重复代码 — 相同逻辑出现多次，应该抽取
6. 导入/模块管理不规范 — 未使用的导入、通配符导入、导入顺序混乱
7. 魔法数字/字符串 — 硬编码的值应该定义为常量
8. 过深的嵌套 — 超过 4 层的 if/for 嵌套
9. 未处理的异常 — 裸 except、忽略了特定异常、错误处理不当
10. 注释问题 — 过期注释、不必要的注释、该注释的地方没注释

对每个找到的问题，按 JSON 格式返回（只输出 JSON 数组，不要多余文字）：
[
  {{
    "file": "文件路径",
    "line": 行号,
    "severity": "critical|major|minor|info",
    "title": "问题标题",
    "description": "为什么这是个风格问题",
    "suggestion": "怎么改进",
    "category": "style",
    "code_snippet": "相关代码片段"
  }}
]

如果没有风格问题，返回空数组 []。

代码变更：
{code}
"""


def style_review_node(state: CodeReviewState) -> dict:
    """风格审查 Agent 节点"""
    import json, re

    files = state.get("files_changed", [])
    if not files:
        return {"style_findings": []}

    review_files = [f for f in files if f.get("change_type") in ("added", "modified")]
    if not review_files:
        return {"style_findings": []}

    code = format_diff_for_review(review_files)
    if not code.strip():
        return {"style_findings": []}

    lang = _get_languages(review_files)
    prompt = STYLE_PROMPT.replace("{language}", lang).replace("{code}", code)

    text, ok = safe_invoke(prompt, temperature=0.1)
    if not ok:
        log(f"[风格审查] 跳过（API不可用）: {text}")
        return {"style_findings": []}

    json_match = re.search(r'\[.*\]', text, re.DOTALL)
    if json_match:
        findings = json.loads(json_match.group())
        return {"style_findings": findings}
    return {"style_findings": []}
