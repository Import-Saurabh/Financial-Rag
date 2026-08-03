"""
pipeline/extract/text_cleaner.py
Normalize and clean text extracted from financial PDFs.
Handles common PDF artifacts: ligatures, encoding issues, spacing noise.

Phase-1 additions:
  - Boilerplate detection for cover pages, disclaimers, participant lists
  - Section classification helpers for concall transcripts
  - Financial number preservation (never strip INR/currency amounts)
"""

import re
import unicodedata
from typing import Optional


# ─────────────────────────────────────────────
# Ligature and encoding fixes
# ─────────────────────────────────────────────
LIGATURES = {
    "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
    "\ufb00": "ff", "\u2019": "'", "\u2018": "'",
    "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-",
    "\u00a0": " ",  # non-breaking space
    "\u200b": "",   # zero-width space
    "\ufffd": "",   # replacement char
}

LIGATURE_TABLE = str.maketrans(LIGATURES)


def fix_ligatures(text: str) -> str:
    return text.translate(LIGATURE_TABLE)


# ─────────────────────────────────────────────
# Boilerplate detection (cover / disclaimer / participants)
# ─────────────────────────────────────────────
# Strong signals — any one match marks the whole page as boilerplate.
_BOILERPLATE_STRONG = re.compile(
    r"|".join([
        r"\b(?:corporate\s+)?(?:identity\s+)?number\b.*\bCIN\b",
        r"\bCIN\s*[:\-]?\s*[LU]\d{5}",
        r"\b(?:BSE|NSE)\s*(?:code|symbol|scrip)\s*[:\-]?\s*\d+",
        r"\b(?:national\s+stock\s+exchange|bombay\s+stock\s+exchange)\b",
        r"\b(?:safe\s+harbor|forward.?looking\s+statements?)\b",
        r"\b(?:this\s+transcript|transcript\s+(?:is|has\s+been))\s+(?:prepared|provided|sourced)",
        r"\b(?:disclaimer|important\s+notice|legal\s+notice)\b",
        r"\b(?:participants?\s+on\s+(?:the\s+)?call|conference\s+participants?)\b",
        r"\b(?:analysts?\s+present|representatives?\s+present)\b",
        r"\b(?:operator|moderator)\s*[:\-]\s*(?:good\s+(?:morning|afternoon|evening)|welcome)",
        r"\b(?:thank\s+you\s+for\s+(?:standing\s+by|joining|participating))\b",
        r"\b(?:earnings?\s+call\s+(?:transcript|for|dated))\b",
        r"\b(?:transcript\s+availability|audio\s+replay)\b",
        r"\b(?:registered\s+office|corporate\s+office)\s*[:\-]",
        r"\b(?:tel(?:ephone)?|fax|email|website|www\.)\s*[:\-]",
        r"\b(?:scrip\s+code|ISIN\s*[:\-])\b",
    ]),
    re.IGNORECASE | re.DOTALL,
)

# Weaker signals — need 2+ hits on a short page to classify as boilerplate.
_BOILERPLATE_WEAK = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bparticipant",
        r"\b(?:host|presenter|coordinator)\b",
        r"\b(?:conference\s+date|call\s+date)\b",
        r"\b(?:transcript\s+date|event\s+date)\b",
        r"\b(?:dial.?in|passcode|replay\s+number)\b",
        r"\b(?:copyright|all\s+rights\s+reserved)\b",
        r"\b(?:not\s+for\s+(?:publication|distribution))\b",
        r"\b(?:page\s+\d+\s+of\s+\d+)\b",
        r"^\s*\d+\s*$",                          # lone page numbers
    ]
]

# Section header patterns for concall structure
SECTION_PATTERNS = {
    "opening_remarks": re.compile(
        r"(?:opening\s+remarks|prepared\s+remarks|management\s+remarks|"
        r"presentation|management\s+commentary|management\s+discussion|"
        r"introductory\s+remarks|initial\s+remarks|overview)",
        re.IGNORECASE,
    ),
    "qa": re.compile(
        r"(?:question\s*(?:and|&)\s*answer|Q\s*&\s*A|analyst\s+questions?|"
        r"interactive\s+session|open\s+(?:forum|session)|"
        r"questions?\s+from\s+(?:analysts?|participants?))",
        re.IGNORECASE,
    ),
    "guidance": re.compile(
        r"(?:outlook|guidance|forward\s+looking|future\s+(?:outlook|guidance))",
        re.IGNORECASE,
    ),
    "closing": re.compile(
        r"(?:closing\s+remarks|concluding\s+remarks|wrap\s+up|end\s+of\s+call)",
        re.IGNORECASE,
    ),
}


def classify_section_header(text: str) -> Optional[str]:
    """Return section_type if text looks like a concall section header."""
    t = text.strip()
    if len(t) > 120:
        return None
    for section_type, pattern in SECTION_PATTERNS.items():
        if pattern.search(t):
            return section_type
    return None


