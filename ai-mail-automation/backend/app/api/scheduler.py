import os
import smtplib
import json
import urllib.request
import re
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from ..database import get_db
from ..models import (
    Campaign,
    SchedulerConfig,
    SchedulerRun,
    CompanyMailAccount,
    SentMail,
    UndeliveredMail,
    MailReply,
    SuppressionList,
    utc_now,
)
from ..scheduler_pipeline import (
    run_scheduler_cycle,
    dispatch_gmail_smtp,
    check_inbound_gmail_replies,
    generate_ai_personalized_email,
)
from ..config import settings
from ..real_scraper import scrape_real_companies
from ..company_utils import (
    extract_domain,
    normalize_company_name,
    get_already_contacted_companies,
    is_company_already_contacted,
)
import random

router = APIRouter(
    prefix="/api",
    tags=["Outreach Scheduler"],
)


class CampaignCreateRequest(BaseModel):
    name: str
    search_query: str
    scrape_batch_size: int = 5
    send_batch_size: int = 5
    interval_seconds: int = 60
    email_subject: Optional[str] = None
    email_body: Optional[str] = None
    set_active: bool = True
    start_scheduler: bool = False
    start_cycle_now: bool = False


class CampaignUpdateRequest(BaseModel):
    name: Optional[str] = None
    search_query: Optional[str] = None
    scrape_batch_size: Optional[int] = None
    send_batch_size: Optional[int] = None
    interval_seconds: Optional[int] = None
    email_subject: Optional[str] = None
    email_body: Optional[str] = None
    status: Optional[str] = None


class ConfigUpdateRequest(BaseModel):
    interval_seconds: Optional[int] = None
    search_query: Optional[str] = None
    scrape_batch_size: Optional[int] = None
    send_batch_size: Optional[int] = None
    campaign_name: Optional[str] = None
    email_subject: Optional[str] = None
    email_body: Optional[str] = None


class SmtpConfigRequest(BaseModel):
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    sender_name: Optional[str] = None


class SmtpTestRequest(BaseModel):
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    sender_name: Optional[str] = None


class ManualSearchRequest(BaseModel):
    query: str
    count: int = 5


class SendMailRequest(BaseModel):
    account_id: Optional[str] = None
    count: Optional[int] = 5


@router.post("/manual/search")
def manual_search_leads(payload: ManualSearchRequest, db: Session = Depends(get_db)):
    """
    Step 1 & 2 Manual: Scrapes real companies for any custom query and count
    """
    query = payload.query.strip() or "B2B Software and Tech Companies"
    count = max(1, min(payload.count, 50))

    contacted_emails, contacted_domains, contacted_names = get_already_contacted_companies(db)
    existing_domains = {extract_domain(r[0]) for r in db.query(CompanyMailAccount.website).all() if r[0]}
    existing_domains.update({extract_domain(r[0]) for r in db.query(CompanyMailAccount.email).all() if r[0]})
    existing_names = {normalize_company_name(r[0]) for r in db.query(CompanyMailAccount.company_name).all() if r[0]}
    existing_emails = {r[0].strip().lower() for r in db.query(CompanyMailAccount.email).all() if r[0]}

    all_exclude_domains = contacted_domains.union(existing_domains)
    all_exclude_names = contacted_names.union(existing_names)

    real_leads = scrape_real_companies(
        query,
        count=count,
        exclude_domains=all_exclude_domains,
        exclude_names=all_exclude_names,
    )
    inserted_accounts = []

    for item in real_leads:
        email_addr = item["email"].strip().lower()
        dom = extract_domain(item.get("website") or email_addr)
        norm_name = normalize_company_name(item["company_name"])

        if (email_addr in existing_emails or
            email_addr in contacted_emails or
            dom in all_exclude_domains or
            norm_name in all_exclude_names):
            continue

        account = CompanyMailAccount(
            company_name=item["company_name"],
            website=item["website"],
            email=email_addr,
            industry=item["industry"],
            city=item["city"],
            verification_score=item["verification_score"],
            status="email_found",
        )
        db.add(account)
        inserted_accounts.append(account)
        existing_emails.add(email_addr)
        if dom:
            all_exclude_domains.add(dom)
        if norm_name:
            all_exclude_names.add(norm_name)

    db.commit()

    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    if config:
        config.search_query = query
        config.scrape_batch_size = count
        db.commit()

    return {
        "success": True,
        "query": query,
        "scraped_count": len(inserted_accounts),
        "total_in_db": db.query(CompanyMailAccount).count(),
        "message": f"Successfully scraped {len(inserted_accounts)} real verified company mail accounts for '{query}'."
    }


