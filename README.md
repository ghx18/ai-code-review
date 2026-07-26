# 🤖 AI Code Review — 基于 LangGraph 的多 Agent 代码审查系统

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2%2B-green)](https://langchain-ai.github.io/langgraph/)

## 简介

一个**生产级的多 Agent 代码审查系统**，基于 LangGraph 构建，由 5 个专业 Agent 协作完成代码审查：

| Agent | 职责 | 审查维度 |
|-------|------|---------|
| 🔍 **变更分析 Agent** | 解析 git diff / 文件 | 纯代码，不调 LLM |
| 🛡️ **安全审查 Agent** | 查找安全漏洞 | SQL注入、XSS、敏感信息泄露、命令注入 |
| ⚡ **性能审查 Agent** | 发现性能瓶颈 | N+1查询、不必要的循环、缓存缺失 |
| 🎨 **风格审查 Agent** | 检查代码规范 | 命名规范、类型注解、文档字符串 |
| 🧠 **逻辑审查 Agent** | 发现逻辑错误 | 空指针、边界条件、并发问题 |

## 架构

```
用户输入 → 变更分析 → 并行审查 ──→ 聚合 → 修复建议 → 报告生成
              │         │  │  │  │        │
              │     安全 性能 风格 逻辑     │
              │          （4个并行节点）     │
              └──────────────────────────────┘
```

**LangGraph 特性：**
- ✅ **StateGraph** — 8 个节点的有向图
- ✅ **并行节点** — 4 个审查 Agent 同时运行
- ✅ **条件路由** — 根据审查结果决定是否生成修复
- ✅ **共享状态** — 所有 Agent 读写同一个 State

## 快速开始

### 1. 安装依赖

```bash
cd projects/ai-code-review
pip install -r requirements.txt
```

### 2. 配置 API Key

项目根目录的 `.env` 文件中已有：


### 3. 运行审查

```bash
# 审查 git 最新的变更
python main.py --git HEAD

# 审查某个分支
python main.py --git feature/my-branch

# 审查单个文件
python main.py --file path/to/file.py

# 审查整个目录
python main.py --dir ./src

# 输出到文件
python main.py --git HEAD --output report.md
```

### 4. 示例

```bash
# 审查你今天写的代码
python main.py --git HEAD

# 审查你之前写的 Agent 系统
python main.py --file ../day7/02_multi_agent.py

# 审查整个项目
python main.py --dir ../
```

## 输出格式

### Markdown 报告（默认）

包含：审查总览 → 问题详情（按严重度分级）→ 自动修复建议 → 总结建议

### JSON 格式

```bash
python main.py --git HEAD --format json
```

## 项目结构

```
ai-code-review/
├── main.py              # CLI 入口
├── state.py             # 共享状态定义
├── graph.py             # LangGraph 图编排
├── agents/
│   ├── diff_analyzer.py      # 变更分析（纯代码）
│   ├── security_review.py    # 安全审查
│   ├── performance_review.py # 性能审查
│   ├── style_review.py       # 风格审查
│   ├── logic_review.py       # 逻辑审查
│   ├── aggregator.py         # 聚合去重排序
│   ├── fix_generator.py      # 修复建议生成
│   └── report_generator.py   # 报告生成
├── tools/
│   ├── git_tools.py     # Git diff 解析
│   └── llm.py           # LLM 调用封装
├── requirements.txt
└── README.md
```

## 技术栈

- **LangGraph** — 状态图编排，并行节点，条件路由
- **LangChain** — LLM 调用封装
- **DeepSeek API** — 底层大模型
- **Python** — 纯代码 + AST 解析

## 简历描述

> **AI 代码审查系统** — 基于 LangGraph 的多 Agent 协作系统
>
> 设计并实现了一个由 5 个专业审查 Agent（安全/性能/风格/逻辑/聚合）组成的代码审查系统，使用 LangGraph 的 StateGraph 进行状态编排，支持并行审查、条件路由和自动修复建议。支持 Git 分支变更、单文件和目录三种审查模式，输出 Markdown/JSON 格式审查报告，包含严重度分级、定位行号和自动 Patch 建议。
>
> 技术栈：LangGraph / LangChain / DeepSeek API / Python
