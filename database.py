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