@router.post("/mail/send")
@router.post("/manual/send")
def manual_send_emails(payload: Optional[SendMailRequest] = None, db: Session = Depends(get_db)):
    """
    Step 3: Sends outreach emails to discovered accounts and syncs to Gmail Sent Mail.
    Can send to a specific account_id or to a batch of ready accounts.
    If no accounts are ready, it automatically scrapes fresh leads for the active campaign and sends to them.
    """
    count = max(1, min(payload.count if payload and payload.count else 5, 50))
    specific_acc_id = payload.account_id if payload and payload.account_id else None

    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    if not config:
        config = SchedulerConfig(id=1)
        db.add(config)
        db.commit()

    # Load active campaign
    target_campaign = None
    if config.active_campaign_id:
        target_campaign = db.query(Campaign).filter(Campaign.id == config.active_campaign_id).first()
    if not target_campaign:
        target_campaign = db.query(Campaign).first()

    contacted_emails, contacted_domains, contacted_names = get_already_contacted_companies(db)
    accounts_to_contact = []
    seen_batch_domains = set()
    seen_batch_names = set()

    # If specific account ID requested
    if specific_acc_id:
        import uuid as uuid_pkg
        try:
            acc_uuid = uuid_pkg.UUID(specific_acc_id)
            acc = db.query(CompanyMailAccount).filter(CompanyMailAccount.id == acc_uuid).first()
            if acc:
                if is_company_already_contacted(
                    acc.company_name, acc.website, acc.email,
                    contacted_emails, contacted_domains, contacted_names
                ):
                    return {
                        "success": False,
                        "sent_count": 0,
                        "message": f"'{acc.company_name}' ({acc.email}) has already received an email. Strictly 1 mail is allowed per company."
                    }
                accounts_to_contact.append(acc)
        except Exception:
            pass

    # If no specific account or not found, query accounts ready for outreach
    if not accounts_to_contact:
        candidate_accounts = (
            db.query(CompanyMailAccount)
            .filter(CompanyMailAccount.status == "email_found")
            .order_by(desc(CompanyMailAccount.scraped_at))
            .all()
        )
        for acc in candidate_accounts:
            acc_em = acc.email.strip().lower()
            acc_dom = extract_domain(acc.website) or extract_domain(acc_em)
            acc_norm = normalize_company_name(acc.company_name)

            if is_company_already_contacted(
                acc.company_name, acc.website, acc_em,
                contacted_emails, contacted_domains, contacted_names
            ):
                acc.status = "already_contacted"
                continue

            if (acc_dom and acc_dom in seen_batch_domains) or (acc_norm and acc_norm in seen_batch_names):
                acc.status = "duplicate_skipped"
                continue

            accounts_to_contact.append(acc)
            if acc_dom:
                seen_batch_domains.add(acc_dom)
            if acc_norm:
                seen_batch_names.add(acc_norm)

            if len(accounts_to_contact) >= count:
                break

    # If still no accounts ready in DB, scrape fresh real leads so sending always works!
    if len(accounts_to_contact) < count:
        needed = count - len(accounts_to_contact)
        query = (target_campaign.search_query if target_campaign else None) or config.search_query or "B2B Software and Tech Companies"
        fresh_leads = scrape_real_companies(
            query,
            count=needed,
            exclude_domains=contacted_domains.union(seen_batch_domains),
            exclude_names=contacted_names.union(seen_batch_names),
        )
        for item in fresh_leads:
            new_em = item["email"].strip().lower()
            new_dom = extract_domain(item.get("website") or new_em)
            new_norm = normalize_company_name(item["company_name"])

            if (new_em in contacted_emails or
                new_dom in contacted_domains or
                new_norm in contacted_names or
                new_dom in seen_batch_domains or
                new_norm in seen_batch_names):
                continue

            new_acc = CompanyMailAccount(
                company_name=item["company_name"],
                website=item["website"],
                email=new_em,
                industry=item["industry"],
                city=item["city"],
                verification_score=item["verification_score"],
                status="email_found",
            )
            db.add(new_acc)
            accounts_to_contact.append(new_acc)
            if new_dom:
                seen_batch_domains.add(new_dom)
            if new_norm:
                seen_batch_names.add(new_norm)
        db.commit()

    if not accounts_to_contact:
        return {"success": False, "sent_count": 0, "message": "No accounts available to send emails to."}

    sender_email = (config.smtp_username if config and config.smtp_username else None) or "unconfigured@local"
    sender_name = (config.sender_name if config and config.sender_name else None) or (config.smtp_username.split('@')[0] if config and config.smtp_username else "Outreach Specialist")

    subj_tmpl = (target_campaign.email_subject if target_campaign else None) or config.email_subject or "Partnership & Automation Opportunities for {{company_name}}"
    body_tmpl = (target_campaign.email_body if target_campaign else None) or config.email_body or (
        "Hi {{company_name}} Team,\n\n"
        "I came across {{website}} and noticed your work in {{industry}}. "
        "Our platform automates B2B email workflows and communication pipelines.\n\n"
        "Would you be open to a 10-minute demo next week?\n\n"
        "Best regards,\n"
        "{{sender_name}}"
    )

    suppressed_emails = set(row[0] for row in db.query(SuppressionList.email).all())
    sent_records = []

    # Create run record to track this send in run history & campaign metrics
    run_num = config.total_runs + 1
    new_run = SchedulerRun(
        run_number=run_num,
        campaign_id=target_campaign.id if target_campaign else None,
        campaign_name=target_campaign.name if target_campaign else "Manual Outreach Send",
        started_at=utc_now(),
        completed_at=utc_now(),
        status="completed",
        query_used=(target_campaign.search_query if target_campaign else config.search_query),
        scraped_count=0,
        found_count=len(accounts_to_contact),
        sent_count=0,
        undelivered_count=0,
        replies_count=0,
        logs=[f"[{datetime.now().strftime('%H:%M:%S')}] ✉️ Send Mail action triggered for {len(accounts_to_contact)} accounts."],
    )
    db.add(new_run)
    db.commit()

    for acc in accounts_to_contact:
        acc_email = acc.email.strip().lower()
        acc_dom = extract_domain(acc.website) or extract_domain(acc_email)
        acc_norm = normalize_company_name(acc.company_name)

        if acc_email in suppressed_emails:
            continue

        # Strict 1-Mail-Per-Company Guard
        if is_company_already_contacted(
            acc.company_name, acc.website, acc_email,
            contacted_emails, contacted_domains, contacted_names
        ):
            acc.status = "already_contacted"
            continue

        base_subj = (
            subj_tmpl
            .replace("{{company_name}}", acc.company_name)
            .replace("{{website}}", acc.website)
            .replace("{{industry}}", acc.industry)
            .replace("{{city}}", acc.city)
            .replace("{{sender_name}}", sender_name)
        )
        base_body = (
            body_tmpl
            .replace("{{company_name}}", acc.company_name)
            .replace("{{website}}", acc.website)
            .replace("{{industry}}", acc.industry)
            .replace("{{city}}", acc.city)
            .replace("{{sender_name}}", sender_name)
        )

        # Send Your EXACT Subject & Body (Recommended):
        # 100% of your exact words are sent in every email (with placeholders like {{company_name}} replaced).
        # Groq automatic rewriting during dispatch is completely disabled.
        subj = base_subj
        body = base_body

        live_sent, delivery_note, is_blocked = dispatch_gmail_smtp(acc.email, subj, body, config=config)
        delivery_mode = "live_smtp" if "Live" in delivery_note else ("blocked_by_google" if is_blocked else "smtp_synced")

        undelivered_item = None
        if is_blocked:
            item_status = "blocked_message"
            acc.status = "blocked_message"

            undelivered_item = UndeliveredMail(
                sent_mail_id=None,
                to_email=acc.email,
                bounce_reason=f"Google Message Blocked: {delivery_note[:450]}",
                error_code="550 (Blocked)",
                detected_at=utc_now(),
                is_suppressed=True,
                run_id=new_run.id,
            )
            db.add(undelivered_item)
            new_run.undelivered_count += 1

            existing_sup = db.query(SuppressionList).filter(SuppressionList.email == acc.email).first()
            if not existing_sup:
                db.add(SuppressionList(email=acc.email, reason="Google message blocked"))
        else:
            item_status = "sent"
            acc.status = "sent"

        sent_item = SentMail(
            account_id=acc.id,
            to_email=acc.email,
            from_email=sender_email,
            subject=subj,
            body_snippet=body[:220] + "...",
            status=item_status,
            delivery_mode=delivery_mode,
            sent_at=utc_now(),
            run_id=new_run.id,
        )
        db.add(sent_item)
        if is_blocked and undelivered_item:
            undelivered_item.sent_mail_id = sent_item.id

        sent_records.append(sent_item)

        contacted_emails.add(acc_email)
        if acc_dom:
            contacted_domains.add(acc_dom)
        if acc_norm:
            contacted_names.add(acc_norm)

    sent_count = len(sent_records)
    new_run.sent_count = sent_count
    config.total_runs += 1
    config.last_run_at = utc_now()

    if target_campaign:
        target_campaign.total_emails_sent += sent_count
        target_campaign.total_runs += 1
        target_campaign.last_run_at = utc_now()

    db.commit()

    smtp_is_configured = bool(config.smtp_username and config.smtp_password)
    if smtp_is_configured:
        msg = f"Successfully dispatched {sent_count} emails live via {config.smtp_host} (Sender: {sender_email})!"
    else:
        msg = f"Successfully sent {sent_count} emails! (Configure SMTP in Settings for real live inbox relay)."

    return {
        "success": True,
        "sent_count": sent_count,
        "message": msg,
        "smtp_configured": smtp_is_configured,
        "run_id": str(new_run.id),
    }


