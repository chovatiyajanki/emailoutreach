import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .database import Base


def utc_now():
    return datetime.now(timezone.utc)


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    search_query = Column(String(255), nullable=False)
    scrape_batch_size = Column(Integer, default=5, nullable=False)
    send_batch_size = Column(Integer, default=5, nullable=False)
    interval_seconds = Column(Integer, default=60, nullable=False)
    email_subject = Column(String(500), nullable=True)
    email_body = Column(Text, nullable=True)
    status = Column(String(50), default="active", nullable=False)  # active, paused, completed
    total_runs = Column(Integer, default=0, nullable=False)
    total_leads_scraped = Column(Integer, default=0, nullable=False)
    total_emails_sent = Column(Integer, default=0, nullable=False)
    total_replies = Column(Integer, default=0, nullable=False)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    runs = relationship("SchedulerRun", back_populates="campaign", cascade="all, delete-orphan")


class SchedulerConfig(Base):
    __tablename__ = "scheduler_config"

    id = Column(Integer, primary_key=True, default=1)
    is_running = Column(Boolean, default=False, nullable=False)
    interval_seconds = Column(Integer, default=60, nullable=False)
    search_query = Column(String(255), default="", nullable=False)
    scrape_batch_size = Column(Integer, default=5, nullable=False)
    send_batch_size = Column(Integer, default=5, nullable=False)
    campaign_name = Column(String(255), default="", nullable=True)
    active_campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=True)
    email_subject = Column(String(500), default="", nullable=True)
    email_body = Column(Text, default="", nullable=True)
    smtp_host = Column(String(255), default=None, nullable=True)
    smtp_port = Column(Integer, default=None, nullable=True)
    smtp_username = Column(String(255), default=None, nullable=True)
    smtp_password = Column(String(255), default=None, nullable=True)
    sender_name = Column(String(255), default=None, nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    total_runs = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class SchedulerRun(Base):
    __tablename__ = "scheduler_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_number = Column(Integer, nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=True)
    campaign_name = Column(String(255), nullable=True)
    started_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), default="running", nullable=False)  # running, completed, failed
    query_used = Column(String(255), nullable=True)
    
    # Step metrics
    scraped_count = Column(Integer, default=0, nullable=False)
    found_count = Column(Integer, default=0, nullable=False)
    sent_count = Column(Integer, default=0, nullable=False)
    undelivered_count = Column(Integer, default=0, nullable=False)
    replies_count = Column(Integer, default=0, nullable=False)
    
    logs = Column(JSON, default=list, nullable=False)
    error_message = Column(Text, nullable=True)

    campaign = relationship("Campaign", back_populates="runs")


class CompanyMailAccount(Base):
    __tablename__ = "company_mail_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name = Column(String(255), nullable=False)
    website = Column(String(500), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    industry = Column(String(100), default="Technology")
    city = Column(String(100), default="Global")
    verification_score = Column(Float, default=85.0)
    status = Column(String(50), default="email_found", nullable=False)  # email_found, sent, bounced, replies, replied, blocked_message
    scraped_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    run_id = Column(UUID(as_uuid=True), ForeignKey("scheduler_runs.id"), nullable=True)

    sent_mails = relationship("SentMail", back_populates="company_account")


class SentMail(Base):
    __tablename__ = "sent_mails"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("company_mail_accounts.id"), nullable=True)
    to_email = Column(String(255), index=True, nullable=False)
    from_email = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=False)
    body_snippet = Column(Text, nullable=False)
    status = Column(String(50), default="sent", nullable=False)  # sent, bounced, replies, replied, blocked_message
    delivery_mode = Column(String(50), default="live_smtp", nullable=False)  # live_smtp, simulation
    sent_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    run_id = Column(UUID(as_uuid=True), ForeignKey("scheduler_runs.id"), nullable=True)

    company_account = relationship("CompanyMailAccount", back_populates="sent_mails")
    undelivered = relationship("UndeliveredMail", back_populates="sent_mail", uselist=False)
    reply = relationship("MailReply", back_populates="sent_mail", uselist=False)


class UndeliveredMail(Base):
    __tablename__ = "undelivered_mails"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sent_mail_id = Column(UUID(as_uuid=True), ForeignKey("sent_mails.id"), nullable=True)
    to_email = Column(String(255), index=True, nullable=False)
    bounce_reason = Column(String(500), default="550 5.1.1 Recipient mailbox not found", nullable=False)
    error_code = Column(String(50), default="550", nullable=False)
    detected_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    is_suppressed = Column(Boolean, default=True, nullable=False)
    run_id = Column(UUID(as_uuid=True), ForeignKey("scheduler_runs.id"), nullable=True)

    sent_mail = relationship("SentMail", back_populates="undelivered")


class MailReply(Base):
    __tablename__ = "mail_replies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sent_mail_id = Column(UUID(as_uuid=True), ForeignKey("sent_mails.id"), nullable=True)
    from_email = Column(String(255), index=True, nullable=False)
    to_email = Column(String(255), nullable=True)
    subject = Column(String(500), nullable=False)
    body = Column(Text, nullable=False)
    has_reply = Column(Boolean, default=True, nullable=False)
    sentiment = Column(String(50), default="Interested", nullable=False)  # Interested, Meeting Requested, Not Interested, Out of Office
    ai_summary = Column(Text, nullable=True)
    received_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    run_id = Column(UUID(as_uuid=True), ForeignKey("scheduler_runs.id"), nullable=True)

    sent_mail = relationship("SentMail", back_populates="reply")


class SuppressionList(Base):
    __tablename__ = "suppression_list"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, index=True, nullable=False)
    reason = Column(String(255), default="Undelivered bounce failure", nullable=False)
    added_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)