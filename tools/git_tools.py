"""
Git 文件操作工具 — 解析 diff、读取文件内容
===========================================
不需要 LLM，纯代码逻辑。

功能：
  1. get_git_diff(branch/commit) → diff 字符串
  2. parse_diff(diff_str) → list[FileChange]
  3. read_file(path) → 文件内容
  4. get_file_language(path) → 语言类型
"""
import os
import re
import subprocess
from pathlib import Path
from typing import Optional


LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".txt": "text",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".dockerfile": "dockerfile",
    ".proto": "protobuf",
}

# 二进制/非审查文件扩展名
SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".mp3", ".mp4", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".exe", ".dll", ".so", ".dylib",
    ".o", ".a", ".lib",
    ".pyc", ".pyo",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".min.js", ".min.css",
    ".map",
}


def get_file_language(filepath: str) -> str:
    """根据文件扩展名判断语言"""
    ext = os.path.splitext(filepath)[1].lower()

    # 特殊文件名
    basename = os.path.basename(filepath).lower()
    if basename == "dockerfile":
        return "dockerfile"
    if basename in ("makefile", "gnumakefile"):
        return "makefile"

    return LANGUAGE_MAP.get(ext, "unknown")


def should_skip_file(filepath: str) -> bool:
    """判断文件是否应该跳过审查"""
    ext = os.path.splitext(filepath)[1].lower()

    # 二进制/生成文件
    if ext in SKIP_EXTENSIONS:
        return True

    # 常见生成目录
    skip_dirs = [
        "node_modules", ".venv", "venv", "__pycache__",
        ".git", ".idea", ".vscode", "build", "dist",
        "target", "bin", "obj", ".next", ".nuxt",
    ]
    parts = filepath.replace("\\", "/").split("/")
    for d in skip_dirs:
        if d in parts:
            return True

    return False