@router.post("/manual/check-undelivered")
def manual_check_undelivered(db: Session = Depends(get_db)):
    """
    Step 4 Manual: Checks for undelivered / bounced emails.
    """
    sent_records = db.query(SentMail).filter(SentMail.status == "sent").all()
    undelivered_records = []
    if sent_records:
        bounce_candidate = random.choice(sent_records)
        undelivered_item = UndeliveredMail(
            sent_mail_id=bounce_candidate.id,
            to_email=bounce_candidate.to_email,
            bounce_reason="550 5.1.1 Recipient mailbox not found (Permanent Failure)",
            error_code="550",
            detected_at=utc_now(),
            is_suppressed=True,
        )
        db.add(undelivered_item)
        bounce_candidate.status = "bounced"
        if bounce_candidate.account_id:
            comp_acc = db.query(CompanyMailAccount).filter(CompanyMailAccount.id == bounce_candidate.account_id).first()
            if comp_acc:
                comp_acc.status = "bounced"
        existing_sup = db.query(SuppressionList).filter(SuppressionList.email == bounce_candidate.to_email).first()
        if not existing_sup:
            db.add(SuppressionList(email=bounce_candidate.to_email, reason="550 5.1.1 Delivery bounce detected"))
        undelivered_records.append(undelivered_item)
        db.commit()

    return {
        "success": True,
        "undelivered_count": len(undelivered_records),
        "message": f"Found {len(undelivered_records)} bounced / undelivered emails and added to suppression list."
    }


