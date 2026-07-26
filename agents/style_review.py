"""
② 风格审查 Agent — 命名规范、代码风格、最佳实践
==================================================
"""
from tools.llm import get_llm
from tools.git_tools import format_diff_for_review
from state import CodeReviewState
from utils import log


STYLE_PROMPT = """你是一个资深代码评审专家，专注于代码风格和最佳实践。

请严格审查以下代码变更中的风格问题，只关注代码风格和最佳实践。

审查维度：
1. 命名规范 — 类名 CamelCase、函数/变量 snake_case（Python）
2. 函数/类过长 — 函数超过 50 行、类超过 300 行
3. 缺少类型注解 — Python 函数参数/返回值未标注类型
4. 缺少文档字符串 — 公开函数/类没有文档
5. 重复代码 — 相同逻辑出现多次，应该抽取
6. 导入不规范 — 未使用的导入、通配符导入、导入顺序
7. 魔法数字 — 硬编码的数字应该定义为常量
8. 过深的嵌套 — 超过 4 层的 if/for 嵌套
9. 未处理的异常 — 裸 except、忽略了特定异常
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

    prompt = STYLE_PROMPT.replace("{code}", code)

    try:
        llm = get_llm(temperature=0.1)
        resp = llm.invoke(prompt)
        text = resp.content if hasattr(resp, "content") else str(resp)

        json_match = re.search(r'\[.*\]', text, re.DOTALL)
        if json_match:
            findings = json.loads(json_match.group())
            return {"style_findings": findings}
        return {"style_findings": []}
    except Exception as e:
        log(f"[风格审查] 失败: {e}")
        return {"style_findings": []}
