import re
import time
import logging
from collections import defaultdict
from typing import Tuple, List, Optional
from config.settings import AUTHORIZED_WHATSAPP_NUMBER

log = logging.getLogger(__name__)

# ── Prompt Injection Defense ───────────────────────────────────────────────────
INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+)?previous\s+instructions",
    r"you\s+are\s+now\s+",
    r"forget\s+(?:everything|all|your\s+rules)",
    r"system\s*:\s*",
    r"<\|im_start\|>",
    r"\[INST\]",
    r"```\s*system",
    r"act\s+as\s+(?:a\s+)?(?:different|new)",
    r"new\s+instruction",
    r"override\s+(?:your|the|all)",
    r"jailbreak",
    r"DAN\s+mode",
]

# ── Rate Limiting State (In-Memory Sliding Windows) ─────────────────────────────
_MESSAGE_TIMESTAMPS: dict = defaultdict(list)
MAX_MESSAGES_PER_MINUTE = 10
MAX_MESSAGES_PER_HOUR = 60


def auth_guard(sender_phone: str) -> bool:
    """
    Reject any incoming WhatsApp number not in the whitelist.
    Sender phone format from Meta is usually E.164 without '+' (e.g. '919876543210').
    """
    if not AUTHORIZED_WHATSAPP_NUMBER:
        # If not configured, log warning and allow for initial development
        log.warning("[guardrails] AUTHORIZED_WHATSAPP_NUMBER not set; allowing sender.")
        return True

    # Normalize by stripping '+' and spaces
    clean_sender = re.sub(r'\D', '', str(sender_phone))
    authorized_list = [
        re.sub(r'\D', '', num.strip())
        for num in AUTHORIZED_WHATSAPP_NUMBER.split(',')
        if num.strip()
    ]

    if clean_sender in authorized_list:
        return True

    log.warning(f"[guardrails] Unauthorized access attempt blocked from: {sender_phone}")
    return False


def rate_limit_check(sender_phone: str) -> Tuple[bool, Optional[str]]:
    """
    Enforce rate limits per sender:
    - 10 messages/minute
    - 60 messages/hour
    Returns (is_allowed, error_message).
    """
    now = time.time()
    timestamps = _MESSAGE_TIMESTAMPS[sender_phone]

    # Clean timestamps older than 1 hour
    _MESSAGE_TIMESTAMPS[sender_phone] = [t for t in timestamps if now - t < 3600]
    recent = _MESSAGE_TIMESTAMPS[sender_phone]

    # Check 1 minute limit
    last_minute_count = sum(1 for t in recent if now - t < 60)
    if last_minute_count >= MAX_MESSAGES_PER_MINUTE:
        log.warning(f"[guardrails] Rate limit exceeded (per minute) by {sender_phone}")
        return False, "⚠️ You are sending messages too quickly. Please wait a moment before sending another query."

    # Check 1 hour limit
    if len(recent) >= MAX_MESSAGES_PER_HOUR:
        log.warning(f"[guardrails] Rate limit exceeded (per hour) by {sender_phone}")
        return False, "⚠️ Hourly message limit reached. Please try again later."

    recent.append(now)
    return True, None


def sanitize_input(message: str) -> Tuple[str, bool]:
    """
    Scans input message for injection patterns and sanitizes dangerous formatting.
    Returns (sanitized_text, is_suspicious).
    """
    if not message:
        return "", False

    is_suspicious = False
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, message, re.IGNORECASE):
            is_suspicious = True
            log.warning(f"[guardrails] Prompt injection pattern detected: '{pattern}'")
            break

    # Strip HTML / XML delimiters to prevent tag breaking
    sanitized = re.sub(r'<[^>]+>', '', message)
    # Strip dangerous code blocks that mimic system prompt injection
    sanitized = re.sub(r'```[\s\S]*?```', '[code snippet removed]', sanitized)

    # Enforce maximum input length of 2000 characters
    if len(sanitized) > 2000:
        sanitized = sanitized[:2000]

    return sanitized.strip(), is_suspicious


def filter_output(text: str) -> str:
    """
    Output DLP: redact API keys, tokens, or raw sensitive patterns.
    """
    if not text:
        return ""

    # Redact common LLM & cloud API keys
    text = re.sub(r'(?:sk-|gsk_|nvapi-|AQ\.|AIza)[A-Za-z0-9_\-]{20,}', '[API_KEY_REDACTED]', text)
    # Redact email addresses
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b', '[EMAIL_REDACTED]', text)
    # Redact full 10-12 digit numbers that look like credentials or bank accounts
    text = re.sub(r'\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4,6}\b', '[NUMBER_MASKED]', text)

    return text


def enforce_grounding(answer: str, sources: List[dict]) -> str:
    """
    If the response contains specific financial numbers (crores, %, ₹) but no [SRC-n]
    citations, append an explicit verification notice.
    """
    has_numbers = bool(re.search(r'₹\s*[\d,.]+|[\d,.]+\s*(?:crore|lakh|%)', answer, re.IGNORECASE))
    has_citations = bool(re.search(r'\[SRC-\d+\]', answer))

    if has_numbers and not has_citations and len(sources) == 0:
        answer += (
            "\n\n⚠️ _Note: The figures above could not be matched directly to a specific "
            "document citation in the current knowledge base. Please verify with statutory filings._"
        )
    return answer


def add_disclaimer_if_needed(answer: str) -> str:
    """
    Appends standard financial disclaimer to research outputs.
    """
    disclaimer = (
        "\n\n_📌 Generated from available company documents & financial databases. "
        "For personal research only. Not financial or investment advice._"
    )
    if "_📌 Generated from available company documents" not in answer:
        answer += disclaimer
    return answer


def quality_gate(answer: str) -> str:
    """
    Validate that the generated response is healthy and suitable for delivery.
    """
    cleaned = answer.strip()
    if len(cleaned) < 15:
        return "I could not find sufficient data to answer your question. Could you please specify the company or topic?"

    # Detect leaked JSON or tracebacks
    if "Traceback (most recent call last):" in cleaned or cleaned.count('{"') > 6:
        log.error("[guardrails] Detected broken response or raw JSON dump.")
        return "An internal error occurred while processing the financial documents. Please rephrase or ask for a specific period."

    return cleaned