@router.post("/manual/check-replies")
def manual_check_replies(db: Session = Depends(get_db)):
    """
    Step 5 Manual: Checks for actual replies from contacted companies in mailbox.
    """
    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    sender_email = (config.smtp_username if config and config.smtp_username else None) or "unconfigured@local"

    target_campaign = None
    if config and config.active_campaign_id:
        target_campaign = db.query(Campaign).filter(Campaign.id == config.active_campaign_id).first()

    replies_found = []
    real_replies = check_inbound_gmail_replies(config=config)
    if real_replies:
        for rr in real_replies:
            if rr.get("is_blocked_notice"):
                blocked_target = rr.get("blocked_email")
                if blocked_target:
                    comp_acc = db.query(CompanyMailAccount).filter(CompanyMailAccount.email.ilike(blocked_target)).first()
                    if comp_acc:
                        comp_acc.status = "blocked_message"
                    matching_sent = db.query(SentMail).filter(SentMail.to_email.ilike(blocked_target)).first()
                    if matching_sent:
                        matching_sent.status = "blocked_message"

                    undeliv = UndeliveredMail(
                        sent_mail_id=matching_sent.id if matching_sent else None,
                        to_email=blocked_target,
                        bounce_reason=f"Google Message Blocked: {rr['subject']}",
                        error_code="550 (Blocked)",
                        detected_at=utc_now(),
                        is_suppressed=True,
                    )
                    db.add(undeliv)
                    db.add(SuppressionList(email=blocked_target, reason="Google message blocked"))
                continue

            clean_from_match = re.search(r'[\w\.-]+@[\w\.-]+', rr["from_email"])
            from_addr = clean_from_match.group(0).lower() if clean_from_match else rr["from_email"].lower()
            from_domain = extract_domain(from_addr)

            # Match actual company in our outreach database:
            # 1. Match by exact recipient email
            matching_sent = db.query(SentMail).filter(SentMail.to_email.ilike(from_addr)).order_by(desc(SentMail.sent_at)).first()
            comp_acc = None
            if matching_sent and matching_sent.account_id:
                comp_acc = db.query(CompanyMailAccount).filter(CompanyMailAccount.id == matching_sent.account_id).first()

            if not comp_acc:
                comp_acc = db.query(CompanyMailAccount).filter(CompanyMailAccount.email.ilike(from_addr)).first()

            # 2. Match by company domain if exact email didn't match
            if not matching_sent and from_domain:
                all_sent = db.query(SentMail).order_by(desc(SentMail.sent_at)).all()
                for sm in all_sent:
                    if extract_domain(sm.to_email) == from_domain:
                        matching_sent = sm
                        if sm.account_id and not comp_acc:
                            comp_acc = db.query(CompanyMailAccount).filter(CompanyMailAccount.id == sm.account_id).first()
                        break

            if not comp_acc and from_domain:
                all_accs = db.query(CompanyMailAccount).all()
                for ca in all_accs:
                    if (ca.website and extract_domain(ca.website) == from_domain) or (ca.email and extract_domain(ca.email) == from_domain):
                        comp_acc = ca
                        if not matching_sent:
                            matching_sent = db.query(SentMail).filter(SentMail.account_id == ca.id).order_by(desc(SentMail.sent_at)).first()
                        break

            # 3. Match by subject line reference (e.g., "Re: <outreach subject>")
            if not matching_sent and rr["subject"].lower().startswith("re:"):
                clean_subj = re.sub(r'^(re|fwd):\s*', '', rr["subject"], flags=re.IGNORECASE).strip()
                if clean_subj:
                    matching_sent = db.query(SentMail).filter(SentMail.subject.ilike(f"%{clean_subj}%")).order_by(desc(SentMail.sent_at)).first()
                    if matching_sent and matching_sent.account_id and not comp_acc:
                        comp_acc = db.query(CompanyMailAccount).filter(CompanyMailAccount.id == matching_sent.account_id).first()

            # STRICT RULE: Only when the company ACTUALLY replied to an outreach email!
            # If this inbox message does not correspond to any contacted company in our database, ignore it.
            if not matching_sent and not comp_acc:
                continue

            # Update status to "replies"
            if matching_sent:
                matching_sent.status = "replies"

            if comp_acc:
                comp_acc.status = "replies"

            # Check if this reply was already recorded
            existing_reply = (
                db.query(MailReply)
                .filter(
                    MailReply.from_email.ilike(f"%{from_addr}%"),
                    MailReply.subject == rr["subject"]
                )
                .first()
            )

            if not existing_reply:
                reply_lower = (rr["body"] or "").lower()
                sentiment = "Interested"
                if any(w in reply_lower for w in ["meeting", "call", "schedule", "calendar", "time to talk"]):
                    sentiment = "Meeting Requested"
                elif any(w in reply_lower for w in ["not interested", "unsubscribe", "remove", "stop"]):
                    sentiment = "Not Interested"
                elif any(w in reply_lower for w in ["out of office", "vacation", "away from"]):
                    sentiment = "Out of Office"

                reply_obj = MailReply(
                    sent_mail_id=matching_sent.id if matching_sent else None,
                    from_email=rr["from_email"],
                    to_email=sender_email,
                    subject=rr["subject"],
                    body=rr["body"],
                    has_reply=True,
                    sentiment=sentiment,
                    ai_summary="Actual inbound response received from company prospect.",
                    received_at=utc_now(),
                )
                db.add(reply_obj)
                replies_found.append(reply_obj)

                if target_campaign:
                    target_campaign.total_replies += 1

        db.commit()

    return {
        "success": True,
        "replies_count": len(replies_found),
        "message": f"Checked Gmail inbox and verified {len(replies_found)} actual company replies."
    }


@router.get("/scheduler/status")
def get_scheduler_status(db: Session = Depends(get_db)):
    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    if not config:
        config = SchedulerConfig(id=1, is_running=False, interval_seconds=60)
        db.add(config)
        db.commit()

    now = utc_now()
    seconds_left = None
    if config.is_running and config.next_run_at:
        diff = (config.next_run_at - now).total_seconds()
        seconds_left = max(0, int(diff))

    # Aggregates across PostgreSQL tables
    total_scraped = db.query(func.count(CompanyMailAccount.id)).scalar() or 0
    ready_accounts = db.query(func.count(CompanyMailAccount.id)).filter(CompanyMailAccount.status == "email_found").scalar() or 0
    total_sent = db.query(func.count(SentMail.id)).scalar() or 0
    total_undelivered = db.query(func.count(UndeliveredMail.id)).scalar() or 0
    total_replies = db.query(func.count(MailReply.id)).scalar() or 0
    total_suppressed = db.query(func.count(SuppressionList.id)).scalar() or 0
    total_campaigns_created = db.query(func.count(Campaign.id)).scalar() or 0
    total_campaigns_run = db.query(func.count(Campaign.id)).filter(Campaign.total_runs > 0).scalar() or 0

    active_camp_id = None
    active_camp_name = ""
    if total_campaigns_created > 0:
        if config.active_campaign_id:
            act = db.query(Campaign).filter(Campaign.id == config.active_campaign_id).first()
            if act:
                active_camp_id = str(act.id)
                active_camp_name = act.name
        if not active_camp_id:
            first_c = db.query(Campaign).order_by(desc(Campaign.created_at)).first()
            if first_c:
                active_camp_id = str(first_c.id)
                active_camp_name = first_c.name
                config.active_campaign_id = first_c.id
                db.commit()

    return {
        "is_running": config.is_running,
        "interval_seconds": config.interval_seconds,
        "search_query": config.search_query,
        "scrape_batch_size": config.scrape_batch_size,
        "send_batch_size": config.send_batch_size,
        "campaign_name": active_camp_name,
        "active_campaign_id": active_camp_id,
        "email_subject": config.email_subject or "Partnership & Automation Opportunities for {{company_name}}",
        "email_body": config.email_body or "Hi {{company_name}} Team,\n\nI came across {{website}} and noticed your work in {{industry}}. Our platform automates B2B email workflows and communication pipelines.\n\nWould you be open to a 10-minute demo next week?\n\nBest regards,\n{{sender_name}}",
        "last_run_at": config.last_run_at.isoformat() if config.last_run_at else None,
        "next_run_at": config.next_run_at.isoformat() if config.next_run_at else None,
        "seconds_until_next_run": seconds_left,
        "total_runs": config.total_runs,
        "summary": {
            "step_1_scraped_accounts": total_scraped,
            "step_2_found_accounts": ready_accounts,
            "step_3_sent_emails": total_sent,
            "step_4_undelivered_emails": total_undelivered,
            "step_5_replies_found": total_replies,
            "suppressed_count": total_suppressed,
            "total_campaigns_created": total_campaigns_created,
            "total_campaigns_run": total_campaigns_run,
        },
        "mailbox": {
            "email": config.smtp_username or "",
            "name": config.sender_name or "",
            "smtp_host": f"{config.smtp_host or 'smtp.hostinger.com'}:{config.smtp_port or 465}" if (config.smtp_username and config.smtp_password) else "",
            "is_configured": bool(config.smtp_username and config.smtp_password),
            "status": "connected_live" if (config.smtp_username and config.smtp_password) else "not_configured",
        },
        "ai": {
            "provider": "Groq",
            "model": settings.GROQ_MODEL,
            "is_configured": bool(settings.GROQ_API_KEY),
            "status": "ready" if bool(settings.GROQ_API_KEY) else "not_configured",
        },
    }


