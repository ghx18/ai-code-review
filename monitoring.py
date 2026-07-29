"""
Prometheus 监控指标 — 请求计数、耗时分布、Agent 级别指标
========================================================
"""
import time
from prometheus_client import Counter, Histogram, Gauge, generate_latest

# ── API 级别指标 ──
API_REQUESTS = Counter(
    "api_requests_total",
    "API 请求总数",
    labelnames=["method", "endpoint", "status"],
)

API_LATENCY = Histogram(
    "api_latency_seconds",
    "API 响应耗时（秒）",
    labelnames=["endpoint"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, float("inf")),
)

# ── 审查指标 ──
REVIEW_TOTAL = Counter(
    "review_total",
    "审查总次数",
    labelnames=["input_type", "status"],
)

REVIEW_LATENCY = Histogram(
    "review_latency_seconds",
    "审查耗时（秒）",
    labelnames=["input_type"],
    buckets=(1.0, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0, float("inf")),
)

REVIEW_ISSUES = Gauge(
    "review_issues_total",
    "审查发现的问题总数",
    labelnames=["severity"],
)

# ── Agent 级别指标 ──
AGENT_CALLS = Counter(
    "agent_calls_total",
    "Agent 调用次数",
    labelnames=["agent", "status"],
)

AGENT_LATENCY = Histogram(
    "agent_latency_seconds",
    "Agent 调用耗时（秒）",
    labelnames=["agent"],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, float("inf")),
)

# ── LLM API 指标 ──
LLM_CALLS = Counter(
    "llm_calls_total",
    "LLM API 调用次数",
    labelnames=["status"],
)

LLM_CIRCUIT_BREAKER = Gauge(
    "llm_circuit_breaker",
    "熔断器状态（0=关闭 1=熔断中）",
)


def metrics_endpoint():
    """返回 Prometheus 格式指标"""
    return generate_latest().decode("utf-8")
