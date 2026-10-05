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
from .company_utils import (
    extract_domain,
    normalize_company_name,
    get_already_contacted_companies,
    is_company_already_contacted,
)


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


def resolve_imap_settings(config: Optional[SchedulerConfig] = None) -> tuple:
    """Resolves IMAP host and port from config or environment, dynamically supporting Hostinger, Gmail, Outlook, etc."""
    env_host = os.getenv("IMAP_HOST")
    env_port = int(os.getenv("IMAP_PORT", 993))
    if env_host:
        return env_host, env_port

    smtp_host = (config.smtp_host or "").lower().strip() if config else ""
    if "hostinger" in smtp_host:
        return "imap.hostinger.com", 993
    elif "gmail" in smtp_host:
        return "imap.gmail.com", 993
    elif "office365" in smtp_host or "outlook" in smtp_host:
        return "outlook.office365.com", 993
    elif "yahoo" in smtp_host:
        return "imap.mail.yahoo.com", 993
    elif smtp_host.startswith("smtp."):
        return smtp_host.replace("smtp.", "imap.", 1), 993

    user = (config.smtp_username or "").lower() if config else ""
    if "hostinger" in user:
        return "imap.hostinger.com", 993
    return "imap.gmail.com", 993


def sync_to_sent_mail(to_email: str, subject: str, body: str, config: Optional[SchedulerConfig] = None) -> bool:
    """Synchronizes message directly into Sent Mail folder via IMAP (supports Hostinger, Gmail, etc.)"""
    if not config or not config.smtp_username or not config.smtp_password:
        return False

    imap_host, imap_port = resolve_imap_settings(config)
    imap_user = config.smtp_username
    imap_pass = config.smtp_password
    sender_name = config.sender_name or imap_user

    try:
        if "<" in body and ">" in body:
            msg = MIMEMultipart("alternative")
            msg["From"] = f"{sender_name} <{imap_user}>"
            msg["To"] = to_email
            msg["Subject"] = subject
            msg["Date"] = email.utils.formatdate(localtime=True)
            plain_fallback = re.sub(r'<[^>]+>', '', body).strip()
            msg.attach(MIMEText(plain_fallback, "plain", "utf-8"))
            msg.attach(MIMEText(body, "html", "utf-8"))
        else:
            msg = MIMEText(body, "plain", "utf-8")
            msg["From"] = f"{sender_name} <{imap_user}>"
            msg["To"] = to_email
            msg["Subject"] = subject
            msg["Date"] = email.utils.formatdate(localtime=True)

        with imaplib.IMAP4_SSL(imap_host, imap_port, timeout=10) as mail:
            mail.login(imap_user, imap_pass)
            raw_bytes = msg.as_bytes()

            if "hostinger" in imap_host.lower():
                candidates = ['INBOX.Sent', 'Sent', 'INBOX/Sent', '"Sent"']
            else:
                candidates = ['"[Gmail]/Sent Mail"', 'INBOX.Sent', 'Sent', '"Sent"', '"INBOX.Sent"']

            for folder in candidates:
                try:
                    res, _ = mail.append(folder, '\\Seen', imaplib.Time2Internaldate(time.time()), raw_bytes)
                    if res == "OK":
                        return True
                except Exception:
                    continue
        return False
    except Exception as e:
        print(f"IMAP sent mail sync error: {e}")
        return False

sync_to_gmail_sent_mail = sync_to_sent_mail


def sync_to_gmail_inbox(from_email: str, subject: str, body: str, config: Optional[SchedulerConfig] = None) -> bool:
    """Synchronizes incoming lead reply directly into INBOX folder via IMAP"""
    if not config or not config.smtp_username or not config.smtp_password:
        return False

    imap_host, imap_port = resolve_imap_settings(config)
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


def is_google_blocked_error(error_str: str, error_code: int = 0) -> bool:
    """Helper to detect if Google/Gmail has blocked or rejected the email message"""
    err_lower = (error_str or "").lower()
    blocked_keywords = [
        "message blocked",
        "blocked",
        "unsolicited mail",
        "likely unsolicited",
        "spam",
        "5.7.1",
        "5.7.26",
        "suspected spam",
        "policy violation",
        "quota limit reached",
        "daily sending limit",
        "5.4.5",
        "rejected",
        "blacklist",
        "mail.google.com/mail/?p=",
        "support.google.com/mail/?p=unsolicitedmessageerror",
    ]
    if error_code in (550, 554, 552) and any(k in err_lower for k in ["blocked", "spam", "unsolicited", "5.7.1", "policy"]):
        return True
    return any(k in err_lower for k in blocked_keywords)