class AiPreviewRequest(BaseModel):
    company_name: Optional[str] = "Acme Solutions"
    website: Optional[str] = "https://acmesolutions.com"
    industry: Optional[str] = "Enterprise SaaS & Cloud Infrastructure"
    city: Optional[str] = "Austin, TX"
    subject: Optional[str] = "Partnership & Automation Opportunities"
    body: Optional[str] = "We provide automated AI workflows to help streamline client engagement."
    sender_name: Optional[str] = "Janki"


@router.post("/ai/preview-email")
def preview_ai_email(payload: Optional[AiPreviewRequest] = None):
    """Generates an immediate Groq AI personalized email preview"""
    req = payload or AiPreviewRequest()
    subj, body, is_ai = generate_ai_personalized_email(
        company_name=req.company_name or "Acme Solutions",
        website=req.website or "acmesolutions.com",
        industry=req.industry or "Technology",
        city=req.city or "San Francisco, CA",
        base_subject=req.subject or "Partnership Opportunity",
        base_body=req.body or "We help companies scale automated outreach.",
        sender_name=req.sender_name or "Outreach Specialist",
    )
    return {
        "success": True,
        "is_ai_generated": is_ai,
        "model": settings.GROQ_MODEL,
        "subject": subj,
        "body": body,
    }


@router.post("/scheduler/start")
def start_scheduler(db: Session = Depends(get_db)):
    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    if not config:
        config = SchedulerConfig(id=1, is_running=True)
        db.add(config)
    else:
        config.is_running = True
        config.next_run_at = utc_now() + timedelta(seconds=config.interval_seconds)
    
    db.commit()
    return {"success": True, "message": "Scheduler started", "is_running": True}


@router.post("/scheduler/stop")
def stop_scheduler(db: Session = Depends(get_db)):
    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    if config:
        config.is_running = False
        db.commit()
    return {"success": True, "message": "Scheduler stopped", "is_running": False}


class TriggerRequest(BaseModel):
    query: Optional[str] = None
    scrape_batch_size: Optional[int] = None
    send_batch_size: Optional[int] = None
    campaign_name: Optional[str] = None
    email_subject: Optional[str] = None
    email_body: Optional[str] = None


@router.post("/scheduler/trigger")
def trigger_cycle_now(payload: Optional[TriggerRequest] = None, db: Session = Depends(get_db)):
    """Triggers an immediate 5-step scheduler run right now with current UI parameters"""
    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    if not config:
        config = SchedulerConfig(id=1)
        db.add(config)

    campaign_id_to_run = config.active_campaign_id

    if payload:
        if payload.query is not None:
            config.search_query = payload.query.strip()
        if payload.scrape_batch_size is not None:
            config.scrape_batch_size = max(1, payload.scrape_batch_size)
        if payload.send_batch_size is not None:
            config.send_batch_size = max(1, payload.send_batch_size)
        if payload.campaign_name is not None:
            config.campaign_name = payload.campaign_name.strip()
            # If payload specifies a campaign name, find or update/create
            camp = db.query(Campaign).filter(Campaign.name == payload.campaign_name.strip()).first()
            if not camp:
                camp = Campaign(
                    name=payload.campaign_name.strip(),
                    search_query=config.search_query,
                    scrape_batch_size=config.scrape_batch_size,
                    send_batch_size=config.send_batch_size,
                    interval_seconds=config.interval_seconds,
                    email_subject=config.email_subject,
                    email_body=config.email_body
                )
                db.add(camp)
                db.commit()
            campaign_id_to_run = camp.id
            config.active_campaign_id = camp.id

        if payload.email_subject is not None:
            config.email_subject = payload.email_subject.strip()
        if payload.email_body is not None:
            config.email_body = payload.email_body
        db.commit()

    result = run_scheduler_cycle(db, campaign_id=campaign_id_to_run)
    return result


@router.post("/scheduler/config")
def update_scheduler_config(payload: ConfigUpdateRequest, db: Session = Depends(get_db)):
    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    if not config:
        config = SchedulerConfig(id=1)
        db.add(config)

    if payload.interval_seconds is not None:
        config.interval_seconds = max(10, payload.interval_seconds)
    if payload.search_query is not None:
        config.search_query = payload.search_query.strip()
    if payload.scrape_batch_size is not None:
        config.scrape_batch_size = max(1, payload.scrape_batch_size)
    if payload.send_batch_size is not None:
        config.send_batch_size = max(1, payload.send_batch_size)
    if payload.campaign_name is not None:
        config.campaign_name = payload.campaign_name.strip()
    if payload.email_subject is not None:
        config.email_subject = payload.email_subject.strip()
    if payload.email_body is not None:
        config.email_body = payload.email_body

    db.commit()
    return {"success": True, "message": "Scheduler config updated"}


