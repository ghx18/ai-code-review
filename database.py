"""
Database — 审查记录持久化层
===========================
支持 SQLite（开发）和 PostgreSQL（生产）。

用法:
    from database import init_db, get_session, ReviewRecord
    session = next(get_session())
    reviews = session.query(ReviewRecord).all()
"""
import os
import json
from datetime import datetime
from typing import Generator

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, JSON, Float, ForeignKey, create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship

# ── 数据库连接 ──
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./data/reviews.db",
)

# SQLite 需要 check_same_thread=False（MCP 多线程调用）
_connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}

engine = create_engine(DATABASE_URL, echo=False, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


# ── ORM 模型 ──

class ReviewRecord(Base):
    """单次审查记录"""
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    input_type = Column(String(50), nullable=False)       # git_diff / file / directory
    input_path = Column(String(500), nullable=False)      # HEAD / 文件路径 / 目录路径
    summary = Column(Text, default="")                    # 一句话总结
    report = Column(Text, default="")                     # Markdown 报告全文
    stats = Column(JSON, default=dict)                    # 各维度统计数据
    status = Column(String(20), default="completed")      # completed / failed
    error = Column(Text, default="")                      # 错误信息
    total_files = Column(Integer, default=0)              # 审查文件数
    elapsed_seconds = Column(Float, default=0.0)          # 耗时
    created_at = Column(DateTime, default=datetime.utcnow)

    findings = relationship("FindingRecord", back_populates="review",
                            cascade="all, delete-orphan")
    fix_suggestions = relationship("FixSuggestionRecord", back_populates="review",
                                   cascade="all, delete-orphan")


class FindingRecord(Base):
    """审查发现的具体问题"""
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    review_id = Column(Integer, ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    file = Column(String(500), nullable=False)
    line = Column(Integer, default=0)
    severity = Column(String(20), nullable=False)          # critical / major / minor / info
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    suggestion = Column(Text, default="")
    category = Column(String(50), nullable=False)          # security / performance / style / logic
    code_snippet = Column(Text, default="")

    review = relationship("ReviewRecord", back_populates="findings")


class FixSuggestionRecord(Base):
    """自动修复建议"""
    __tablename__ = "fix_suggestions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    review_id = Column(Integer, ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    file = Column(String(500), nullable=False)
    line = Column(Integer, default=0)
    original = Column(Text, default="")
    suggested = Column(Text, default="")
    explanation = Column(Text, default="")

    review = relationship("ReviewRecord", back_populates="fix_suggestions")


class TaskRecord(Base):
    """异步任务注册表：记录 API 提交过的 Celery 任务

    作用：Celery 对不存在的 task_id 也返回 PENDING（"排队中"），
    不落库就无法区分"任务不存在"和"任务真在排队"。
    """
    __tablename__ = "tasks"

    task_id = Column(String(64), primary_key=True)
    input_type = Column(String(50), nullable=False)
    input_path = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── 初始化与 Session ──

def init_db():
    """初始化数据库，创建所有表"""
    # 确保 data 目录存在
    if "sqlite" in DATABASE_URL:
        # sqlite:///./data/reviews.db → 提取目录部分
        db_path = DATABASE_URL.replace("sqlite:///", "")
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    Base.metadata.create_all(bind=engine)


def get_session() -> Generator[Session, None, None]:
    """获取数据库会话（自动提交/回滚）"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── CRUD 辅助函数 ──

def save_review(
    input_type: str,
    input_path: str,
    summary: str,
    report: str,
    stats: dict,
    status: str,
    error: str,
    total_files: int,
    elapsed_seconds: float,
    findings: list,
    fix_suggestions: list,
) -> int:
    """
    保存审查结果到数据库，返回 record id。
    findings / fix_suggestions 是字典列表，字段与 ORM 模型对应。
    """
    session = next(get_session())
    try:
        record = ReviewRecord(
            input_type=input_type,
            input_path=input_path,
            summary=summary,
            report=report,
            stats=stats or {},
            status=status,
            error=error,
            total_files=total_files,
            elapsed_seconds=round(elapsed_seconds, 2),
        )
        session.add(record)
        session.flush()  # 获取 record.id

        for f in findings:
            session.add(FindingRecord(
                review_id=record.id,
                file=f.get("file", ""),
                line=f.get("line", 0),
                severity=f.get("severity", "info"),
                title=f.get("title", ""),
                description=f.get("description", ""),
                suggestion=f.get("suggestion", ""),
                category=f.get("category", ""),
                code_snippet=f.get("code_snippet", ""),
            ))

        for f in fix_suggestions:
            session.add(FixSuggestionRecord(
                review_id=record.id,
                file=f.get("file", ""),
                line=f.get("line", 0),
                original=f.get("original", ""),
                suggested=f.get("suggested", ""),
                explanation=f.get("explanation", ""),
            ))

        session.commit()
        return record.id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_review(review_id: int) -> dict | None:
    """查询单条审查记录（含 findings）"""
    session = next(get_session())
    try:
        record = session.query(ReviewRecord).filter(ReviewRecord.id == review_id).first()
        if not record:
            return None
        return _record_to_dict(record)
    finally:
        session.close()


def list_reviews(limit: int = 20, offset: int = 0) -> list[dict]:
    """列出最近的审查记录"""
    session = next(get_session())
    try:
        records = (
            session.query(ReviewRecord)
            .order_by(ReviewRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [_record_to_dict(r) for r in records]
    finally:
        session.close()


def delete_review(review_id: int) -> bool:
    """删除审查记录及其关联的 findings / fix_suggestions"""
    session = next(get_session())
    try:
        record = session.query(ReviewRecord).filter(ReviewRecord.id == review_id).first()
        if not record:
            return False
        session.delete(record)  # cascade 会自动删除关联记录
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def save_task(task_id: str, input_type: str, input_path: str):
    """记录一个已提交的异步审查任务（task 注册表）

    让 GET /api/tasks/{id} 能区分"任务不存在"和"任务在排队"。
    """
    session = next(get_session())
    try:
        record = TaskRecord(task_id=task_id, input_type=input_type, input_path=input_path)
        session.add(record)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_task(task_id: str) -> dict | None:
    """查询已提交的任务记录，不存在返回 None"""
    session = next(get_session())
    try:
        record = session.query(TaskRecord).filter(TaskRecord.task_id == task_id).first()
        if not record:
            return None
        return {
            "task_id": record.task_id,
            "input_type": record.input_type,
            "input_path": record.input_path,
            "created_at": record.created_at.timestamp() if record.created_at else 0.0,
        }
    finally:
        session.close()


def _record_to_dict(record: ReviewRecord) -> dict:
    """ORM 模型转字典（含关联数据）"""
    return {
        "id": record.id,
        "input_type": record.input_type,
        "input_path": record.input_path,
        "summary": record.summary,
        "report": record.report,
        "stats": record.stats,
        "status": record.status,
        "error": record.error,
        "total_files": record.total_files,
        "elapsed_seconds": record.elapsed_seconds,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "findings": [
            {
                "id": f.id,
                "file": f.file,
                "line": f.line,
                "severity": f.severity,
                "title": f.title,
                "description": f.description,
                "suggestion": f.suggestion,
                "category": f.category,
                "code_snippet": f.code_snippet,
            }
            for f in record.findings
        ],
        "fix_suggestions": [
            {
                "id": f.id,
                "file": f.file,
                "line": f.line,
                "original": f.original,
                "suggested": f.suggested,
                "explanation": f.explanation,
            }
            for f in record.fix_suggestions
        ],
    }


# ═══════════════════════════════════════════════════════════
#  Agent 记忆 — 跨会话上下文
# ═══════════════════════════════════════════════════════════

class ReviewMemoryRecord(Base):
    """Agent 记忆：记住文件的历史审查结果"""
    __tablename__ = "review_memory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_path = Column(String(500), nullable=False, index=True)
    category = Column(String(50), nullable=False, index=True)  # security/performance/style/logic
    severity = Column(String(20), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    suggestion = Column(Text, default="")
    review_id = Column(Integer, ForeignKey("reviews.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


def save_review_memory(findings: list, review_id: int):
    """将审查结果存入记忆"""
    session = next(get_session())
    try:
        for f in findings:
            record = ReviewMemoryRecord(
                file_path=f.get("file", ""),
                category=f.get("category", ""),
                severity=f.get("severity", ""),
                title=f.get("title", ""),
                description=f.get("description", ""),
                suggestion=f.get("suggestion", ""),
                review_id=review_id,
            )
            session.add(record)
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


def query_review_memory(file_path: str = "", top_k: int = 10) -> list:
    """查询文件的历史审查记忆"""
    session = next(get_session())
    try:
        query = session.query(ReviewMemoryRecord)
        if file_path:
            query = query.filter(ReviewMemoryRecord.file_path == file_path)
        records = query.order_by(ReviewMemoryRecord.created_at.desc()).limit(top_k).all()
        return [
            {
                "file": r.file_path,
                "category": r.category,
                "severity": r.severity,
                "title": r.title,
                "description": r.description,
                "suggestion": r.suggestion,
                "review_id": r.review_id,
            }
            for r in records
        ]
    finally:
        session.close()
