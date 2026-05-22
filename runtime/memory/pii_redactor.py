"""PII redactor — surgical scrub of personally identifiable information.

Runs on every MemoryStore write so journal entries, broker payloads, and
chat messages cannot leak emails, phone numbers, account IDs, addresses,
or API keys into the long-lived JSONL / ChromaDB store.

Design notes
------------
- Patterns compiled once at module load (performance budget: < 5ms/scan).
- Stable substitution tokens: ``[REDACTED:<type>:<sha8>]``. The same source
  string always maps to the same token so internal references survive the
  redaction (e.g. two memories that mention ``foo@bar.com`` will both show
  ``[REDACTED:email:a1b2c3d4]`` and can still be cross-correlated).
- Two confidence tiers via ``strict`` flag — ``strict=False`` (default)
  skips high-false-positive patterns like ``account_id_numeric``.
- Allowlist for infrastructure identifiers (Tailscale IPv4 ``100.x.x.x``,
  localhost ``127.0.0.1``, Brain port ``8800``) — these are not PII.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Pattern catalogue
# ---------------------------------------------------------------------------

PII_PATTERNS: dict[str, str] = {
    "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "phone_us": r"\b(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b(?:\d[ -]*?){13,16}\b",
    "ipv4": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "account_id_numeric": r"\b[A-Z0-9]{8,16}\b",  # broker IDs — high FP rate, strict only
    "api_key_anthropic": r"sk-ant-[a-zA-Z0-9_-]{20,}",
    "api_key_openai": r"sk-[a-zA-Z0-9]{20,}",
    "api_key_xai": r"xai-[a-zA-Z0-9_-]{20,}",
    "bearer_token": r"Bearer\s+[A-Za-z0-9_-]{20,}",
    "private_address": (
        r"\d+\s+[A-Z][a-z]+\s+"
        r"(Street|St\.?|Ave\.?|Avenue|Rd\.?|Road|Blvd\.?|Boulevard|"
        r"Drive|Dr\.?|Lane|Ln\.?|Way|Court|Ct\.?)\b"
    ),
}

# Patterns only enabled in strict mode (very high false-positive risk).
_STRICT_ONLY = {"account_id_numeric"}

# Allowlist — matches that look like PII but are actually infrastructure.
# Keyed by pattern name; values are compiled regexes the full match must
# satisfy for the finding to be discarded.
PII_ALLOWLIST: dict[str, list[str]] = {
    "ipv4": [
        r"^100\.\d{1,3}\.\d{1,3}\.\d{1,3}$",  # Tailscale CGNAT range
        r"^127\.0\.0\.1$",                     # localhost
        r"^0\.0\.0\.0$",                       # any-bind
    ],
    "account_id_numeric": [
        r"^[A-Z]+$",        # all-letters tokens are tickers, not IDs
    ],
}


# Compile once at import time. Order matters — long/specific patterns first
# so that ``sk-ant-...`` is not eaten by the more general ``sk-...`` rule.
_PATTERN_ORDER = [
    "api_key_anthropic",
    "api_key_xai",
    "api_key_openai",
    "bearer_token",
    "ssn",
    "credit_card",
    "phone_us",
    "email",
    "private_address",
    "ipv4",
    "account_id_numeric",
]

_COMPILED: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(PII_PATTERNS[name])) for name in _PATTERN_ORDER
]

_COMPILED_ALLOWLIST: dict[str, list[re.Pattern[str]]] = {
    name: [re.compile(p) for p in patterns]
    for name, patterns in PII_ALLOWLIST.items()
}


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class RedactionResult:
    """Outcome of a single ``PIIRedactor.scan()`` call."""

    original_len: int
    redacted_text: str
    findings: list[dict] = field(default_factory=list)
    redaction_count: int = 0

    def to_audit_dict(self) -> dict:
        """Audit-safe dict — never includes the raw matched text."""
        return {
            "original_len": self.original_len,
            "redaction_count": self.redaction_count,
            "types_found": sorted({f["type"] for f in self.findings}),
        }


# ---------------------------------------------------------------------------
# Stable-token helper
# ---------------------------------------------------------------------------

def _stable_token(pii_type: str, raw_value: str) -> str:
    """Deterministic substitution token.

    Same input -> same token across all writes, allowing redacted memories
    to still cross-reference each other without revealing the underlying
    string.
    """
    digest = hashlib.sha256(raw_value.encode("utf-8")).hexdigest()[:8]
    return f"[REDACTED:{pii_type}:{digest}]"


def _is_allowlisted(pii_type: str, raw_value: str) -> bool:
    patterns = _COMPILED_ALLOWLIST.get(pii_type)
    if not patterns:
        return False
    return any(p.match(raw_value) for p in patterns)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class PIIRedactor:
    """Static facade — stateless and thread-safe."""

    @staticmethod
    def scan(text: str, strict: bool = False) -> RedactionResult:
        """Scan ``text`` for PII; return findings + redacted variant.

        Args:
            text: Input string to scrub.
            strict: When True enables aggressive patterns
                    (``account_id_numeric``) which produce false positives
                    on ordinary stock tickers and SKUs.

        Performance: < 5ms per call for typical memory-unit sizes
        (< 4 KB). Regex compilation happens once at module load.
        """
        if not text:
            return RedactionResult(original_len=0, redacted_text="", findings=[], redaction_count=0)

        original_len = len(text)
        # Track findings + replacement spans so we can rebuild the string
        # in a single pass. We never mutate ``text`` until the end so that
        # offsets stay valid for the lifetime of the scan.
        spans: list[tuple[int, int, str, str]] = []  # (start, end, type, raw)

        for name, pattern in _COMPILED:
            if name in _STRICT_ONLY and not strict:
                continue
            for m in pattern.finditer(text):
                raw = m.group(0)
                if _is_allowlisted(name, raw):
                    continue
                spans.append((m.start(), m.end(), name, raw))

        if not spans:
            return RedactionResult(
                original_len=original_len,
                redacted_text=text,
                findings=[],
                redaction_count=0,
            )

        # Resolve overlaps — earlier/longer matches win. Sort by start
        # ascending, then by length descending so a longer span at the
        # same start beats a shorter one (e.g. ``sk-ant-...`` over
        # ``sk-...``).
        spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
        accepted: list[tuple[int, int, str, str]] = []
        last_end = -1
        for start, end, name, raw in spans:
            if start < last_end:
                continue  # overlaps a longer/earlier match — drop
            accepted.append((start, end, name, raw))
            last_end = end

        # Rebuild text in one pass.
        out_parts: list[str] = []
        findings: list[dict] = []
        cursor = 0
        for start, end, name, raw in accepted:
            if cursor < start:
                out_parts.append(text[cursor:start])
            token = _stable_token(name, raw)
            out_parts.append(token)
            findings.append({
                "type": name,
                "original": raw,
                "replaced_with": token,
                "position": start,
            })
            cursor = end
        if cursor < len(text):
            out_parts.append(text[cursor:])

        return RedactionResult(
            original_len=original_len,
            redacted_text="".join(out_parts),
            findings=findings,
            redaction_count=len(findings),
        )

    @staticmethod
    def redact(text: str, strict: bool = False) -> str:
        """Convenience — returns the redacted string only."""
        return PIIRedactor.scan(text, strict=strict).redacted_text

    @staticmethod
    def is_clean(text: str, strict: bool = False) -> bool:
        """``True`` iff no PII was found."""
        return PIIRedactor.scan(text, strict=strict).redaction_count == 0