def is_boilerplate_text(text: str) -> bool:
    """
    Return True if text is cover/disclaimer/participant boilerplate
    that should NOT be indexed for retrieval.
    """
    if not text or not text.strip():
        return True

    t = text.strip()
    word_count = len(t.split())

    if _BOILERPLATE_STRONG.search(t):
        return True

    # Short pages with multiple weak boilerplate signals
    if word_count < 150:
        weak_hits = sum(1 for p in _BOILERPLATE_WEAK if p.search(t))
        if weak_hits >= 2:
            return True

    # Participant list pages: many short lines with names/titles, few sentences
    lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
    if len(lines) >= 8 and word_count < 200:
        name_like = sum(
            1 for ln in lines
            if re.match(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z\.]+){1,4}(?:\s*[\-–,]\s*.+)?$", ln)
        )
        if name_like >= 5:
            return True

    return False


def is_boilerplate_page(page_text: str, page_num: int) -> bool:
    """
    Page-level boilerplate check. Early pages (1-3) get stricter filtering
    because cover/disclaimer/participant lists cluster at the front.
    """
    if is_boilerplate_text(page_text):
        return True

    # First 3 pages: if >60% of words match known noise tokens, skip
    if page_num <= 3:
        words = page_text.lower().split()
        if not words:
            return True
        noise_tokens = {
            "cin", "bse", "nse", "participant", "participants", "disclaimer",
            "transcript", "conference", "operator", "moderator", "welcome",
            "registered", "office", "website", "email", "fax", "tel",
            "copyright", "reserved", "replay", "dial", "passcode",
        }
        noise_count = sum(1 for w in words if w.strip(".,:;") in noise_tokens)
        if noise_count / len(words) > 0.25 and len(words) < 120:
            return True

    return False


# ─────────────────────────────────────────────
# Common financial PDF noise patterns
# ─────────────────────────────────────────────
NOISE_PATTERNS = [
    (re.compile(r"Page \d+ of \d+", re.IGNORECASE), ""),
    (re.compile(r"^\s*\d+\s*$", re.MULTILINE), ""),       # lone page numbers
    (re.compile(r"CONFIDENTIAL.*?$", re.IGNORECASE | re.MULTILINE), ""),
    # URLs removed only in aggressive mode — keep if embedded in footnotes
    (re.compile(r"(?:www\.|https?://)[^\s]+"), ""),
    # CIN on its own line — but preserve if part of a financial table
    (re.compile(r"^CIN[:\s]+[A-Z0-9]+\s*$", re.IGNORECASE | re.MULTILINE), ""),
    (re.compile(r"^(?:Tel|Fax|Email|Website)[:\s].{0,80}$", re.IGNORECASE | re.MULTILINE), ""),
]

# Patterns applied ONLY to boilerplate-adjacent prose, never to tables
AGGRESSIVE_NOISE = [
    (re.compile(r"\b[A-Z]{2,6}\d{6,}\b"), ""),             # BSE/NSE codes
    (re.compile(r"CIN[:\s]+[A-Z0-9]+", re.IGNORECASE), ""),
]


def remove_noise(text: str, aggressive: bool = False) -> str:
    for pattern, replacement in NOISE_PATTERNS:
        text = pattern.sub(replacement, text)
    if aggressive:
        for pattern, replacement in AGGRESSIVE_NOISE:
            text = pattern.sub(replacement, text)
    return text


# ─────────────────────────────────────────────
# Whitespace normalisation
# ─────────────────────────────────────────────
def normalize_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.strip()


# ─────────────────────────────────────────────
# Number normalisation (financial tables)
# ─────────────────────────────────────────────
def normalize_numbers(text: str) -> str:
    text = re.sub(r"\bCr\.?\b", "Crore", text, flags=re.IGNORECASE)
    text = re.sub(r"\bLk\.?\b", "Lakh", text, flags=re.IGNORECASE)
    text = re.sub(r"\bMn\.?\b", "Million", text, flags=re.IGNORECASE)
    text = re.sub(r"\bBn\.?\b", "Billion", text, flags=re.IGNORECASE)
    # Preserve Indian comma-grouped numbers — do NOT strip commas
    return text


# ─────────────────────────────────────────────
# Main cleaner
# ─────────────────────────────────────────────
def clean_text(text: str, aggressive: bool = False, preserve_speakers: bool = False) -> str:
    """
    Clean extracted PDF text.
    aggressive=True removes more noise (good for prose, not tables).
    preserve_speakers=True keeps speaker label lines intact (concall turns).
    """
    if not text:
        return ""

    text = fix_ligatures(text)
    text = unicodedata.normalize("NFKC", text)

    if aggressive and not preserve_speakers:
        text = remove_noise(text, aggressive=True)
    elif aggressive:
        text = remove_noise(text, aggressive=False)

    text = normalize_numbers(text)
    text = normalize_whitespace(text)

    return text


def is_garbage_text(text: str, min_words: int = 10) -> bool:
    """Return True if text is too short, too noisy, or boilerplate."""
    if is_boilerplate_text(text):
        return True

    words = text.split()
    if len(words) < min_words:
        return True

    alpha = sum(c.isalpha() for c in text)
    total = max(len(text), 1)
    if alpha / total < 0.4:
        return True

    return False
