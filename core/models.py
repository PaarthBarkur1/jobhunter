from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Integer, Float, Boolean, Text, ForeignKey, DateTime, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class Company(Base):
    __tablename__ = "companies"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    career_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    ats_provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True) # e.g., 'greenhouse', 'lever', 'workday'
    ats_slug: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)     # e.g., 'towerresearchcapital'
    is_target: Mapped[bool] = mapped_column(Boolean, default=False)
    
    jobs: Mapped[List["JobPosting"]] = relationship("JobPosting", back_populates="company", cascade="all, delete-orphan")

class JobPosting(Base):
    __tablename__ = "job_postings"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    role_category: Mapped[Optional[str]] = mapped_column(String(150), nullable=True) # e.g., 'Quant Researcher', 'Data Scientist'
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)        # e.g., 'lever_api', 'greenhouse_api', 'web_search'
    
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    company: Mapped["Company"] = relationship("Company", back_populates="jobs")
    
    # Compensation & Experience
    estimated_ctc: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    explicit_salary_str: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    experience_level: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    
    # LLM Evaluation & Intelligence
    required_skills: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    match_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    match_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_curve_ball: Mapped[bool] = mapped_column(Boolean, default=False)
    curve_ball_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # User Interaction & Lifecycle
    status: Mapped[str] = mapped_column(String(50), default="unrated", index=True) # 'unrated', 'thumbs_up', 'thumbs_down', 'applied', 'closed'
    feedback_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    posted_date: Mapped[Optional[str]] = mapped_column(String(100), default="Unknown")
    date_discovered: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ScanLog(Base):
    __tablename__ = "scan_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(50), default="running") # 'running', 'completed', 'failed'
    jobs_discovered: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
