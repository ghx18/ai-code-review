# -*- coding: utf-8 -*-
"""
AI Code Review 评估 runner
==========================
对 eval/cases/ 下每个文件跑完整审查图（diff 分析 -> 4 Agent 并行 -> 聚合），
用 ground_truth 锚点匹配 findings，计算：

  - 检出率 (recall)      : 埋的缺陷被抓到的比例（整体 + 按类别）
  - 误报文件率            : 干净文件被报了问题的比例
  - 额外发现              : 缺陷文件上未命中锚点的 finding（可能是真问题或噪音）

直接调 LangGraph 图（绕过 run_review 的记忆库），保证测量干净、可重复。

用法:
    python eval_runner.py                 # 全量
    python eval_runner.py --limit 3       # 只跑前 3 个缺陷文件（pilot）
    python eval_runner.py --verbose       # 打印每个 finding
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(ROOT)
sys.path.insert(0, PROJ)
os.chdir(PROJ)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import ground_truth as gt
from graph import build_graph
from state import empty_state

CASES_DIR = os.path.join(ROOT, "cases")


def review_file(graph, path):
    """对单个文件跑完整审查图，返回 (findings, 耗时秒, agent_errors)"""
    state = empty_state()
    state["input_type"] = "file"
    state["input_path"] = path
    t0 = time.time()
    result = graph.invoke(state)
    dur = time.time() - t0
    findings = result.get("aggregated_findings", []) or []
    errors = result.get("agent_errors", []) or []
    return findings, dur, errors


def finding_text(f):
    return " ".join(str(f.get(k, "")) for k in ("title", "description", "code_snippet"))


def matches_any(f, anchors):
    txt = finding_text(f).lower()
    return any(str(a).lower() in txt for a in anchors)


def fmt_finding(f):
    return {
        "severity": f.get("severity", ""),
        "category": f.get("category", ""),
        "title": f.get("title", ""),
        "line": f.get("line", 0),
        "snippet": (f.get("code_snippet", "") or "")[:200],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个缺陷文件")
    ap.add_argument("--category", default="", help="只跑指定类别（security/performance/logic/style），仍会跑干净对照")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    buggy = gt.BUGGY_CASES
    clean = gt.CLEAN_CASES
    if args.limit:
        buggy = buggy[:args.limit]
    if args.category:
        buggy = [c for c in buggy if c["category"] == args.category]

    graph = build_graph()
    detail = {"buggy": [], "clean": [], "metrics": {}}

    # ── 跑缺陷文件 ──
    detected, total, extra_findings = 0, 0, []
    cat_stats = {}
    for case in buggy:
        path = os.path.join(CASES_DIR, case["file"])
        findings, dur, errors = review_file(graph, path)

        hit = any(matches_any(f, case["anchors"]) for f in findings)
        detected += 1 if hit else 0
        total += 1
        cat = case["category"]
        cs = cat_stats.setdefault(cat, {"detected": 0, "total": 0})
        cs["total"] += 1
        if hit:
            cs["detected"] += 1

        extras = [f for f in findings if not matches_any(f, case["anchors"])]
        extra_findings.extend(
            {"file": case["file"], "finding": fmt_finding(f)} for f in extras
        )

        detail["buggy"].append({
            "file": case["file"], "category": cat, "desc": case["desc"],
            "detected": hit, "elapsed_s": round(dur, 1),
            "agent_errors": errors,
            "findings": [fmt_finding(f) for f in findings],
        })
        print(f"[{case['file']}] {'检出' if hit else '漏报':<4} {cat:<11} {case['desc']}  findings={len(findings)} {dur:.1f}s")

    # ── 跑干净对照文件 ──
    # 误报分两档：
    #   strict     : 干净文件上出现任何 finding
    #   substantive: 出现"实质性"finding（severity=critical/major，或非 style 类别）。
    #                style 类 minor（缺注释/类型注解）是风格审查的设计行为，不算实质性误报。
    fp_strict, fp_substantive, clean_extra, clean_substantive = 0, 0, [], []

    def is_substantive(f):
        return (f.get("severity") in ("critical", "major")) or (f.get("category", "") != "style")

    for case in clean:
        path = os.path.join(CASES_DIR, case["file"])
        findings, dur, errors = review_file(graph, path)
        has_fp = len(findings) > 0
        has_real = any(is_substantive(f) for f in findings)
        fp_strict += 1 if has_fp else 0
        fp_substantive += 1 if has_real else 0
        clean_extra.extend(
            {"file": case["file"], "finding": fmt_finding(f)} for f in findings
        )
        clean_substantive.extend(
            {"file": case["file"], "finding": fmt_finding(f)}
            for f in findings if is_substantive(f)
        )
        detail["clean"].append({
            "file": case["file"], "desc": case["desc"],
            "false_positive": has_fp, "substantive_fp": has_real,
            "elapsed_s": round(dur, 1),
            "agent_errors": errors,
            "findings": [fmt_finding(f) for f in findings],
        })
        print(f"[{case['file']}] {'误报' if has_fp else '无报':<4} {case['desc']}  findings={len(findings)} {dur:.1f}s")

    # ── 指标 ──
    recall = detected / total if total else 0
    fp_rate = fp_strict / len(clean) if clean else 0
    fp_real_rate = fp_substantive / len(clean) if clean else 0
    metrics = {
        "seeded_bugs": total,
        "detected": detected,
        "recall": round(recall, 3),
        "per_category_recall": {
            k: {"detected": v["detected"], "total": v["total"],
                "recall": round(v["detected"] / v["total"], 3) if v["total"] else 0}
            for k, v in cat_stats.items()
        },
        "clean_files": len(clean),
        "clean_fp_strict_files": fp_strict,
        "clean_fp_rate": round(fp_rate, 3),
        "clean_fp_substantive_files": fp_substantive,
        "clean_fp_substantive_rate": round(fp_real_rate, 3),
        "extra_findings_on_buggy": len(extra_findings),
        "findings_on_clean": len(clean_extra),
        "substantive_findings_on_clean": len(clean_substantive),
    }
    detail["metrics"] = metrics

    with open(os.path.join(ROOT, "results.json"), "w", encoding="utf-8") as f:
        json.dump(detail, f, ensure_ascii=False, indent=2)

    print("\n================ 结果 ================")
    print(f"检出率 recall            : {detected}/{total} = {recall*100:.0f}%")
    for k, v in metrics["per_category_recall"].items():
        print(f"  - {k:<11} : {v['detected']}/{v['total']} = {v['recall']*100:.0f}%")
    print(f"误报率（含风格提示）      : {fp_strict}/{len(clean)} = {fp_rate*100:.0f}%")
    print(f"实质性误报率（排除style） : {fp_substantive}/{len(clean)} = {fp_real_rate*100:.0f}%")
    print(f"缺陷文件上额外发现        : {len(extra_findings)} 条")
    print(f"干净文件上风格提示条数    : {len(clean_extra) - len(clean_substantive)} 条")
    print("详细结果 -> eval/results.json")


if __name__ == "__main__":
    main()
