"""
共享的批量审查工具 — 把文件分批送 LLM，避免大 diff 被截断丢中间段
=====================================================================
原实现把所有文件拼成一大段，超过 max_tokens 就截断（保留头尾、中间段直接丢）。
被截掉的部分等于"没被审查"，而且用户端不可见 —— 这是静默漏报。

这里改成按文件分批：每批单独构建 prompt、单独调 LLM，合并所有结果。
每个批次都带独立的 token 预算，单个大文件不会因为"文件多被均分预算"而截断。
"""
from tools.git_tools import format_diff_for_review, estimate_tokens

REVIEW_MAX_TOKENS = 8000       # 每批的 token 预算（原 4000 → 8000，提升单文件覆盖）
REVIEW_BATCH_MAX_FILES = 3     # 每批最多几个文件


def _chunk_files(files: list, max_tokens: int, max_files: int) -> list:
    """把文件分成若干小批：每批文件数 ≤ max_files，且预估 token 总量 ≤ max_tokens"""
    chunks = []
    current = []
    current_tokens = 0
    for f in files:
        code = f.get("diff_content") or f.get("content") or ""
        ft = estimate_tokens(code)
        if current and (len(current) >= max_files or current_tokens + ft > max_tokens):
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(f)
        current_tokens += ft
    if current:
        chunks.append(current)
    return chunks


def run_batched_review(
    prompt_template: str,
    files: list,
    agent_name: str,
    language: str,
    memory_context: str = "",
    temperature: float = 0.1,
    max_tokens: int = REVIEW_MAX_TOKENS,
    max_files_per_batch: int = REVIEW_BATCH_MAX_FILES,
):
    """
    按文件分批调 LLM 审查，合并所有批次的 findings。

    返回:
        (findings, had_error)
        findings: 所有批次合并的审查结果（按批次顺序拼接）
        had_error: 只要有任何批次失败即为 True（上层据此决定是否标 agent_errors）
    """
    from tools.llm import timed_invoke, extract_json_array
    from utils import log

    all_findings = []
    had_error = False

    batches = _chunk_files(files, max_tokens, max_files_per_batch)
    if not batches:
        return [], False

    for i, batch in enumerate(batches):
        code = format_diff_for_review(batch, max_tokens=max_tokens)

        # 历史记忆只附在第一批，避免每批重复注入浪费 token
        if memory_context and i == 0:
            code = memory_context + "\n" + code
        if not code.strip():
            continue

        prompt = prompt_template.replace("{language}", language).replace("{code}", code)
        text, ok = timed_invoke(agent_name, prompt, temperature=temperature)
        if not ok:
            had_error = True
            log(f"[{agent_name}审查] 批次{i + 1}/{len(batches)}跳过（API不可用）: {text}")
            continue

        findings, parse_error = extract_json_array(text)
        if parse_error:
            had_error = True
            log(f"[{agent_name}审查] 批次{i + 1}/{len(batches)}解析失败: {parse_error}，原始响应前200字符: {text[:200]}")
            continue

        all_findings.extend(findings)

    return all_findings, had_error
