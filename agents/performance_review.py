"""
② 性能审查 Agent — 慢查询、不必要的循环、缓存等（多语言）
===========================================================
"""
from tools.llm import get_llm
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


PERFORMANCE_PROMPT = """你是一个资深性能优化工程师，负责性能审查。

当前审查的语言：{language}

请严格审查以下代码变更中的性能问题，只关注性能，不要管其他问题。
注意：根据语言特性调整审查标准（例如 Python 关注 GIL、JavaScript 关注事件循环、Java 关注 JVM 内存等）。

审查维度：
1. 不必要的循环/递归 — 可以用向量操作/批量处理代替
2. 数据库 N+1 查询 — 在循环中查数据库
3. 大对象加载 — 一次性加载大量数据到内存
4. 缓存使用不当 — 应该缓存但没缓存的重复计算
5. 资源未释放 — 文件句柄、数据库连接、网络连接未关闭
6. 重复计算 — 相同的计算结果可以复用
7. 低效的数据结构 — 选型不当（如用 list 做频繁查找应该用 set/dict/Map/Set）
8. 频繁的 I/O 操作 — 可以批量合并的单次读写
9. 不合适的并发粒度 — 锁粒度太大/太小
10. 内存泄漏 — 不断增长的数据结构、全局缓存未清理

对每个找到的问题，按 JSON 格式返回（只输出 JSON 数组，不要多余文字）：
[
  {{
    "file": "文件路径",
    "line": 行号,
    "severity": "critical|major|minor|info",
    "title": "问题标题",
    "description": "为什么这是个性能问题",
    "suggestion": "怎么优化",
    "category": "performance",
    "code_snippet": "相关代码片段"
  }}
]

如果没有性能问题，返回空数组 []。

代码变更：
{code}
"""


def performance_review_node(state: CodeReviewState) -> dict:
    """性能审查 Agent 节点"""
    import json, re

    files = state.get("files_changed", [])
    if not files:
        return {"performance_findings": []}

    review_files = [f for f in files if f.get("change_type") in ("added", "modified")]
    if not review_files:
        return {"performance_findings": []}

    code = format_diff_for_review(review_files)
    if not code.strip():
        return {"performance_findings": []}

    lang = _get_languages(review_files)
    prompt = PERFORMANCE_PROMPT.replace("{language}", lang).replace("{code}", code)

    try:
        llm = get_llm(temperature=0.1)
        resp = llm.invoke(prompt)
        text = resp.content if hasattr(resp, "content") else str(resp)

        json_match = re.search(r'\[.*\]', text, re.DOTALL)
        if json_match:
            findings = json.loads(json_match.group())
            return {"performance_findings": findings}
        return {"performance_findings": []}
    except Exception as e:
        log(f"[性能审查] 失败: {e}")
        return {"performance_findings": []}
