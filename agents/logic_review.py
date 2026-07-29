"""
② 逻辑审查 Agent — 空指针、边界条件、并发问题等（多语言）
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


LOGIC_PROMPT = """你是一个资深软件工程师，专注于代码逻辑正确性。

当前审查的语言：{language}

请严格审查以下代码变更中的逻辑问题，只关注逻辑正确性。
注意：根据语言的类型系统特性调整审查（如 Java 的空指针、Rust 的所有权、Python 的动态类型等）。

审查维度：
1. 空指针/空值检查 — 可能为 null/None/nil/undefined 的变量未判空就直接使用
2. 数组越界 — 访问列表/数组时未校验索引范围
3. 除零错误 — 除法前未检查除数是否为 0
4. 并发安全 — 共享变量未加锁、线程不安全的数据结构
5. 竞态条件 — 检查-执行模式不是原子的（TOCTOU）
6. 错误处理缺失 — 未处理的异常、吞掉异常、错误返回码未检查
7. 逻辑矛盾 — if 条件永远为 true/false、死代码
8. 类型错误 — 类型不匹配的操作、隐式类型转换导致的问题
9. 资源泄漏 — 打开的文件/连接/流未关闭
10. 状态不一致 — 多个相关变量未同时更新
11. 边界条件遗漏 — 空集合、单元素集合、最大/最小值
12. 无限循环 — 循环终止条件可能永远不满足

对每个找到的问题，按 JSON 格式返回（只输出 JSON 数组，不要多余文字）：
[
  {{
    "file": "文件路径",
    "line": 行号,
    "severity": "critical|major|minor|info",
    "title": "问题标题",
    "description": "为什么这是个逻辑问题",
    "suggestion": "怎么修复",
    "category": "logic",
    "code_snippet": "相关代码片段"
  }}
]

如果没有逻辑问题，返回空数组 []。

代码变更：
{code}
"""


def logic_review_node(state: CodeReviewState) -> dict:
    """逻辑审查 Agent 节点"""
    import json, re

    files = state.get("files_changed", [])
    if not files:
        return {"logic_findings": []}

    review_files = [f for f in files if f.get("change_type") in ("added", "modified")]
    if not review_files:
        return {"logic_findings": []}

    code = format_diff_for_review(review_files, max_tokens=4000)
    memory = state.get("_memory_context", "")
    if memory:
        code = memory + "\n" + code
    if not code.strip():
        return {"logic_findings": []}

    lang = _get_languages(review_files)
    prompt = LOGIC_PROMPT.replace("{language}", lang).replace("{code}", code)

    text, ok = safe_invoke(prompt, temperature=0.1)
    if not ok:
        log(f"[逻辑审查] 跳过（API不可用）: {text}")
        return {"logic_findings": [], "agent_errors": ["logic"]}

    json_match = re.search(r'\[.*\]', text, re.DOTALL)
    if json_match:
        try:
            findings = json.loads(json_match.group())
            return {"logic_findings": findings}
        except json.JSONDecodeError as e:
            log(f"[逻辑审查] JSON 解析失败: {e}")
            return {"logic_findings": []}
    return {"logic_findings": []}