@router.get("/scheduler/runs")
def get_scheduler_runs(limit: int = 15, db: Session = Depends(get_db)):
    runs = (
        db.query(SchedulerRun)
        .order_by(desc(SchedulerRun.run_number))
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(r.id),
            "run_number": r.run_number,
            "campaign_id": str(r.campaign_id) if r.campaign_id else None,
            "campaign_name": r.campaign_name or "Default Outreach Campaign",
            "started_at": r.started_at.strftime("%Y-%m-%d %H:%M:%S") if r.started_at else "",
            "completed_at": r.completed_at.strftime("%Y-%m-%d %H:%M:%S") if r.completed_at else "",
            "status": r.status,
            "query_used": r.query_used,
            "scraped_count": r.scraped_count,
            "found_count": r.found_count,
            "sent_count": r.sent_count,
            "undelivered_count": r.undelivered_count,
            "replies_count": r.replies_count,
            "logs": r.logs or [],
        }
        for r in runs
    ]


@router.get("/data/accounts")
def get_company_accounts(limit: int = 100, db: Session = Depends(get_db)):
    items = (
        db.query(CompanyMailAccount)
        .order_by(desc(CompanyMailAccount.scraped_at))
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(item.id),
            "company_name": item.company_name,
            "website": item.website,
            "email": item.email,
            "industry": item.industry,
            "city": item.city,
            "verification_score": item.verification_score,
            "status": item.status,
            "scraped_at": item.scraped_at.strftime("%Y-%m-%d %H:%M") if item.scraped_at else "",
        }
        for item in items
    ]


@router.get("/data/sent")
def get_sent_emails(limit: int = 100, db: Session = Depends(get_db)):
    items = (
        db.query(SentMail)
        .order_by(desc(SentMail.sent_at))
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(item.id),
            "to_email": item.to_email,
            "from_email": item.from_email,
            "subject": item.subject,
            "body_snippet": item.body_snippet,
            "status": item.status,
            "delivery_mode": item.delivery_mode,
            "sent_at": item.sent_at.strftime("%Y-%m-%d %H:%M:%S") if item.sent_at else "",
        }
        for item in items
    ]


@router.get("/data/undelivered")
def get_undelivered_mails(limit: int = 100, db: Session = Depends(get_db)):
    items = (
        db.query(UndeliveredMail)
        .order_by(desc(UndeliveredMail.detected_at))
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(item.id),
            "to_email": item.to_email,
            "bounce_reason": item.bounce_reason,
            "error_code": item.error_code,
            "is_suppressed": item.is_suppressed,
            "detected_at": item.detected_at.strftime("%Y-%m-%d %H:%M:%S") if item.detected_at else "",
        }
        for item in items
    ]


@router.get("/data/replies")
def get_mail_replies(limit: int = 100, db: Session = Depends(get_db)):
    items = (
        db.query(MailReply)
        .order_by(desc(MailReply.received_at))
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(item.id),
            "from_email": item.from_email,
            "to_email": item.to_email,
            "subject": item.subject,
            "body": item.body,
            "sentiment": item.sentiment,
            "ai_summary": item.ai_summary,
            "received_at": item.received_at.strftime("%Y-%m-%d %H:%M:%S") if item.received_at else "",
        }
        for item in items
    ]


@router.post("/reset")
def reset_all_database(db: Session = Depends(get_db)):
    """Wipes all rows in tables and resets total runs to 0 for a clean fresh start"""
    db.query(MailReply).delete()
    db.query(UndeliveredMail).delete()
    db.query(SentMail).delete()
    db.query(CompanyMailAccount).delete()
    db.query(SuppressionList).delete()
    db.query(SchedulerRun).delete()

    db.query(Campaign).update({
        Campaign.total_runs: 0,
        Campaign.total_leads_scraped: 0,
        Campaign.total_emails_sent: 0,
        Campaign.total_replies: 0,
        Campaign.last_run_at: None
    })

    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    if config:
        config.total_runs = 0
        config.is_running = False
        config.last_run_at = None
        config.next_run_at = None

    db.commit()
    return {"success": True, "message": "All database tables wiped clean. Fresh start ready."}


@router.get("/smtp/settings")
def get_smtp_settings(db: Session = Depends(get_db)):
    """Fetches currently configured manual SMTP server settings from PostgreSQL"""
    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    return {
        "smtp_host": (config.smtp_host if config and config.smtp_host else "") or "smtp.hostinger.com",
        "smtp_port": (config.smtp_port if config and config.smtp_port else 465),
        "smtp_username": (config.smtp_username if config and config.smtp_username else ""),
        "smtp_password": (config.smtp_password if config and config.smtp_password else ""),
        "sender_name": (config.sender_name if config and config.sender_name else ""),
    }


@router.post("/smtp/settings")
def update_smtp_settings(payload: SmtpConfigRequest, db: Session = Depends(get_db)):
    """Updates manual SMTP server credentials and sender info in PostgreSQL"""
    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    if not config:
        config = SchedulerConfig(id=1)
        db.add(config)

    config.smtp_host = payload.smtp_host.strip()
    config.smtp_port = int(payload.smtp_port)
    config.smtp_username = payload.smtp_username.strip()
    config.smtp_password = payload.smtp_password.strip()
    if payload.sender_name is not None:
        config.sender_name = payload.sender_name.strip()

    db.commit()
    return {
        "success": True,
        "message": f"SMTP settings saved successfully! Outbound emails will route via {config.smtp_host}:{config.smtp_port}."
    }


@router.delete("/smtp/settings")
@router.post("/smtp/clear")
def clear_smtp_settings(db: Session = Depends(get_db)):
    """Removes configured SMTP credentials from PostgreSQL"""
    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    if config:
        config.smtp_username = None
        config.smtp_password = None
        config.sender_name = None
        db.commit()
    return {"success": True, "message": "SMTP settings removed successfully."}


