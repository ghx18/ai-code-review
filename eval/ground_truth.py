# -*- coding: utf-8 -*-
"""
AI Code Review 评估集 — 标准答案与匹配锚点
==========================================
每个缺陷用例对应一个预期缺陷：
  - file     : 文件名（位于 eval/cases/）
  - category : 缺陷类别（security / performance / logic / style）
  - anchors  : 匹配锚点。一条 finding 的 title/description/code_snippet 里
               命中任一锚点（不区分大小写）即判定为该缺陷被检出。
  - desc     : 缺陷说明（用于报告可读性）

干净对照用例没有锚点，用来测误报率：出现任一 finding 即视为误报。
"""

# 缺陷用例（每个文件埋 1 个明确缺陷）
BUGGY_CASES = [
    {"file": "b01_sql_injection.py",  "category": "security",    "anchors": ["cur.execute", "SELECT * FROM users"], "desc": "SQL注入：字符串拼接SQL"},
    {"file": "b02_command_injection.py", "category": "security", "anchors": ["subprocess.call", "tar -czf"], "desc": "命令注入：shell拼接用户输入"},
    {"file": "b03_hardcoded_secret.py", "category": "security",  "anchors": ["API_KEY", "sk-abcdefghijklmnopqrstuvwxyz123456"], "desc": "硬编码密钥"},
    {"file": "b04_path_traversal.py",  "category": "security",    "anchors": ["os.path.join", "open(path"], "desc": "路径遍历：未校验用户输入路径"},
    {"file": "b05_eval_untrusted.py",  "category": "security",    "anchors": ["eval(expr)", "eval("], "desc": "对不可信输入执行eval"},
    {"file": "b06_concat_loop.py",     "category": "performance", "anchors": ["out += r", "build_csv"], "desc": "循环内字符串拼接"},
    {"file": "b07_nested_loop.py",     "category": "performance", "anchors": ["x not in seen", "unique_items"], "desc": "O(n²)去重"},
    {"file": "b08_nplus1.py",          "category": "performance", "anchors": ["db.query", "load_orders"], "desc": "N+1数据库查询"},
    {"file": "b09_off_by_one.py",      "category": "logic",       "anchors": ["items[len(items)]", "last_item"], "desc": "越界访问"},
    {"file": "b10_wrong_comparison.py","category": "logic",       "anchors": ["age > 18", "is_adult"], "desc": "边界条件错误"},
    {"file": "b11_div_zero.py",        "category": "logic",       "anchors": ["/ len(nums)", "average"], "desc": "除以零"},
    {"file": "b12_none_deref.py",      "category": "logic",       "anchors": [".get(\"profile\")", "profile[\"age\"]"], "desc": "空值解引用：.get返回None后直接取字段"},
    {"file": "b13_wrong_operator.py",  "category": "logic",       "anchors": ["n % 2 == 0", "is_odd"], "desc": "逻辑判断写反"},
    {"file": "b14_style.py",           "category": "style",       "anchors": ["import sys", "calculateSum"], "desc": "未使用导入+非PEP8命名"},
]

# 干净对照用例（出现任一 finding 即误报）
CLEAN_CASES = [
    {"file": "c01_clean_api.py",   "desc": "干净对照：API处理"},
    {"file": "c02_clean_utils.py", "desc": "干净对照：工具函数"},
    {"file": "c03_clean_worker.py", "desc": "干净对照：处理逻辑"},
]
