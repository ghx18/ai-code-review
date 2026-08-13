"""
② 逻辑审查 Agent — 空指针、边界条件、并发问题等（多语言）
===========================================================
"""
from state import CodeReviewState
from agents.agent_utils import run_batched_review


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

核心原则（必须遵守）：
1. 不要假设调用方会保证输入合法。代码可能在任意输入下运行，请按"最坏情况输入"评估：空集合、None/null、0、负数、边界值、超大值。
2. 代码长度不影响审查强度：即使是 1-3 行的短函数，也要逐个维度逐行验证。短代码里的缺陷往往最隐蔽（如越界、除零、判断写反），不要因为"函数太短"就默认没问题。
3. 审查场景中，漏报的代价远高于误报。只要缺陷在某种合法输入下必然触发，就应当报告；宁可多报可疑问题，也不要因为"不常见"而漏掉。
4. 同时要保持精确：只报告能在某个合法输入下确定复现的缺陷；不要报告编码偏好、命名风格、文档注释类建议（这些交给风格审查 Agent 处理）。
5. 对每个函数，先在心中用边界输入"模拟执行一遍"，确认是否存在越界/空值/除零/语义错误，再下结论。

审查维度：
1. 空指针/空值检查 — 可能为 null/None/nil/undefined 的变量未判空就直接使用；含嵌套访问（如 user["profile"]["age"]）未判断中间层是否可能缺失
2. 数组越界 — 访问列表/数组时未校验索引范围；特别注意 items[len(items)]、items[i+1] 这类必然/可能越界的写法
3. 除零错误 — 除法前未检查除数是否为 0
4. 并发安全 — 共享变量未加锁、线程不安全的数据结构
5. 竞态条件 — 检查-执行模式不是原子的（TOCTOU）
6. 错误处理缺失 — 未处理的异常、吞掉异常、错误返回码未检查
7. 逻辑矛盾 — if 条件永远为 true/false、死代码
8. 类型错误 — 类型不匹配的操作、隐式类型转换导致的问题
9. 资源泄漏 — 打开的文件/连接/流未关闭
10. 状态不一致 — 多个相关变量未同时更新
11. 边界条件遗漏 — 空集合、单元素集合、最大/最小值；比较运算符是否含边界（如成年判断应为 >= 18 而非 > 18）
12. 无限循环 — 循环终止条件可能永远不满足
13. 语义反写 — 函数名/变量名与实现相反（如 is_odd 返回 n % 2 == 0、withdraw 返回逻辑颠倒）

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
    files = state.get("files_changed", [])
    if not files:
        return {"logic_findings": []}

    review_files = [f for f in files if f.get("change_type") in ("added", "modified")]
    if not review_files:
        return {"logic_findings": []}

    lang = _get_languages(review_files)
    memory = state.get("_memory_context", "")
    # 按文件分批送 LLM（每批独立 token 预算），避免大 diff 截断丢中间段
    findings, had_error = run_batched_review(
        LOGIC_PROMPT, review_files, "logic", lang,
        memory_context=memory,
    )

    # 全部批次都失败才算 Agent 不可用；部分失败保留成功批次的结果
    if had_error and not findings:
        return {"logic_findings": [], "agent_errors": ["logic"]}
    return {"logic_findings": findings}