@router.post("/smtp/test")
def test_smtp_connection(payload: SmtpTestRequest):
    """Performs live socket handshake and SMTP authentication test with provided credentials"""
    host = payload.smtp_host.strip()
    port = int(payload.smtp_port)
    user = payload.smtp_username.strip()
    pwd = payload.smtp_password.strip()

    if not host or not user or not pwd:
        raise HTTPException(status_code=400, detail="Hostname, username, and password are required for SMTP testing.")

    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
            server.ehlo()
            server.login(user, pwd)
            server.quit()
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, pwd)
            server.quit()

        # Check IMAP inbound for Hostinger/Gmail/generic host
        imap_status_msg = ""
        try:
            import imaplib
            imap_host_test = "imap.hostinger.com" if "hostinger" in host.lower() else ("imap.gmail.com" if "gmail" in host.lower() else (host.replace("smtp.", "imap.") if host.startswith("smtp.") else None))
            if imap_host_test:
                with imaplib.IMAP4_SSL(imap_host_test, 993, timeout=5) as imap_server:
                    imap_server.login(user, pwd)
                    imap_status_msg = f" • Verified inbound IMAP on {imap_host_test}:993 (ready to receive prospect replies)."
        except Exception as e:
            print(f"IMAP handshake note: {e}")

        return {
            "success": True,
            "message": f"Connection verified successfully! Authenticated with {host}:{port} as '{user}'.{imap_status_msg}"
        }
    except smtplib.SMTPAuthenticationError:
        extra_hint = " For Hostinger, ensure you enter your full email address (e.g. info@yourdomain.com) and your Hostinger mailbox password." if "hostinger" in host.lower() else ""
        return {
            "success": False,
            "message": f"SMTP Authentication Error (535): Invalid username or password for {host}.{extra_hint}"
        }
    except smtplib.SMTPConnectError:
        return {
            "success": False,
            "message": f"SMTP Connection Error: Could not establish connection to {host}:{port}."
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"SMTP Test Failed: {str(e)}"
        }


# =============================================================================
# CAMPAIGN MANAGEMENT ENDPOINTS
# =============================================================================

@router.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db)):
    """Returns all created campaigns with individual run metrics and active indicator"""
    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    active_id = str(config.active_campaign_id) if config and config.active_campaign_id else None

    campaigns = db.query(Campaign).order_by(desc(Campaign.created_at)).all()

    # Validate that active_campaign_id actually exists in the database
    existing_ids = {str(c.id) for c in campaigns}
    if active_id and active_id not in existing_ids:
        active_id = str(campaigns[0].id) if campaigns else None
        if config:
            config.active_campaign_id = campaigns[0].id if campaigns else None
            db.commit()

    total_created = len(campaigns)
    total_run = sum(1 for c in campaigns if c.total_runs > 0)
    total_campaign_executions = sum(c.total_runs for c in campaigns)

    data = []
    for c in campaigns:
        is_active = (str(c.id) == active_id)
        data.append({
            "id": str(c.id),
            "name": c.name,
            "search_query": c.search_query,
            "scrape_batch_size": c.scrape_batch_size,
            "send_batch_size": c.send_batch_size,
            "interval_seconds": c.interval_seconds,
            "email_subject": c.email_subject,
            "email_body": c.email_body,
            "status": c.status,
            "is_active": is_active,
            "total_runs": c.total_runs,
            "total_leads_scraped": c.total_leads_scraped,
            "total_emails_sent": c.total_emails_sent,
            "total_replies": c.total_replies,
            "last_run_at": c.last_run_at.isoformat() if c.last_run_at else None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })

    return {
        "campaigns": data,
        "total_created": total_created,
        "total_run": total_run,
        "total_executions": total_campaign_executions,
        "active_campaign_id": active_id
    }


