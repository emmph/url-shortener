from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
VALID_SHORT_CODE_RE = re.compile(r"^[a-zA-Z0-9_-]{4,16}$")


class URLValidationError(Exception):
    """Structured URL validation failure mapped to unified API/UI error routing."""

    def __init__(self, status_code: int, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class SanitizedURL:
    original_url: str
    normalized_url: str
    url_hash: str
    domain: str
    port: int


def _script_category(ch: str) -> str:
    if "a" <= ch.lower() <= "z":
        return "LATIN"
    name = unicodedata.name(ch, "")
    if "CYRILLIC" in name:
        return "CYRILLIC"
    if "GREEK" in name:
        return "GREEK"
    return "OTHER"


def _check_homograph(hostname: str) -> str:
    """Decode punycode labels and reject mixed-script IDN homograph spoofing."""
    ascii_host = hostname.strip().rstrip(".").lower()
    if not ascii_host or len(ascii_host) > 253:
        raise URLValidationError(422, "invalid_url", "Invalid domain name in URL")

    # Convert IDN to ASCII punycode
    try:
        idna_bytes = ascii_host.encode("idna")
        ascii_domain = idna_bytes.decode("ascii").lower()
    except UnicodeError as exc:
        raise URLValidationError(422, "invalid_url", "Invalid IDN or Punycode domain") from exc

    # Inspect each DNS label for mixed alphabets
    for label in ascii_domain.split("."):
        if not label or len(label) > 63:
            raise URLValidationError(422, "invalid_url", "Malformed domain label")
        if label.startswith("xn--"):
            try:
                decoded = label.encode("ascii").decode("idna")
            except UnicodeError as exc:
                raise URLValidationError(422, "invalid_url", "Suspicious Punycode domain") from exc
            scripts = {
                _script_category(ch)
                for ch in decoded
                if ch.isalpha() and _script_category(ch) != "OTHER"
            }
            if len(scripts) > 1 or ("LATIN" in scripts and ("CYRILLIC" in scripts or "GREEK" in scripts)):
                raise URLValidationError(
                    422,
                    "invalid_url",
                    "Potential domain spoofing detected (IDN homograph)",
                )
        else:
            scripts = {
                _script_category(ch)
                for ch in label
                if ch.isalpha() and _script_category(ch) != "OTHER"
            }
            if len(scripts) > 1:
                raise URLValidationError(
                    422,
                    "invalid_url",
                    "Mixed character scripts in domain label (homograph)",
                )

    return ascii_domain


def sanitize_and_normalize_url(raw_url: str, max_length: int = 2048) -> SanitizedURL:
    """Validate and normalize user-submitted URL in memory with zero DB overhead."""
    if not isinstance(raw_url, str):
        raise URLValidationError(422, "invalid_url", "URL must be a string")

    candidate = raw_url.strip()
    if not candidate:
        raise URLValidationError(422, "invalid_url", "URL field cannot be empty")

    # Reject overly long URLs early
    if len(candidate) > max_length:
        raise URLValidationError(
            413,
            "payload_too_large",
            f"URL length exceeds the limit of {max_length} characters",
        )

    # Block CR/LF/NUL against header injection
    if CONTROL_CHARS_RE.search(candidate):
        raise URLValidationError(422, "invalid_url", "URL contains forbidden control characters")

    try:
        parsed = urlsplit(candidate)
    except ValueError as exc:
        raise URLValidationError(422, "invalid_url", "Malformed URL syntax") from exc

    # Only allow standard web protocols
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise URLValidationError(
            422,
            "invalid_url",
            "Only http:// and https:// protocols are allowed",
        )

    # Reject user:pass@host phishing tricks
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise URLValidationError(
            422,
            "invalid_url",
            "Embedded credentials in URL are not allowed",
        )

    if not parsed.hostname:
        raise URLValidationError(422, "invalid_url", "Missing hostname in URL")

    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise URLValidationError(422, "invalid_url", "Invalid port number in URL") from exc

    ascii_domain = _check_homograph(parsed.hostname)

    # Strip default ports for clean deduplication
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        netloc = ascii_domain
    else:
        netloc = f"{ascii_domain}:{port}"

    path = parsed.path or "/"
    normalized_url = urlunsplit((scheme, netloc, path, parsed.query, ""))
    url_hash = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()

    return SanitizedURL(
        original_url=candidate,
        normalized_url=normalized_url,
        url_hash=url_hash,
        domain=ascii_domain,
        port=port,
    )