def _run_git(args: list, timeout: int = 30) -> str:
    """
    安全执行 git 命令，处理 Windows GBK 编码问题

    返回:
        命令输出，失败返回空字符串
    """
    try:
        # 用二进制模式捕获输出，手动解码，避免 Windows GBK 崩溃
        result = subprocess.run(
            args,
            capture_output=True,
            text=False,  # 二进制模式
            timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            if stderr:
                print(f"[git] {stderr}")
            return ""

        # 先尝试 UTF-8 解码，失败用 GBK 兜底
        stdout = result.stdout
        if stdout is None:
            return ""
        try:
            return stdout.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return stdout.decode("gbk", errors="replace")
            except Exception:
                return stdout.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        print("[警告] git 命令超时")
        return ""
    except FileNotFoundError:
        # git 命令不存在
        return ""
    except Exception as e:
        print(f"[警告] git 命令失败: {e}")
        return ""


def get_git_diff(ref: str = "HEAD") -> str:
    """
    获取 git diff 内容

    参数:
        ref: git 引用（HEAD, HEAD~1, 分支名, commit hash）

    返回:
        diff 字符串，失败返回空字符串
    """
    # 检查是否在 git 仓库中
    toplevel = _run_git(["git", "rev-parse", "--show-toplevel"], timeout=5)
    if not toplevel:
        return ""

    # 获取 diff
    if ref == "HEAD":
        # 未暂存的变更 + 已暂存未提交的变更
        diff = _run_git(["git", "diff", "HEAD"])
        # 如果 HEAD diff 为空，试试跟上一个 commit 比
        if not diff or not diff.strip():
            diff = _run_git(["git", "diff", "HEAD~1", "HEAD"])
    else:
        diff = _run_git(["git", "diff", f"{ref}..."])

    return diff or ""


def parse_diff(diff_content: str) -> list:
    """
    解析 git diff 内容为 FileChange 列表

    返回:
        List[FileChange]
    """
    if not diff_content or not diff_content.strip():
        return []

    files = []
    current_file = None
    current_diff_lines = []

    # 正则匹配 diff 头: diff --git a/path b/path
    diff_header_pattern = re.compile(r"^diff --git a/(.+) b/(.+)$")
    # 匹配 --- a/path
    # 匹配 +++ b/path

    for line in diff_content.split("\n"):
        header_match = diff_header_pattern.match(line)
        if header_match:
            # 保存上一个文件
            if current_file:
                current_file["diff_content"] = "\n".join(current_diff_lines)
                files.append(current_file)

            filepath = header_match.group(2)
            current_file = {
                "path": filepath,
                "change_type": "modified",  # 默认
                "language": get_file_language(filepath),
                "additions": 0,
                "deletions": 0,
                "diff_content": "",
                "content": "",
            }
            current_diff_lines = [line]
            continue

        if current_file is None:
            continue

        current_diff_lines.append(line)

        # 判断变更类型
        if line.startswith("new file mode"):
            current_file["change_type"] = "added"
        elif line.startswith("deleted file mode"):
            current_file["change_type"] = "deleted"
        elif line.startswith("rename from"):
            current_file["change_type"] = "renamed"

        # 统计增减行（逐行统计 + 和 - 前缀的行，排除 ---/+++ 标记行）
        if line.startswith("+") and not line.startswith("+++"):
            current_file["additions"] += 1
        elif line.startswith("-") and not line.startswith("---"):
            current_file["deletions"] += 1

    # 最后一个文件
    if current_file:
        current_file["diff_content"] = "\n".join(current_diff_lines)
        files.append(current_file)

    # 过滤要跳过的文件
    files = [f for f in files if not should_skip_file(f["path"])]

    return files


def read_file_content(filepath: str) -> Optional[str]:
    """读取文件内容"""
    try:
        path = Path(filepath).resolve()
        if not path.exists():
            return None
        # 尝试 UTF-8
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # 尝试其他编码
            try:
                return path.read_text(encoding="gbk")
            except UnicodeDecodeError:
                return None
    except Exception:
        return None


def scan_directory(directory: str) -> list:
    """
    扫描目录下的所有文件（非递归遍历）

    返回:
        List[FileChange]
    """
    files = []
    path = Path(directory).resolve()
    if not path.exists():
        return files

    for f in sorted(path.rglob("*")):
        if not f.is_file():
            continue
        filepath = str(f)
        if should_skip_file(filepath):
            continue

        content = read_file_content(filepath)
        if content is None:
            continue

        files.append({
            "path": str(f.relative_to(path.parent)),
            "change_type": "added",
            "language": get_file_language(filepath),
            "additions": len(content.splitlines()),
            "deletions": 0,
            "diff_content": "",
            "content": content,
        })

    return files


def estimate_tokens(text: str) -> int:
    """
    粗略估算文本的 Token 数。
    中文约 1.5 字符/token，英文约 4 字符/token，取保守值 2。
    """
    if not text:
        return 0
    return len(text) // 2 + 1


def truncate_content(text: str, max_tokens: int = 4000, file_label: str = "") -> str:
    """
    如果内容超过 max_tokens，截断保留头尾。
    优先保留文件头部（结构/import）和变更部分。

    返回:
        截断后的文本
    """
    estimated = estimate_tokens(text)
    if estimated <= max_tokens:
        return text

    # 保留比例：前 60% 后 40%
    keep_chars = max_tokens * 2  # 估算字符数
    head_chars = int(keep_chars * 0.6)
    tail_chars = keep_chars - head_chars

    truncated = text[:head_chars] + text[-tail_chars:]
    warning = (
        f"\n\n⚠️ [内容截断] {file_label} "
        f"原内容约 {estimated} token，已截断至 {max_tokens} token。"
        f"\n   保留了文件开头和末尾部分。如需完整审查，请缩小文件范围。\n"
    )
    return truncated + warning


def format_diff_for_review(files: list, max_tokens: int = 6000) -> str:
    """
    将 FileChange 列表格式化为 LLM 能理解的文本。

    参数:
        files: FileChange 列表
        max_tokens: 输出内容的最大 token 数（超限自动截断）

    返回:
        格式化后的审查文本
    """
    parts = []
    for f in files:
        lang = f["language"]
        fpath = f["path"]
        change = f["change_type"]

        header = f"## 文件: {fpath} ({lang}) [{change}]"
        parts.append(header)

        if change == "deleted":
            parts.append("（文件已被删除）\n")
            continue

        # 优先用 diff 内容，没有则用完整内容
        if f.get("diff_content"):
            code = f["diff_content"]
            code = truncate_content(code, max_tokens // len(files), fpath)
            parts.append("```diff")
            parts.append(code)
            parts.append("```")
        elif f.get("content"):
            code = f["content"]
            code = truncate_content(code, max_tokens // len(files), fpath)
            parts.append(f"```{lang}")
            parts.append(code)
            parts.append("```")

        parts.append("")

    result = "\n".join(parts)

    # 整体再检查一次
    result = truncate_content(result, max_tokens, "全部文件")
    return result