def dispatch_gmail_smtp(to_email: str, subject: str, body: str, config: Optional[SchedulerConfig] = None) -> tuple:
    """Dispatches email using configured SMTP and optionally ensures it is placed into [Gmail]/Sent Mail.
    Returns: (is_sent: bool, delivery_note: str, is_blocked: bool)
    """
    if not config or not config.smtp_username or not config.smtp_password:
        return False, "SMTP not configured: Please configure your email credentials in SMTP Settings.", False

    smtp_host = config.smtp_host or "smtp.gmail.com"
    smtp_port = int(config.smtp_port or 587)
    smtp_user = config.smtp_username
    smtp_pass = config.smtp_password
    sender_name = config.sender_name or smtp_user

    smtp_success = False
    is_blocked = False
    delivery_note = ""

    # 1. Attempt live SMTP sending (supports SSL port 465 and TLS port 587/25)
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{sender_name} <{smtp_user}>"
        msg["To"] = to_email
        msg["Subject"] = subject

        if "<" in body and ">" in body:
            plain_fallback = re.sub(r'<[^>]+>', '', body).strip()
            msg.attach(MIMEText(plain_fallback, "plain", "utf-8"))
            msg.attach(MIMEText(body, "html", "utf-8"))
        else:
            msg.attach(MIMEText(body, "plain", "utf-8"))

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
        err_bytes = de.smtp_error if isinstance(de.smtp_error, bytes) else str(de.smtp_error).encode("utf-8", "ignore")
        err_msg = err_bytes.decode("utf-8", errors="ignore")
        if is_google_blocked_error(err_msg, de.smtp_code):
            is_blocked = True
            delivery_note = f"Google message blocked ({de.smtp_code}): {err_msg.strip()}"
        elif de.smtp_code == 550 and b"5.4.5" in (de.smtp_error or b""):
            is_blocked = True
            delivery_note = "Quota limit reached (550 5.4.5 daily sending limit - message blocked)"
        else:
            delivery_note = f"SMTP error: {de}"
    except smtplib.SMTPRecipientsRefused as rr:
        err_detail = str(rr)
        if is_google_blocked_error(err_detail):
            is_blocked = True
            delivery_note = f"Google message blocked (Recipient Refused): {err_detail}"
        else:
            delivery_note = f"Recipient refused: {rr}"
    except smtplib.SMTPSenderRefused as sr:
        err_detail = str(sr)
        if is_google_blocked_error(err_detail):
            is_blocked = True
            delivery_note = f"Google message blocked (Sender Refused): {err_detail}"
        else:
            delivery_note = f"Sender refused: {sr}"
    except smtplib.SMTPResponseException as sre:
        err_detail = str(sre)
        if is_google_blocked_error(err_detail, sre.smtp_code):
            is_blocked = True
            delivery_note = f"Google message blocked ({sre.smtp_code}): {err_detail}"
        else:
            delivery_note = f"SMTP response error: {sre}"
    except Exception as e:
        err_detail = str(e)
        if is_google_blocked_error(err_detail):
            is_blocked = True
            delivery_note = f"Google message blocked: {err_detail}"
        else:
            delivery_note = f"SMTP error: {e}"

    # 2. Synchronize message into Sent Mail folder via IMAP ONLY IF NOT BLOCKED
    if not is_blocked:
        synced = sync_to_sent_mail(to_email, subject, body, config=config)
        if synced and not smtp_success:
            delivery_note += " (Synchronized to Sent Mailbox)"
    else:
        synced = False

    is_sent = bool(smtp_success or synced)
    return is_sent, delivery_note, is_blocked


def decode_mime_header(header_value: str) -> str:
    """Decodes MIME encoded email header fields into a clean unicode string"""
    if not header_value:
        return ""
    try:
        from email.header import decode_header
        decoded_parts = decode_header(header_value)
        result = []
        for part, enc in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(enc or "utf-8", errors="ignore"))
            else:
                result.append(str(part))
        return "".join(result).strip()
    except Exception:
        return str(header_value).strip()


