# -*- coding: utf-8 -*-
"""验证 extract_json_array 修复 + 失败要响亮 集成"""
from tools.llm import extract_json_array

OK = 0
def check(name, cond):
    global OK
    status = "✅" if cond else "❌"
    print(f"  {status} {name}")
    if cond:
        OK += 1

print("=" * 60)
print("第1部分: extract_json_array 各场景")
print("=" * 60)

clean = '''好的,我审查了代码:
[
  {"file": "a.py", "line": 1, "severity": "critical", "title": "SQL注入", "description": "d", "suggestion": "s", "category": "security", "code_snippet": "c"}
]
以上就是结果。'''
data, err = extract_json_array(clean)
check("干净数组 → 成功", data is not None and isinstance(data, list) and data[0]["severity"] == "critical")

tail = clean + "\n [仅供参考]"
data, err = extract_json_array(tail)
check("数组后带 [仅供参考] 尾巴 → 成功(旧正则会失败)", data is not None and len(data) == 1)

fence = "```json\n" + clean + "\n```"
data, err = extract_json_array(fence)
check("markdown 代码围栏 → 成功", data is not None and len(data) == 1)

bad = clean.replace('"code_snippet": "c"', '"code_snippet": c')
data, err = extract_json_array(bad)
check("坏 JSON(引号坏了) → 失败且给错误描述", data is None and err is not None)

prose = "我没有发现任何安全问题,代码写得不错。"
data, err = extract_json_array(prose)
check("纯人话无数组 → 失败且给错误描述", data is None and err is not None)

data, err = extract_json_array("")
check("空响应 → 失败", data is None and err is not None)

obj = '{"findings": [{"file": "a.py", "line": 1, "severity": "minor", "title": "t", "description": "d", "suggestion": "s", "category": "style", "code_snippet": "c"}]}'
data, err = extract_json_array(obj)
check("返回对象而非数组 → 失败(不静默放行)", data is None and err is not None)

print()
print("=" * 60)
print("第2部分: security_review_node 集成(解析失败→agent_errors)")
print("=" * 60)

import agents.security_review as sr

# mock 掉 LLM: 返回"人话",没有 JSON 数组
sr.timed_invoke = lambda *a, **k: ("好的,我审查完了,没发现什么问题。", True)
state = {
    "files_changed": [
        {"path": "a.py", "change_type": "added", "language": "python", "diff_content": "x = 1\n"},
    ],
}
result = sr.security_review_node(state)
check("坏输出 → security_findings 为空", result["security_findings"] == [])
check("坏输出 → agent_errors 记入 ['security'](失败要响亮)", result.get("agent_errors") == ["security"])

# mock: 正常 JSON 输出
sr.timed_invoke = lambda *a, **k: (
    '[{"file": "a.py", "line": 1, "severity": "critical", "title": "SQL注入", '
    '"description": "拼接", "suggestion": "参数化", "category": "security", "code_snippet": "c"}]',
    True,
)
result = sr.security_review_node(state)
check("正常输出 → 解析出 1 条 finding", len(result["security_findings"]) == 1)

print()
print("=" * 60)
print("第3部分: 聚合器——agent_errors 出现在摘要里")
print("=" * 60)

from agents.aggregator import aggregator_node
agg_state = {
    "security_findings": [],
    "performance_findings": [{"file": "b.py", "line": 2, "severity": "major", "title": "循环慢", "category": "performance"}],
    "style_findings": [],
    "logic_findings": [],
    "agent_errors": ["security"],
}
agg = aggregator_node(agg_state)
summary = agg["summary"]
check("安全 Agent 挂了 → 摘要含 '结果可能不完整'", "结果可能不完整" in summary)
print("     摘要原文:", summary)

print()
print(f"通过 {OK} 项测试")
