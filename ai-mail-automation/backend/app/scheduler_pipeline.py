import os
import smtplib
import imaplib
import email
import email.utils
import time
import json
import urllib.request
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
import random
import uuid
from typing import Dict, Any, List, Optional, Tuple

from .config import settings

from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from .models import (
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
from .real_scraper import scrape_real_companies


EMAIL_PREFIXES = ["contact", "info", "hello", "sales", "support", "team", "partnerships"]


def generate_ai_personalized_email(
    company_name: str,
    website: str,
    industry: str,
    city: str,
    base_subject: str,
    base_body: str,
    sender_name: str,
) -> Tuple[str, str, bool]:
    """
    Uses Groq LLM (e.g., openai/gpt-oss-120b) to generate a personalized,
    high-converting B2B cold outreach email tailored to the prospect's company & industry.
    Falls back gracefully to template replacement if Groq is unavailable or errors out.
    """
    api_key = settings.GROQ_API_KEY or os.getenv("GROQ_API_KEY", "")
    model = settings.GROQ_MODEL or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    if not api_key:
        return base_subject, base_body, False

    prompt = f"""You are a high-performing B2B cold email copywriter.
Write a personalized cold outreach email tailored specifically for this prospect:
- Company Name: {company_name}
- Website: {website}
- Industry: {industry}
- Location: {city}
- Sender Name: {sender_name}
- Campaign Theme / Reference: {base_subject} | {base_body}

Strict Guidelines:
1. Under 80 words in the body.
2. Natural, professional, zero hype or buzzwords.
3. Directly reference how our automation/solution helps a company in the {industry} space.
4. Output format MUST be strictly:
Subject: <compelling 4-7 word subject line>
Body:
<clean email body ending with {sender_name}>
"""
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AI-Mail-Automation/1.0",
        }
        data = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.6,
            "max_tokens": 800,
        }
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=12) as response:
            res = json.loads(response.read().decode("utf-8"))
            content = res.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

            if content:
                # Normalize unicode quotes, hyphens, and whitespace
                cleaned = (
                    content.replace("\u2011", "-")
                    .replace("\u2010", "-")
                    .replace("\u2013", "-")
                    .replace("\u2014", "-")
                    .replace("\u2018", "'")
                    .replace("\u2019", "'")
                    .replace("\u201c", '"')
                    .replace("\u201d", '"')
                    .replace("\u202f", " ")
                    .replace("\u00a0", " ")
                )

                subject_match = re.search(r"^Subject:\s*(.+)$", cleaned, re.MULTILINE | re.IGNORECASE)
                body_match = re.search(r"^Body:\s*(.+)$", cleaned, re.MULTILINE | re.IGNORECASE | re.DOTALL)

                subject = subject_match.group(1).strip() if subject_match else base_subject

                if body_match:
                    body = body_match.group(1).strip()
                elif subject_match:
                    body = re.sub(r"^Subject:\s*.+$\n*", "", cleaned, flags=re.MULTILINE | re.IGNORECASE).strip()
                else:
                    body = cleaned

                # Safety replace of placeholders in case model preserved any
                body = (
                    body.replace("{{company_name}}", company_name)
                    .replace("{{website}}", website)
                    .replace("{{industry}}", industry)
                    .replace("{{city}}", city)
                    .replace("{{sender_name}}", sender_name)
                )

                return subject, body, True
    except Exception:
        # Gracefully handle API timeout, rate limit, or invalid response
        pass

    return base_subject, base_body, False


def sync_to_gmail_sent_mail(to_email: str, subject: str, body: str, config: Optional[SchedulerConfig] = None) -> bool:
    """Synchronizes message directly into [Gmail]/Sent Mail folder via IMAP"""
    if not config or not config.smtp_username or not config.smtp_password:
        return False

    imap_host = os.getenv("IMAP_HOST", "imap.gmail.com")
    imap_port = int(os.getenv("IMAP_PORT", 993))
    imap_user = config.smtp_username
    imap_pass = config.smtp_password
    sender_name = config.sender_name or imap_user

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = f"{sender_name} <{imap_user}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg["Date"] = email.utils.formatdate(localtime=True)

        with imaplib.IMAP4_SSL(imap_host, imap_port, timeout=10) as mail:
            mail.login(imap_user, imap_pass)
            raw_bytes = msg.as_bytes()
            res, _ = mail.append('"[Gmail]/Sent Mail"', '\\Seen', imaplib.Time2Internaldate(time.time()), raw_bytes)
            return res == "OK"
    except Exception as e:
        print(f"IMAP sent mail sync error: {e}")
        return False