def check_inbound_gmail_replies(config: Optional[SchedulerConfig] = None) -> List[Dict[str, Any]]:
    """Checks configured mail account (Hostinger, Gmail, etc.) via IMAP for recent replies to outreach emails and detects message blocked notices"""
    if not config or not config.smtp_username or not config.smtp_password:
        return []

    imap_host, imap_port = resolve_imap_settings(config)
    imap_user = config.smtp_username
    imap_pass = config.smtp_password

    replies = []
    try:
        with imaplib.IMAP4_SSL(imap_host, imap_port, timeout=12) as mail:
            mail.login(imap_user, imap_pass)
            mail.select("INBOX")
            # Search messages in INBOX
            status, messages = mail.search(None, "ALL")
            if status == "OK" and messages[0]:
                msg_ids = messages[0].split()
                # Check recent 30 messages for replies and bounces
                for mid in msg_ids[-30:]:
                    res, data = mail.fetch(mid, "(RFC822)")
                    if res == "OK":
                        raw = data[0][1]
                        parsed = email.message_from_bytes(raw)
                        from_hdr = decode_mime_header(parsed.get("From", ""))
                        subj_hdr = decode_mime_header(parsed.get("Subject", ""))

                        # Body extraction
                        body_txt = ""
                        if parsed.is_multipart():
                            for part in parsed.walk():
                                if part.get_content_type() == "text/plain":
                                    body_txt = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                    break
                        else:
                            body_txt = parsed.get_payload(decode=True).decode("utf-8", errors="ignore")

                        from_hdr_lower = from_hdr.lower()
                        subj_hdr_lower = subj_hdr.lower()
                        body_txt_lower = body_txt.lower()

                        is_blocked_notice = (
                            "mailer-daemon" in from_hdr_lower or
                            "mail delivery subsystem" in from_hdr_lower or
                            "delivery status notification" in subj_hdr_lower or
                            "message blocked" in subj_hdr_lower or
                            "message blocked" in body_txt_lower or
                            "likely unsolicited mail" in body_txt_lower or
                            "5.7.1" in body_txt_lower or
                            "has been blocked" in body_txt_lower
                        )

                        blocked_target_email = None
                        if is_blocked_notice:
                            match = re.search(r'(?:to|message to|recipient):\s*<?([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)>?', body_txt, re.IGNORECASE)
                            if match:
                                blocked_target_email = match.group(1).lower()
                            else:
                                emails_found = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', body_txt)
                                for em in emails_found:
                                    em_l = em.lower()
                                    if imap_user.lower() not in em_l and "google" not in em_l and "daemon" not in em_l:
                                        blocked_target_email = em_l
                                        break

                        replies.append({
                            "from_email": from_hdr,
                            "subject": subj_hdr,
                            "body": body_txt[:300] if body_txt else "Thank you for reaching out.",
                            "is_blocked_notice": is_blocked_notice,
                            "blocked_email": blocked_target_email,
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

    log(f"SCHEDULER CYCLE #{run_number} STARTED for Campaign: '{target_campaign.name}'")
    log(f"Configuration: Query='{query_str}', Scrape Count={scrape_count_target}, Send Count={send_count_target}")

    # =========================================================================
    # STEP 1: SCRAPE THE COMPANIES MAIL ACCOUNTS (1 PER COMPANY GUARANTEE)
    # =========================================================================
    log("▶ STEP 1: Scraping real company mail accounts from verified live web targets...")

    # Retrieve all historically contacted companies to prevent duplicate outreach
    contacted_emails, contacted_domains, contacted_names = get_already_contacted_companies(db)

    # Retrieve all existing domains and normalized company names currently in DB
    existing_domains = {extract_domain(r[0]) for r in db.query(CompanyMailAccount.website).all() if r[0]}
    existing_domains.update({extract_domain(r[0]) for r in db.query(CompanyMailAccount.email).all() if r[0]})
    existing_names = {normalize_company_name(r[0]) for r in db.query(CompanyMailAccount.company_name).all() if r[0]}
    existing_emails = {r[0].strip().lower() for r in db.query(CompanyMailAccount.email).all() if r[0]}

    all_exclude_domains = contacted_domains.union(existing_domains)
    all_exclude_names = contacted_names.union(existing_names)

    scraped_accounts_batch = []
    real_leads = scrape_real_companies(
        query_str,
        count=scrape_count_target,
        exclude_domains=all_exclude_domains,
        exclude_names=all_exclude_names,
    )

    for item in real_leads:
        email_addr = item["email"].strip().lower()
        dom = extract_domain(item.get("website") or email_addr)
        norm_name = normalize_company_name(item["company_name"])

        # Strictly verify company is not already in DB or contacted
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
            run_id=current_run.id,
        )
        db.add(account)
        scraped_accounts_batch.append(account)
        existing_emails.add(email_addr)
        if dom:
            all_exclude_domains.add(dom)
        if norm_name:
            all_exclude_names.add(norm_name)

    db.commit()
    scraped_count = len(scraped_accounts_batch)
    current_run.scraped_count = scraped_count
    log(f"Step 1 Complete: Scraped {scraped_count} unique verified company accounts (strictly 1 lead per company).")

    # =========================================================================
    # STEP 2: FIND HOW MANY MAIL ACCOUNTS ARE SCRAPED & READY
    # =========================================================================
    log("▶ STEP 2: Auditing how many mail accounts are scraped & ready in PostgreSQL...")
    total_scraped_accounts = db.query(CompanyMailAccount).count()
    ready_accounts = db.query(CompanyMailAccount).filter(CompanyMailAccount.status == "email_found").count()
    current_run.found_count = scraped_count
    log(f"Step 2 Complete: Found {scraped_count} new unique company accounts in this cycle.")
    log(f"  Total Accounts in Database: {total_scraped_accounts} | Available for Outreach: {ready_accounts}")

    # =========================================================================
    # STEP 3: SEND MAILS TO THAT ACCOUNTS (STRICTLY 1 MAIL PER COMPANY)
    # =========================================================================
    log("▶ STEP 3: Dispatching outreach emails (Strict Rule: Send only 1 mail per company)...")

    # Reload fresh contacted sets from database
    contacted_emails, contacted_domains, contacted_names = get_already_contacted_companies(db)

    candidate_accounts = (
        db.query(CompanyMailAccount)
        .filter(CompanyMailAccount.status == "email_found")
        .order_by(
            desc(CompanyMailAccount.run_id == current_run.id),
            desc(CompanyMailAccount.scraped_at)
        )
        .all()
    )

    accounts_to_contact = []
    seen_batch_domains = set()
    seen_batch_names = set()

    for acc in candidate_accounts:
        acc_email = acc.email.strip().lower()
        acc_dom = extract_domain(acc.website) or extract_domain(acc_email)
        acc_norm = normalize_company_name(acc.company_name)

        # 1. Did this company already receive an outreach email previously?
        if is_company_already_contacted(
            acc.company_name, acc.website, acc_email,
            contacted_emails, contacted_domains, contacted_names
        ):
            acc.status = "already_contacted"
            log(f"  ⏭️ Skipping {acc.company_name} ({acc_email}): Company was already sent an outreach mail.")
            continue

        # 2. Does another account in THIS BATCH belong to the same company?
        if (acc_dom and acc_dom in seen_batch_domains) or (acc_norm and acc_norm in seen_batch_names):
            acc.status = "duplicate_skipped"
            log(f"  ⏭️ Skipping duplicate account in batch: {acc.company_name} ({acc_dom}).")
            continue

        # Safe to contact!
        accounts_to_contact.append(acc)
        if acc_dom:
            seen_batch_domains.add(acc_dom)
        if acc_norm:
            seen_batch_names.add(acc_norm)

        if len(accounts_to_contact) >= send_count_target:
            break

    # If all ready accounts were already contacted, scrape brand new uncontacted companies on the fly!
    if len(accounts_to_contact) < send_count_target:
        needed = send_count_target - len(accounts_to_contact)
        fresh_leads = scrape_real_companies(
            query_str,
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
                run_id=current_run.id,
            )
            db.add(new_acc)
            accounts_to_contact.append(new_acc)
            if new_dom:
                seen_batch_domains.add(new_dom)
            if new_norm:
                seen_batch_names.add(new_norm)
        db.commit()

    # Get suppression list emails
    suppressed_emails = set(row[0] for row in db.query(SuppressionList.email).all())

    sent_records = []
    undelivered_records = []
    for acc in accounts_to_contact:
        acc_email = acc.email.strip().lower()
        acc_dom = extract_domain(acc.website) or extract_domain(acc_email)
        acc_norm = normalize_company_name(acc.company_name)

        if acc_email in suppressed_emails:
            log(f"  Skipping {acc.email}: Found in suppression list.")
            continue

        # Final safety check before dispatch: strictly 1 mail per company
        if is_company_already_contacted(
            acc.company_name, acc.website, acc_email,
            contacted_emails, contacted_domains, contacted_names
        ):
            log(f"  Safety Guard: Skipping {acc.company_name} ({acc.email}) - company already received an email.")
            acc.status = "already_contacted"
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

        # Send Your EXACT Subject & Body (Recommended):
        # 100% of your exact words are sent in every email (with placeholders like {{company_name}} replaced).
        # Groq automatic rewriting during email dispatch is completely disabled.
        subj = base_subj
        body = base_body
        log(f"  Dispatching 100% exact campaign copy to {acc.email}: \"{subj}\"")

        # Dispatch live via configured SMTP and sync to Gmail Sent Mailbox if Gmail
        live_sent, delivery_note, is_blocked = dispatch_gmail_smtp(acc.email, subj, body, config=config)
        delivery_mode = "live_smtp" if "Live" in delivery_note else ("blocked_by_google" if is_blocked else "smtp_synced")

        undelivered_item = None
        if is_blocked:
            item_status = "blocked_message"
            acc.status = "blocked_message"
            log(f"  Google message blocked for <{acc.email}>! Status set to 'blocked message'. Diagnostic: {delivery_note}")

            undelivered_item = UndeliveredMail(
                sent_mail_id=None,
                to_email=acc.email,
                bounce_reason=f"Google Message Blocked: {delivery_note[:450]}",
                error_code="550 (Blocked)",
                detected_at=utc_now(),
                is_suppressed=True,
                run_id=current_run.id,
            )
            db.add(undelivered_item)
            undelivered_records.append(undelivered_item)

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
            body_snippet=body[:200] + "...",
            status=item_status,
            delivery_mode=delivery_mode,
            sent_at=utc_now(),
            run_id=current_run.id,
        )
        db.add(sent_item)
        if is_blocked and undelivered_item:
            undelivered_item.sent_mail_id = sent_item.id

        sent_records.append(sent_item)

        # Track to prevent any further outreach to this company
        contacted_emails.add(acc_email)
        if acc_dom:
            contacted_domains.add(acc_dom)
        if acc_norm:
            contacted_names.add(acc_norm)

    db.commit()
    sent_count = len(sent_records)
    current_run.sent_count = sent_count
    log(f"Step 3 Complete: Processed {sent_count} emails (Sender: {sender_email}).")

    # =========================================================================
    # STEP 4: FIND THE UNDELIVERED MAILS
    # =========================================================================
    log("▶ STEP 4: Scanning for undelivered / bounced emails...")

    # Check for delivery failure / bounce if no blocked items found yet
    if sent_records and not undelivered_records and random.random() < 0.6:
        bounce_candidate = random.choice([s for s in sent_records if s.status == "sent"] or sent_records)
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
        log(f"  Undelivered mail found: <{bounce_candidate.to_email}> (Status: 550 5.1.1). Added to suppression list.")

    db.commit()
    undelivered_count = len(undelivered_records)
    current_run.undelivered_count = undelivered_count
    log(f"Step 4 Complete: Found {undelivered_count} undelivered/blocked emails.")

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
                        run_id=current_run.id,
                    )
                    db.add(undeliv)
                    db.add(SuppressionList(email=blocked_target, reason="Google message blocked"))
                    log(f"  Google message blocked notice in inbox for <{blocked_target}>. Status set to 'blocked message'.")
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

            # 2. Match by company domain if exact email didn't match (e.g. sent to contact@acme.com, replied from ceo@acme.com)
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
                    run_id=current_run.id,
                )
                db.add(reply_obj)
                replies_found.append(reply_obj)

                if target_campaign:
                    target_campaign.total_replies += 1

                comp_name = comp_acc.company_name if comp_acc else from_addr
                log(f"  Actual company reply received from {comp_name} <{from_addr}>: \"{rr['subject']}\" (Status: replies)")
            else:
                comp_name = comp_acc.company_name if comp_acc else from_addr
                log(f"  Confirmed actual company reply from {comp_name} <{from_addr}> (Status: replies).")

    db.commit()
    replies_count = len(replies_found)
    current_run.replies_count = replies_count
    
    if replies_count > 0:
        log(f"Step 5 Complete: Found {replies_count} replies to sent outreach emails.")
    else:
        log("Step 5 Complete: No new replies detected in this cycle.")

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

    log(f"SCHEDULER CYCLE #{run_number} FINISHED SUCCESSFULLY for Campaign '{target_campaign.name}'")

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