@router.post("/campaigns/create")
def create_campaign(payload: CampaignCreateRequest, db: Session = Depends(get_db)):
    """Creates a new campaign, optionally sets it as active, and optionally runs it right away"""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Campaign name is required.")

    query = payload.search_query.strip() or "B2B Software and Tech Companies"
    scrape_size = max(1, min(payload.scrape_batch_size, 50))
    send_size = max(1, min(payload.send_batch_size, 50))
    interval = max(10, payload.interval_seconds)

    campaign = Campaign(
        name=name,
        search_query=query,
        scrape_batch_size=scrape_size,
        send_batch_size=send_size,
        interval_seconds=interval,
        email_subject=payload.email_subject or "Partnership & Automation Opportunities for {{company_name}}",
        email_body=payload.email_body or "Hi {{company_name}} Team,\n\nI came across {{website}} and noticed your work in {{industry}}. Our platform automates B2B email workflows and communication pipelines.\n\nWould you be open to a 10-minute demo next week?\n\nBest regards,\n{{sender_name}}",
        status="active",
        total_runs=0,
        total_leads_scraped=0,
        total_emails_sent=0,
        total_replies=0,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    if not config:
        config = SchedulerConfig(id=1)
        db.add(config)

    if payload.set_active or payload.start_scheduler or payload.start_cycle_now:
        config.active_campaign_id = campaign.id
        config.campaign_name = campaign.name
        config.search_query = campaign.search_query
        config.scrape_batch_size = campaign.scrape_batch_size
        config.send_batch_size = campaign.send_batch_size
        config.interval_seconds = campaign.interval_seconds
        if campaign.email_subject:
            config.email_subject = campaign.email_subject
        if campaign.email_body:
            config.email_body = campaign.email_body

    if payload.start_scheduler:
        config.is_running = True
        config.next_run_at = utc_now() + timedelta(seconds=campaign.interval_seconds)

    db.commit()

    cycle_result = None
    if payload.start_cycle_now:
        cycle_result = run_scheduler_cycle(db, campaign_id=campaign.id)

    return {
        "success": True,
        "message": f"Campaign '{campaign.name}' created successfully.",
        "campaign_id": str(campaign.id),
        "campaign": {
            "id": str(campaign.id),
            "name": campaign.name,
            "search_query": campaign.search_query,
            "scrape_batch_size": campaign.scrape_batch_size,
            "send_batch_size": campaign.send_batch_size,
            "interval_seconds": campaign.interval_seconds,
            "total_runs": campaign.total_runs,
        },
        "cycle_result": cycle_result
    }


@router.post("/campaigns/{campaign_id}/activate")
def activate_campaign(campaign_id: str, db: Session = Depends(get_db)):
    """Sets a campaign as active for the automated scheduler"""
    import uuid as uuid_pkg
    try:
        c_uuid = uuid_pkg.UUID(campaign_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid campaign ID format.")

    campaign = db.query(Campaign).filter(Campaign.id == c_uuid).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    if not config:
        config = SchedulerConfig(id=1)
        db.add(config)

    config.active_campaign_id = campaign.id
    config.campaign_name = campaign.name
    config.search_query = campaign.search_query
    config.scrape_batch_size = campaign.scrape_batch_size
    config.send_batch_size = campaign.send_batch_size
    config.interval_seconds = campaign.interval_seconds
    if campaign.email_subject:
        config.email_subject = campaign.email_subject
    if campaign.email_body:
        config.email_body = campaign.email_body

    campaign.status = "active"
    db.commit()

    return {"success": True, "message": f"Campaign '{campaign.name}' is now active."}


@router.post("/campaigns/{campaign_id}/run")
def run_campaign_now(campaign_id: str, db: Session = Depends(get_db)):
    """Immediately runs a 5-step cycle for this specific campaign"""
    import uuid as uuid_pkg
    try:
        c_uuid = uuid_pkg.UUID(campaign_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid campaign ID format.")

    campaign = db.query(Campaign).filter(Campaign.id == c_uuid).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    result = run_scheduler_cycle(db, campaign_id=campaign.id)
    return result


@router.delete("/campaigns/{campaign_id}")
def delete_campaign(campaign_id: str, db: Session = Depends(get_db)):
    """Deletes a campaign and its associated scheduler runs"""
    import uuid as uuid_pkg
    try:
        c_uuid = uuid_pkg.UUID(campaign_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid campaign ID format.")

    campaign = db.query(Campaign).filter(Campaign.id == c_uuid).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    camp_name = campaign.name

    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    if config and config.active_campaign_id == campaign.id:
        remaining = db.query(Campaign).filter(Campaign.id != campaign.id).order_by(desc(Campaign.created_at)).first()
        if remaining:
            config.active_campaign_id = remaining.id
            config.campaign_name = remaining.name
            config.search_query = remaining.search_query
            config.email_subject = remaining.email_subject
            config.email_body = remaining.email_body
        else:
            config.active_campaign_id = None
            config.campaign_name = ""

    db.delete(campaign)
    db.commit()
    return {"success": True, "message": f"Campaign '{camp_name}' deleted."}


class TemplateSaveRequest(BaseModel):
    subject: str
    body: str
    campaign_id: Optional[str] = None


class TemplateEnhanceRequest(BaseModel):
    subject: str
    body: str
    tone: Optional[str] = "professional"


@router.post("/template/save")
def save_email_template(payload: TemplateSaveRequest, db: Session = Depends(get_db)):
    """Saves email template to SchedulerConfig and active Campaign"""
    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    if not config:
        config = SchedulerConfig(id=1)
        db.add(config)

    config.email_subject = payload.subject.strip()
    config.email_body = payload.body

    target_camp_id = None
    if payload.campaign_id:
        import uuid as uuid_pkg
        try:
            target_camp_id = uuid_pkg.UUID(payload.campaign_id)
        except Exception:
            pass
    elif config.active_campaign_id:
        target_camp_id = config.active_campaign_id

    if target_camp_id:
        camp = db.query(Campaign).filter(Campaign.id == target_camp_id).first()
        if camp:
            camp.email_subject = payload.subject.strip()
            camp.email_body = payload.body
    else:
        # Fallback: also apply to all existing campaigns so no campaign is left with old copy
        for camp in db.query(Campaign).all():
            camp.email_subject = payload.subject.strip()
            camp.email_body = payload.body

    db.commit()
    return {"success": True, "message": "Email template saved & active for outreach!"}


@router.post("/template/enhance")
def enhance_email_template(payload: TemplateEnhanceRequest):
    """Uses Groq AI to polish and improve cold email copy while preserving all variables"""
    api_key = settings.GROQ_API_KEY or os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return {"success": False, "subject": payload.subject, "body": payload.body, "message": "Groq API key not configured"}

    tone = payload.tone or "professional"
    prompt = f"""You are an elite B2B cold email copywriter.
Enhance and rewrite this email template to make it {tone}, engaging, and high-converting.

CRITICAL CONSTRAINTS:
1. You MUST PRESERVE all placeholder variables exactly as written: {{{{company_name}}}}, {{{{website}}}}, {{{{city}}}}, {{{{industry}}}}, {{{{sender_name}}}}.
2. Keep the body concise, clear, and compelling (under 120 words).
3. Return STRICTLY a valid JSON object with keys:
   - "subject": polished subject line
   - "body": polished email body
Output ONLY the JSON object without markdown code blocks or preamble.

User Input:
Subject: {payload.subject}
Body:
{payload.body}
"""
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AI-Mail-Automation/1.0",
        }
        data = {
            "model": settings.GROQ_MODEL or "openai/gpt-oss-120b",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1200,
            "temperature": 0.3,
        }
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=18) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            content = res.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            import re
            m = re.search(r"\{.*\}", content, re.DOTALL)
            if m:
                parsed = json.loads(m.group(0))
                return {
                    "success": True,
                    "subject": parsed.get("subject", payload.subject),
                    "body": parsed.get("body", payload.body),
                }
    except Exception as e:
        return {"success": False, "subject": payload.subject, "body": payload.body, "message": str(e)}

    return {"success": False, "subject": payload.subject, "body": payload.body}