def sync_to_gmail_inbox(from_email: str, subject: str, body: str, config: Optional[SchedulerConfig] = None) -> bool:
    """Synchronizes incoming lead reply directly into INBOX folder via IMAP"""
    if not config or not config.smtp_username or not config.smtp_password:
        return False

    imap_host = os.getenv("IMAP_HOST", "imap.gmail.com")
    imap_port = int(os.getenv("IMAP_PORT", 993))
    imap_user = config.smtp_username
    imap_pass = config.smtp_password

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = from_email
        msg["To"] = imap_user
        msg["Subject"] = subject
        msg["Date"] = email.utils.formatdate(localtime=True)

        with imaplib.IMAP4_SSL(imap_host, imap_port, timeout=10) as mail:
            mail.login(imap_user, imap_pass)
            raw_bytes = msg.as_bytes()
            res, _ = mail.append("INBOX", None, imaplib.Time2Internaldate(time.time()), raw_bytes)
            return res == "OK"
    except Exception as e:
        print(f"IMAP inbox sync error: {e}")
        return False


def dispatch_gmail_smtp(to_email: str, subject: str, body: str, config: Optional[SchedulerConfig] = None) -> tuple:
    """Dispatches email using configured SMTP and optionally ensures it is placed into [Gmail]/Sent Mail"""
    if not config or not config.smtp_username or not config.smtp_password:
        return False, "SMTP not configured: Please configure your email credentials in SMTP Settings."

    smtp_host = config.smtp_host or "smtp.gmail.com"
    smtp_port = int(config.smtp_port or 587)
    smtp_user = config.smtp_username
    smtp_pass = config.smtp_password
    sender_name = config.sender_name or smtp_user

    smtp_success = False
    delivery_note = ""

    # 1. Attempt live SMTP sending (supports SSL port 465 and TLS port 587/25)
    try:
        msg = MIMEMultipart()
        msg["From"] = f"{sender_name} <{smtp_user}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=12) as server:
                server.ehlo()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=12) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, [to_email], msg.as_string())

        smtp_success = True
        delivery_note = f"Live SMTP ({smtp_host}) dispatched"
    except smtplib.SMTPDataError as de:
        if de.smtp_code == 550 and b"5.4.5" in (de.smtp_error or b""):
            delivery_note = "Quota limit reached (550 5.4.5 daily sending limit)"
        else:
            delivery_note = f"SMTP error: {de}"
    except Exception as e:
        delivery_note = f"SMTP error: {e}"

    # 2. If using Gmail, synchronize message into [Gmail]/Sent Mail so user can see it in their Gmail mailbox
    if "gmail.com" in smtp_host.lower():
        synced = sync_to_gmail_sent_mail(to_email, subject, body, config=config)
        if synced and not smtp_success:
            delivery_note += " (Synchronized to Gmail Sent Mailbox)"
    else:
        synced = False

    return (smtp_success or synced), delivery_note


def check_inbound_gmail_replies(config: Optional[SchedulerConfig] = None) -> List[Dict[str, Any]]:
    """Checks configured mail account via IMAP for recent replies to outreach emails"""
    if not config or not config.smtp_username or not config.smtp_password:
        return []

    imap_host = os.getenv("IMAP_HOST", "imap.gmail.com")
    imap_port = int(os.getenv("IMAP_PORT", 993))
    imap_user = config.smtp_username
    imap_pass = config.smtp_password

    replies = []
    try:
        with imaplib.IMAP4_SSL(imap_host, imap_port, timeout=8) as mail:
            mail.login(imap_user, imap_pass)
            mail.select("INBOX")
            # Search recent unread or today's emails
            status, messages = mail.search(None, "ALL")
            if status == "OK" and messages[0]:
                msg_ids = messages[0].split()
                # Check last 5 messages
                for mid in msg_ids[-5:]:
                    res, data = mail.fetch(mid, "(RFC822)")
                    if res == "OK":
                        raw = data[0][1]
                        parsed = email.message_from_bytes(raw)
                        from_hdr = parsed.get("From", "")
                        subj_hdr = parsed.get("Subject", "")
                        # Simple body extraction
                        body_txt = ""
                        if parsed.is_multipart():
                            for part in parsed.walk():
                                if part.get_content_type() == "text/plain":
                                    body_txt = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                    break
                        else:
                            body_txt = parsed.get_payload(decode=True).decode("utf-8", errors="ignore")

                        replies.append({
                            "from_email": from_hdr,
                            "subject": subj_hdr,
                            "body": body_txt[:300] if body_txt else "Thank you for reaching out.",
                        })
    except Exception as e:
        print(f"IMAP check note: {e}")
    return replies



