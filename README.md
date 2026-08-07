# 🤖 AI Code Review — 基于 LangGraph 的多 Agent 代码审查系统

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2%2B-green)](https://langchain-ai.github.io/langgraph/)

## 简介

一个**生产级的多 Agent 代码审查系统**，基于 LangGraph 构建，由 5 个审查 Agent 协作完成代码审查，并支持异步任务、WebSocket 实时进度、Agent 记忆与多层级安全加固。

| Agent | 职责 | 审查维度 |
|-------|------|---------|
| 🔍 **变更分析 Agent** | 解析 git diff / 文件 / 目录 | 纯代码，不调 LLM |
| 🛡️ **安全审查 Agent** | 查找安全漏洞 | SQL注入、XSS、敏感信息泄露、命令注入、路径遍历 |
| ⚡ **性能审查 Agent** | 发现性能瓶颈 | N+1查询、不必要的循环、缓存缺失、资源未释放 |
| 🎨 **风格审查 Agent** | 检查代码规范 | 命名规范、类型注解、文档字符串、重复代码 |
| 🧠 **逻辑审查 Agent** | 发现逻辑错误 | 空指针、边界条件、并发问题、竞态条件 |

## 架构

### LangGraph 图编排（同步链路）

```
diff_analyzer
   │  条件路由：出错 → 直接出报告；正常 → fan_out
   ▼
fan_out ──4 条普通边并行──► security / performance / style / logic
   │                                        │
   │                                        ▼
   │                            aggregator（去重 / 排序 / 统计）
   │                                        │
   │                         ┌──────────────┴──────────────┐
   │                     有发现 → fix_generator             │
   │                         └──────────────┬──────────────┘
   ▼                                        ▼
report_generator ◄──────────────────────────┘
   ▼
  END
```

- **条件边 vs 普通边**：`diff_analyzer` 用条件边（分流），`fan_out` 用普通边（扇出 1→4 并行），一个节点只选一种出口
- **聚合去重**：按 `(file, line, title)` 字面匹配去重，按严重度 → 文件 → 行号排序

### 异步执行链路

```
REST / WebSocket ──► Celery review_task（Redis 队列）──► 完整 LangGraph
                          │
                          ├─ 节点级真实进度（diff 15% → 安全 30% → … → 报告 95%）
                          ├─ 指数退避重试（仅瞬时错误，永久错误不重试）
                          └─ 结果落库（reviews / tasks / review_memory）
```

## 核心特性

- **批量审查，防截断漏报** — 4 个审查 Agent 按文件分批送 LLM（每批独立 token 预算），超长 diff 不再被截断丢中间段（`agents/agent_utils.py`）
- **异步任务 + 真实进度** — Celery 后台执行；worker 探活（`worker_available`）+ 120s 卡死兜底；任务落库区分"不存在 / 排队中 / 已过期"，7 天过期返回 EXPIRED
- **WebSocket 实时审查** — `/ws/review` 复用 Celery，推送真实阶段进度；断线只停轮询、worker 照跑，不阻塞事件循环
- **Agent 记忆** — 按文件注入历史审查结果（`review_memory` 表），跨会话上下文
- **三层安全加固** — 敏感文件黑名单（.env/密钥）+ 内容脱敏（进 LLM 前打码 `mask_secrets`）+ 路径白名单（MCP/REST 越界拒绝）
- **LLM 并发与容错** — 信号量限流（每进程 `LLM_MAX_CONCURRENCY`，默认 16）+ 熔断器 + Prometheus 指标
- **限流在网关层** — nginx `limit_req`（api 10r/m / general 60r/m）；API 只监听 `127.0.0.1:8000`，公网不可直连

## 线上部署现状

已部署上线（腾讯云轻量服务器）。入口统一走 nginx（80 端口），API 容器只监听 `127.0.0.1:8000`，公网不可直连。

```
用户 ──► nginx :80（limit_req 网关限流：/api 10r/m、general 60r/m）
              ├──► api（127.0.0.1:8000，FastAPI + WebSocket）
              ├──► celery worker（--concurrency=4，异步审查）
              └──► redis / postgres
```

- **访问地址**: `http://124.222.1.136`（`/health` 已验证返回 ok）
- **安全现状**: 8000 后门已关闭（外网直连被拒，全部流量只能走 nginx 正门）；限流职责唯一归 nginx（app 旧中间件已删除）
- **部署/更新**: 一键 `deploy.bat` —— 提交推送 Gitee → ssh 到服务器 `git pull` → `docker compose up -d api worker`
- **更新线上流程** = 先本地提交代码，再跑 `deploy.bat`

> ⚠️ 域名 ghx08.tech 备案中；备案生效前大陆访问走 IP，之后再启用 HTTPS。

## 快速开始

### 1. 安装依赖

```bash
cd projects/ai-code-review
pip install -r requirements.txt
```

### 2. 配置 API Key

项目根目录的 `.env` 中设置 `DEEPSEEK_API_KEY`（可选 `LLM_MAX_CONCURRENCY` 控制并发）。

### 3. 命令行审查

```bash
# 审查 git 最新的变更
python main.py --git HEAD

# 审查某个分支
python main.py --git feature/my-branch

# 审查单个文件
python main.py --file path/to/file.py

# 审查整个目录（自动分批）
python main.py --dir ./src

# 输出到文件
python main.py --git HEAD --output report.md

# 输出格式：markdown（默认）/ json / html
python main.py --file path/to/file.py --format html -o report.html   # HTML 报告可直接浏览器打开
python main.py --file path/to/file.py --format json                  # JSON 报告（findings / fix_suggestions 结构化）
```

### 4. 启动服务（API + Celery + Redis）

```bash
# 启动 Redis
redis-server

# 启动 Celery worker（并发数 = 同时审查数）
celery -A celery_app worker --pool=solo --concurrency=4

# 启动 API
uvicorn api:app --host 127.0.0.1 --port 8000
```

### 5. MCP Server

```bash
python mcp_server.py   # 暴露 review_git_diff / review_file / review_directory 等工具
```

## API 端点

| 端点 | 说明 |
|------|------|
| `POST /api/review` | 同步审查（git_diff / file / directory） |
| `POST /api/review/code` | 粘贴代码审查 |
| `POST /api/review/async` | 异步提交审查（返回 task_id） |
| `GET /api/tasks/{task_id}` | 查询任务状态（PENDING / SUCCESS / FAILURE / EXPIRED） |
| `GET /api/reviews` | 历史审查列表 |
| `GET /api/reviews/{id}` | 单次审查详情 |
| `DELETE /api/reviews/{id}` | 删除审查记录 |
| `WS /ws/review` | WebSocket 实时审查（推送真实进度 + 结果） |
| `GET /health` / `GET /metrics` | 健康检查 / Prometheus 指标 |

> `POST /api/review` 和 `POST /api/review/code` 请求体支持 `format` 字段（`markdown` / `html`），`report` 字段按所选格式返回，`report_format` 标记实际格式。

## 项目结构

```
ai-code-review/
├── main.py              # CLI 入口
├── api.py               # FastAPI + WebSocket + REST 端点
├── graph.py             # LangGraph 图编排（9 节点，含进度回调）
├── state.py             # 共享状态定义
├── database.py          # SQLAlchemy 持久化（SQLite 开发 / PostgreSQL 生产）
├── celery_app.py        # Celery 异步任务（重试/退避/探活/进度）
├── mcp_server.py        # MCP Server（FastMCP，路径白名单）
├── monitoring.py        # Prometheus 指标
├── agents/
│   ├── agent_utils.py       # 批量审查工具（按文件分批防截断）
│   ├── diff_analyzer.py     # 变更分析（纯代码）
│   ├── security_review.py   # 安全审查
│   ├── performance_review.py# 性能审查
│   ├── style_review.py      # 风格审查
│   ├── logic_review.py      # 逻辑审查
│   ├── aggregator.py        # 聚合去重排序
│   ├── fix_generator.py     # 修复建议生成
│   └── report_generator.py  # 报告生成
├── tools/
│   ├── git_tools.py     # Git diff 解析 / 敏感文件过滤 / 内容脱敏
│   └── llm.py           # LLM 调用封装（信号量限流 + 熔断器）
├── static/              # Web 前端
├── docker-compose.yml   # api / worker / redis / postgres
└── README.md
```

## 技术栈

| 组件 | 技术 |
|------|------|
| 编排 | LangGraph（StateGraph / 条件边 / 并行） |
| Web 服务 | FastAPI + WebSocket |
| 异步任务 | Celery + Redis |
| 持久化 | SQLAlchemy + SQLite / PostgreSQL |
| LLM | DeepSeek API |
| 安全 | 敏感文件黑名单 / 内容脱敏 / 路径白名单 / nginx 网关限流 |
| 部署 | Docker Compose + nginx（**已上线**：腾讯云，API 仅监听 127.0.0.1:8000） |

## 简历描述

> **AI 代码审查系统** — 基于 LangGraph 的多 Agent 协作 + 异步生产化
>
> 设计并实现了一个由 5 个专业审查 Agent（安全/性能/风格/逻辑）组成的代码审查系统，使用 LangGraph 的 StateGraph 编排并行审查、条件路由与自动修复建议。支持 Git 分支变更、单文件、目录三种模式，输出带严重度分级与行号定位的 Markdown/JSON 报告。
>
> 生产化能力：Celery 异步任务 + WebSocket 实时进度推送 + worker 探活与卡死兜底；Agent 跨会话记忆；敏感信息脱敏与路径白名单三层安全加固；批量审查防止超长 diff 截断漏报；信号量限流与熔断器；Docker Compose + nginx 网关限流部署（API 端口只对内）。
>
> 技术栈：LangGraph / FastAPI / Celery / Redis / WebSocket / SQLAlchemy / DeepSeek API / nginx
