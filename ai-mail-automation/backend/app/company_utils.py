import re
from typing import Set, Tuple, Optional
from urllib.parse import urlparse
from sqlalchemy.orm import Session


def extract_domain(url_or_email: Optional[str]) -> str:
    """
    Extracts a normalized, clean domain from a URL or email address.
    Examples:
        'sales@lloydspharmacy.com' -> 'lloydspharmacy.com'
        'https://www.boots.com/store' -> 'boots.com'
        'http://sub.domain.co.uk' -> 'domain.co.uk'
    """
    if not url_or_email:
        return ""

    text = str(url_or_email).strip().lower()

    # Handle email addresses
    if "@" in text:
        text = text.split("@")[-1]

    # Handle URLs with protocols
    if "://" in text:
        try:
            parsed = urlparse(text)
            text = parsed.netloc or parsed.path
        except Exception:
            text = text.split("://")[-1]

    # Strip paths, queries, ports
    text = text.split("/")[0].split("?")[0].split("#")[0].split(":")[0]

    # Strip leading www.
    if text.startswith("www."):
        text = text[4:]

    return text.strip()


def normalize_company_name(name: Optional[str]) -> str:
    """
    Normalizes a company name for duplicate detection.
    Strips common legal designations (Ltd, Inc, LLC, Corp, Co, etc.) and punctuation.
    Examples:
        'Boots UK Ltd' -> 'bootsuk'
        'Boots UK' -> 'bootsuk'
        'LloydsPharmacy' -> 'lloydspharmacy'
        'Tata 1mg' -> 'tata1mg'
    """
    if not name:
        return ""

    cleaned = str(name).strip().lower()

    # Common corporate entity suffixes
    suffixes = [
        " private limited", " pvt ltd", " pvt. ltd.", " limited", " ltd.", " ltd",
        " incorporated", " inc.", " inc", " corporation", " corp.", " corp",
        " llc", " l.l.c.", " llp", " l.l.p.", " gmbh", " plc", " s.a.", " sa",
        " co.", " co", " company", " group", " enterprises"
    ]

    for suf in suffixes:
        if cleaned.endswith(suf):
            cleaned = cleaned[:-len(suf)].strip()
            break

    # Remove non-alphanumeric characters
    cleaned = re.sub(r'[^a-z0-9]', '', cleaned)
    return cleaned


def get_already_contacted_companies(db: Session, user_id: Optional[object] = None) -> Tuple[Set[str], Set[str], Set[str]]:
    """
    Retrieves sets of all emails, domains, and normalized company names
    that have already received an email across history (isolated by user if user_id is provided).

    Returns:
        (contacted_emails, contacted_domains, contacted_company_names)
    """
    from .models import SentMail, CompanyMailAccount

    contacted_emails: Set[str] = set()
    contacted_domains: Set[str] = set()
    contacted_company_names: Set[str] = set()

    # 1. From SentMail table (actual sent messages)
    try:
        sent_q = db.query(SentMail)
        if user_id is not None:
            sent_q = sent_q.filter(SentMail.user_id == user_id)
        sent_records = sent_q.all()
        for sm in sent_records:
            if sm.to_email:
                em = sm.to_email.strip().lower()
                contacted_emails.add(em)
                dom = extract_domain(em)
                if dom:
                    contacted_domains.add(dom)
            if sm.company_account:
                if sm.company_account.website:
                    dom = extract_domain(sm.company_account.website)
                    if dom:
                        contacted_domains.add(dom)
                if sm.company_account.company_name:
                    norm = normalize_company_name(sm.company_account.company_name)
                    if norm:
                        contacted_company_names.add(norm)
    except Exception:
        pass

    # 2. From CompanyMailAccount where status indicates prior contact
    try:
        acc_q = db.query(CompanyMailAccount).filter(
            CompanyMailAccount.status.in_(["sent", "bounced", "replied", "already_contacted"])
        )
        if user_id is not None:
            acc_q = acc_q.filter(CompanyMailAccount.user_id == user_id)
        contacted_accs = acc_q.all()
        for acc in contacted_accs:
            if acc.email:
                em = acc.email.strip().lower()
                contacted_emails.add(em)
                dom = extract_domain(em)
                if dom:
                    contacted_domains.add(dom)
            if acc.website:
                dom = extract_domain(acc.website)
                if dom:
                    contacted_domains.add(dom)
            if acc.company_name:
                norm = normalize_company_name(acc.company_name)
                if norm:
                    contacted_company_names.add(norm)
    except Exception:
        pass

    return contacted_emails, contacted_domains, contacted_company_names


def is_company_already_contacted(
    company_name: Optional[str],
    website_or_domain: Optional[str],
    email: Optional[str],
    contacted_emails: Set[str],
    contacted_domains: Set[str],
    contacted_company_names: Set[str],
) -> bool:
    """
    Checks if a company has already been contacted using email, domain, or company name.
    Strictly prevents sending more than 1 email to any company.
    """
    if email and email.strip().lower() in contacted_emails:
        return True

    domain = extract_domain(website_or_domain) or extract_domain(email)
    if domain and domain in contacted_domains:
        return True

    norm_name = normalize_company_name(company_name)
    if norm_name and norm_name in contacted_company_names:
        return True

    return False