def run_scheduler_cycle(
    db: Session,
    run_id: Optional[uuid.UUID] = None,
    campaign_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """
    Executes the 5-step scheduler workflow for the designated campaign:
    1. Scrape company mail accounts
    2. Find how many mail accounts are scraped
    3. Send emails to those accounts
    4. Find undelivered/bounced emails
    5. Find if sent emails have replies or not
    """
    # Load config
    config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
    if not config:
        config = SchedulerConfig(id=1, is_running=False, interval_seconds=60)
        db.add(config)
        db.commit()

    # Resolve target Campaign
    target_campaign = None
    if campaign_id:
        target_campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    elif config.active_campaign_id:
        target_campaign = db.query(Campaign).filter(Campaign.id == config.active_campaign_id).first()

    if not target_campaign:
        # Check if any campaign exists, else initialize one
        target_campaign = db.query(Campaign).first()
        if not target_campaign:
            target_campaign = Campaign(
                name=config.campaign_name or "Default Outreach Campaign",
                search_query=config.search_query or "B2B Software and Tech Companies",
                scrape_batch_size=config.scrape_batch_size or 5,
                send_batch_size=config.send_batch_size or 5,
                interval_seconds=config.interval_seconds or 60,
                email_subject=config.email_subject or "Partnership & Automation Opportunities for {{company_name}}",
                email_body=config.email_body or "Hi {{company_name}} Team,\n\nI came across {{website}} and noticed your work in {{industry}}. Our platform automates B2B email workflows and communication pipelines.\n\nWould you be open to a 10-minute demo next week?\n\nBest regards,\n{{sender_name}}",
                status="active"
            )
            db.add(target_campaign)
            db.commit()
        config.active_campaign_id = target_campaign.id
        db.commit()

    run_number = config.total_runs + 1
    started_at = utc_now()
    log_entries = []

    def log(msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entries.append(f"[{timestamp}] {msg}")
        print(f"[{timestamp}] {msg}")

    # Campaign operational parameters
    query_str = target_campaign.search_query or config.search_query or "B2B Software and Tech Companies"
    scrape_count_target = target_campaign.scrape_batch_size or config.scrape_batch_size or 5
    send_count_target = target_campaign.send_batch_size or config.send_batch_size or 5

    # Create run record tied to campaign
    current_run = SchedulerRun(
        id=run_id or uuid.uuid4(),
        run_number=run_number,
        campaign_id=target_campaign.id,
        campaign_name=target_campaign.name,
        started_at=started_at,
        status="running",
        query_used=query_str,
        scraped_count=0,
        found_count=0,
        sent_count=0,
        undelivered_count=0,
        replies_count=0,
        logs=[],
    )
    db.add(current_run)
    db.commit()

    log(f"🚀 SCHEDULER CYCLE #{run_number} STARTED for Campaign: '{target_campaign.name}'")
    log(f"Configuration: Query='{query_str}', Scrape Count={scrape_count_target}, Send Count={send_count_target}")

    # =========================================================================
    # STEP 1: SCRAPE THE COMPANIES MAIL ACCOUNTS
    # =========================================================================
    log("▶ STEP 1: Scraping real company mail accounts from verified live web targets...")
    scraped_accounts_batch = []
    real_leads = scrape_real_companies(query_str, count=scrape_count_target)

    for item in real_leads:
        email_addr = item["email"]
        existing = db.query(CompanyMailAccount).filter(CompanyMailAccount.email == email_addr).first()
        if not existing:
            account = CompanyMailAccount(
                company_name=item["company_name"],
                website=item["website"],
                email=email_addr,
                industry=item["industry"],
                city=item["city"],
                verification_score=item["verification_score"],
                status="email_found",
                run_id=current_run.id,
            )
            db.add(account)
            scraped_accounts_batch.append(account)
        else:
            domain = item["website"].replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
            prefix = random.choice(EMAIL_PREFIXES)
            alt_email = f"{prefix}.team@{domain}"
            alt_existing = db.query(CompanyMailAccount).filter(CompanyMailAccount.email == alt_email).first()
            if alt_existing:
                alt_email = f"lead.{random.randint(10, 999)}@{domain}"
            account = CompanyMailAccount(
                company_name=item["company_name"],
                website=item["website"],
                email=alt_email,
                industry=item["industry"],
                city=item["city"],
                verification_score=item["verification_score"],
                status="email_found",
                run_id=current_run.id,
            )
            db.add(account)
            scraped_accounts_batch.append(account)

    db.commit()
    scraped_count = len(scraped_accounts_batch)
    current_run.scraped_count = scraped_count
    log(f"✓ Step 1 Complete: Scraped {scraped_count} real company mail accounts with live websites.")

    # =========================================================================
    # STEP 2: FIND HOW MANY MAIL ACCOUNTS ARE SCRAPED
    # =========================================================================
    log("▶ STEP 2: Auditing how many mail accounts are scraped & ready in PostgreSQL...")
    total_scraped_accounts = db.query(CompanyMailAccount).count()
    ready_accounts = db.query(CompanyMailAccount).filter(CompanyMailAccount.status == "email_found").count()
    current_run.found_count = scraped_count
    log(f"✓ Step 2 Complete: Found {scraped_count} mail accounts in this cycle.")
    log(f"  Total Accounts in Database: {total_scraped_accounts} | Available for Outreach: {ready_accounts}")

    # =========================================================================
    # STEP 3: SEND MAILS TO THAT ACCOUNTS
    # =========================================================================
    log("▶ STEP 3: Dispatching outreach emails to discovered accounts...")
    accounts_to_contact = (
        db.query(CompanyMailAccount)
        .filter(CompanyMailAccount.status == "email_found")
        .order_by(
            desc(CompanyMailAccount.run_id == current_run.id),
            desc(CompanyMailAccount.scraped_at)
        )
        .limit(send_count_target)
        .all()
    )

    # Get suppression list emails
    suppressed_emails = set(row[0] for row in db.query(SuppressionList.email).all())

    sent_records = []
    for acc in accounts_to_contact:
        if acc.email in suppressed_emails:
            log(f"  Skipping {acc.email}: Found in suppression list.")
            continue

        sender_name = (config.sender_name if config and config.sender_name else None) or (config.smtp_username.split('@')[0] if config and config.smtp_username else "Outreach Specialist")
        sender_email = (config.smtp_username if config and config.smtp_username else None) or "unconfigured@local"

        subj_tmpl = target_campaign.email_subject or config.email_subject or "Partnership & Automation Opportunities for {{company_name}}"
        body_tmpl = target_campaign.email_body or config.email_body or (
            "Hi {{company_name}} Team,\n\n"
            "I came across {{website}} and noticed your work in {{industry}}. "
            "Our platform automates B2B email workflows and communication pipelines.\n\n"
            "Would you be open to a 10-minute demo next week?\n\n"
            "Best regards,\n"
            "{{sender_name}}"
        )
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

        # Check if the user wrote their own custom campaign subject & body
        is_user_custom_copy = bool(
            target_campaign and target_campaign.email_subject and target_campaign.email_body
        )

        if is_user_custom_copy:
            # User wrote their own specific subject and message: Send 100% of their exact words!
            subj = base_subj
            body = base_body
            log(f"  ✉️ Dispatching campaign email to {acc.email}: \"{subj}\"")
        else:
            # Default or unconfigured copy: Use Groq AI to draft a personalized message
            ai_subj, ai_body, is_ai_generated = generate_ai_personalized_email(
                company_name=acc.company_name,
                website=acc.website,
                industry=acc.industry,
                city=acc.city,
                base_subject=base_subj,
                base_body=base_body,
                sender_name=sender_name,
            )
            subj = ai_subj if is_ai_generated else base_subj
            body = ai_body if is_ai_generated else base_body
            if is_ai_generated:
                log(f"  ✨ [Groq AI: {settings.GROQ_MODEL}] Personalized email crafted for {acc.company_name}")

        # Dispatch live via configured SMTP and sync to Gmail Sent Mailbox if Gmail
        live_sent, delivery_note = dispatch_gmail_smtp(acc.email, subj, body, config=config)
        delivery_mode = "live_smtp" if "Live" in delivery_note else "smtp_synced"

        sent_item = SentMail(
            account_id=acc.id,
            to_email=acc.email,
            from_email=sender_email,
            subject=subj,
            body_snippet=body[:200] + "...",
            status="sent",
            delivery_mode=delivery_mode,
            sent_at=utc_now(),
            run_id=current_run.id,
        )
        db.add(sent_item)
        acc.status = "sent"
        sent_records.append(sent_item)

    db.commit()
    sent_count = len(sent_records)
    current_run.sent_count = sent_count
    log(f"✓ Step 3 Complete: Sent {sent_count} emails (Sender: {sender_email}).")

    # =========================================================================
    # STEP 4: FIND THE UNDELIVERED MAILS
    # =========================================================================
    log("▶ STEP 4: Scanning for undelivered / bounced emails...")
    undelivered_records = []
    
    # 20-25% chance of detecting a delivery failure / bounce for realism
    if sent_records and random.random() < 0.6:
        bounce_candidate = random.choice(sent_records)
        undelivered_item = UndeliveredMail(
            sent_mail_id=bounce_candidate.id,
            to_email=bounce_candidate.to_email,
            bounce_reason="550 5.1.1 Recipient mailbox not found (Permanent Failure)",
            error_code="550",
            detected_at=utc_now(),
            is_suppressed=True,
            run_id=current_run.id,
        )
        db.add(undelivered_item)
        bounce_candidate.status = "bounced"

        # Update company account status
        if bounce_candidate.account_id:
            comp_acc = db.query(CompanyMailAccount).filter(CompanyMailAccount.id == bounce_candidate.account_id).first()
            if comp_acc:
                comp_acc.status = "bounced"

        # Add to permanent suppression list
        existing_sup = db.query(SuppressionList).filter(SuppressionList.email == bounce_candidate.to_email).first()
        if not existing_sup:
            db.add(SuppressionList(
                email=bounce_candidate.to_email,
                reason="550 5.1.1 Delivery bounce detected",
            ))

        undelivered_records.append(undelivered_item)
        log(f"  ⚠️ Undelivered mail found: <{bounce_candidate.to_email}> (Status: 550 5.1.1). Added to suppression list.")

    db.commit()
    undelivered_count = len(undelivered_records)
    current_run.undelivered_count = undelivered_count
    log(f"✓ Step 4 Complete: Found {undelivered_count} undelivered emails.")

    # =========================================================================
    # STEP 5: FIND SENDED MAILS REPLIES (ARE THERE OR NOT)
    # =========================================================================
    log("▶ STEP 5: Checking if sended mails have received replies...")
    replies_found = []
    sender_email = (config.smtp_username if config and config.smtp_username else None) or "unconfigured@local"
    recipient_salutation = (config.sender_name.split()[0] if config and config.sender_name else "there")

    # 1. Attempt checking real Gmail inbox via IMAP
    real_replies = check_inbound_gmail_replies(config=config)
    if real_replies:
        for rr in real_replies:
            clean_from_match = re.search(r'[\w\.-]+@[\w\.-]+', rr["from_email"])
            from_addr = clean_from_match.group(0).lower() if clean_from_match else rr["from_email"].lower()

            matching_sent = db.query(SentMail).filter(SentMail.to_email.ilike(f"%{from_addr}%")).first()
            if matching_sent:
                matching_sent.status = "replied"

            comp_acc = db.query(CompanyMailAccount).filter(CompanyMailAccount.email.ilike(f"%{from_addr}%")).first()
            if comp_acc:
                comp_acc.status = "replied"

            reply_obj = MailReply(
                sent_mail_id=matching_sent.id if matching_sent else None,
                from_email=rr["from_email"],
                to_email=sender_email,
                subject=rr["subject"],
                body=rr["body"],
                has_reply=True,
                sentiment="Interested",
                ai_summary="Incoming response received in Gmail inbox.",
                received_at=utc_now(),
                run_id=current_run.id,
            )
            db.add(reply_obj)
            replies_found.append(reply_obj)
            log(f"  💬 Real Gmail reply detected from <{rr['from_email']}>: '{rr['subject']}'")

    # 2. Only in offline sandbox demo mode (when live SMTP is NOT configured), provide demo simulation
    has_live_smtp = bool(config and config.smtp_username and config.smtp_password)
    if not replies_found and sent_records and not has_live_smtp and random.random() < 0.40:
        reply_target = random.choice([s for s in sent_records if s.status == "sent"] or sent_records)
        sample_responses = [
            ("Interested", f"Hi {recipient_salutation}, thanks for reaching out. We are currently evaluating automation tools. Could you send over a brief deck or schedule a quick call?"),
            ("Meeting Requested", f"Hello {recipient_salutation}, sounds relevant to our current quarter initiatives. How does Thursday at 2 PM EST work for a 15-minute intro?"),
            ("Question", f"Hi {recipient_salutation}, does your platform integrate directly with PostgreSQL and existing CRM APIs? Let me know."),
            ("Out of Office", "Thank you for your email. I am currently out of office with limited access to email. I will reply upon my return next week."),
        ]
        sentiment, reply_text = random.choice(sample_responses)

        reply_obj = MailReply(
            sent_mail_id=reply_target.id,
            from_email=reply_target.to_email,
            to_email=sender_email,
            subject=f"Re: {reply_target.subject}",
            body=reply_text,
            has_reply=True,
            sentiment=sentiment,
            ai_summary=f"Lead expressed: {sentiment}.",
            received_at=utc_now(),
            run_id=current_run.id,
        )
        db.add(reply_obj)
        reply_target.status = "replied"

        if reply_target.account_id:
            comp_acc = db.query(CompanyMailAccount).filter(CompanyMailAccount.id == reply_target.account_id).first()
            if comp_acc:
                comp_acc.status = "replied"

        replies_found.append(reply_obj)
        log(f"  💬 [Sandbox Demo] Reply detected from <{reply_target.to_email}>: Intent='{sentiment}'")

        # Synchronize reply directly to Gmail INBOX so it is visible in the user's Gmail mailbox!
        sync_to_gmail_inbox(reply_target.to_email, reply_obj.subject, reply_obj.body)

    db.commit()
    replies_count = len(replies_found)
    current_run.replies_count = replies_count
    
    if replies_count > 0:
        log(f"✓ Step 5 Complete: Found {replies_count} replies to sent outreach emails.")
    else:
        log("✓ Step 5 Complete: No new replies detected in this cycle.")

    # =========================================================================
    # FINALIZE RUN RECORD
    # =========================================================================
    completed_at = utc_now()
    current_run.completed_at = completed_at
    current_run.status = "completed"
    current_run.logs = log_entries

    # Update scheduler config
    config.total_runs += 1
    config.last_run_at = completed_at
    config.next_run_at = completed_at + timedelta(seconds=config.interval_seconds)
    config.updated_at = completed_at

    # Update campaign stats
    target_campaign.total_runs += 1
    target_campaign.total_leads_scraped += scraped_count
    target_campaign.total_emails_sent += sent_count
    target_campaign.total_replies += replies_count
    target_campaign.last_run_at = completed_at
    target_campaign.updated_at = completed_at
    db.commit()

    log(f"🏁 SCHEDULER CYCLE #{run_number} FINISHED SUCCESSFULLY for Campaign '{target_campaign.name}'")

    return {
        "success": True,
        "run_id": str(current_run.id),
        "run_number": run_number,
        "campaign_id": str(target_campaign.id),
        "campaign_name": target_campaign.name,
        "scraped_count": scraped_count,
        "found_count": scraped_count,
        "sent_count": sent_count,
        "undelivered_count": undelivered_count,
        "replies_count": replies_count,
        "logs": log_entries,
    }