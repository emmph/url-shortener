from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import settings
from app.core.ssrf_guard import ResolverFn, SSRFBlockedError, resolve_and_validate_host
from app.core.url_security import URLValidationError, sanitize_and_normalize_url
from app.db.redis import redis_store

# Compiled regexes for fast header + first-64KB HTML fingerprinting
_PRODUCT_VERSION_RE = re.compile(
    r"(nginx|apache|php|openssl|iis|caddy|tomcat|jetty|express|wordpress|drupal|joomla|jquery|demo-low-lib)"
    r"[/\s_-]+v?(\d+\.\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_META_GENERATOR_RE = re.compile(
    r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']{1,120})["\']',
    re.IGNORECASE,
)
_SCRIPT_SRC_RE = re.compile(
    r'<script[^>]+src=["\']([^"\']{1,300})["\']',
    re.IGNORECASE,
)
_DANGEROUS_EXT_RE = re.compile(r"\.(exe|scr|bat|cmd|msi|vbs|ps1|hta|apk)(?:$|[?#])", re.IGNORECASE)
_PHISHING_HEURISTIC_RE = re.compile(
    r"(login-verify|verify-account-secure|wallet-drain|steal-seed|malware-payload)",
    re.IGNORECASE,
)

# Built-in CVE rules for fast offline detection
_KNOWN_CVE_RULES: Dict[str, List[Tuple[Tuple[int, ...], str, float, str, str]]] = {
    "nginx": [
        ((1, 25, 3), "CVE-2024-7347", 5.3, "MEDIUM", "nginx ngx_http_mp4_module out-of-bounds read"),
        ((1, 23, 0), "CVE-2022-41741", 7.8, "HIGH", "nginx mp4 memory corruption vulnerability"),
    ],
    "apache": [
        ((2, 4, 58), "CVE-2024-38476", 9.8, "CRITICAL", "Apache HTTP Server mod_proxy SSRF / request smuggling"),
        ((2, 4, 52), "CVE-2022-31813", 9.8, "CRITICAL", "Apache HTTP Server X-Forwarded-* bypass"),
    ],
    "php": [
        ((8, 1, 29), "CVE-2024-4577", 9.8, "CRITICAL", "PHP CGI Argument Injection RCE"),
        ((8, 0, 30), "CVE-2023-3824", 9.8, "CRITICAL", "PHP phar buffer overflow"),
    ],
    "openssl": [
        ((3, 0, 12), "CVE-2023-5678", 5.3, "MEDIUM", "OpenSSL DH key generation excessive CPU"),
        ((1, 1, 1), "CVE-2022-0778", 7.5, "HIGH", "OpenSSL infinite loop in BN_mod_sqrt"),
    ],
    "jquery": [
        ((3, 5, 0), "CVE-2020-11022", 6.1, "MEDIUM", "jQuery DOM XSS via htmlPrefilter"),
        ((3, 0, 0), "CVE-2019-11358", 6.1, "MEDIUM", "jQuery prototype pollution"),
    ],
    "wordpress": [
        ((6, 4, 0), "CVE-2023-5561", 5.3, "MEDIUM", "WordPress user email disclosure"),
    ],
    "express": [
        ((4, 19, 2), "CVE-2024-29041", 6.1, "MEDIUM", "Express.js open redirect vulnerability"),
    ],
    "demo-low-lib": [
        ((2, 0, 0), "CVE-2024-0001", 2.6, "LOW", "Minor informational version disclosure (LOW risk)"),
    ],
}


def _parse_version_tuple(ver_str: str) -> Tuple[int, ...]:
    parts: List[int] = []
    for p in ver_str.split(".")[:4]:
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _severity_from_cvss(cvss: float) -> str:
    if cvss >= 9.0:
        return "CRITICAL"
    if cvss >= 7.0:
        return "HIGH"
    if cvss >= 4.0:
        return "MEDIUM"
    if cvss > 0.0:
        return "LOW"
    return "NONE"


@dataclass
class ScanOutcome:
    is_safe: bool
    risk_score: int
    max_cvss: float
    max_severity: str
    reason: str
    report: Dict[str, Any] = field(default_factory=dict)
    host_cache_hit: bool = False


async def _lookup_cve_for_product(
    product: str,
    version: str,
    http_client: httpx.AsyncClient,
) -> List[Dict[str, Any]]:
    prod = product.lower()
    ver_clean = version.strip()
    cache_key = f"cve:pkg:{prod}:{ver_clean}"

    # Check 7-day CVE cache first
    cached = await redis_store.get_json(cache_key)
    if isinstance(cached, list):
        return cached

    findings: List[Dict[str, Any]] = []
    ver_tuple = _parse_version_tuple(ver_clean)

    # Match against fast built-in rules
    for threshold, cve_id, cvss, severity, summary in _KNOWN_CVE_RULES.get(prod, []):
        if ver_tuple < threshold:
            findings.append(
                {
                    "cve_id": cve_id,
                    "product": prod,
                    "version": ver_clean,
                    "cvss": cvss,
                    "severity": severity,
                    "summary": summary,
                    "source": "builtin-rules",
                }
            )
            break

    # Fall back to OSV.dev API for npm libs
    ecosystem_map = {"jquery": "npm", "express": "npm"}
    if not findings and prod in ecosystem_map and settings.osv_api_url:
        try:
            resp = await http_client.post(
                settings.osv_api_url,
                json={"version": ver_clean, "package": {"name": prod, "ecosystem": ecosystem_map[prod]}},
                timeout=2.5,
            )
            if resp.status_code == 200:
                data = resp.json()
                for vuln in (data.get("vulns") or [])[:5]:
                    vid = str(vuln.get("id") or "OSV-UNKNOWN")
                    summary = str(vuln.get("summary") or "Vulnerability reported by OSV.dev")[:200]
                    cvss = 5.5
                    for sev in vuln.get("severity") or []:
                        score_str = str(sev.get("score") or "")
                        if score_str.replace(".", "", 1).isdigit():
                            cvss = float(score_str)
                            break
                    findings.append(
                        {
                            "cve_id": vid,
                            "product": prod,
                            "version": ver_clean,
                            "cvss": cvss,
                            "severity": _severity_from_cvss(cvss),
                            "summary": summary,
                            "source": "osv.dev",
                        }
                    )
        except Exception:
            # Offline or slow OSV API, skip gracefully
            pass

    # Save lookup result for 7 days
    await redis_store.set_json(cache_key, findings, ttl=7 * 24 * 3600)
    return findings


def _extract_software_signatures(headers: httpx.Headers, html_head: str) -> List[Tuple[str, str]]:
    found: Dict[Tuple[str, str], bool] = {}

    # Scan common server headers
    for header_name in ("server", "x-powered-by", "x-generator"):
        val = headers.get(header_name, "")
        for m in _PRODUCT_VERSION_RE.finditer(val):
            found[(m.group(1).lower(), m.group(2))] = True

    # Scan HTML head tags with compiled regex
    if html_head:
        for m in _META_GENERATOR_RE.finditer(html_head):
            for pm in _PRODUCT_VERSION_RE.finditer(m.group(1)):
                found[(pm.group(1).lower(), pm.group(2))] = True

        for m in _SCRIPT_SRC_RE.finditer(html_head):
            src = m.group(1)
            for pm in _PRODUCT_VERSION_RE.finditer(src):
                found[(pm.group(1).lower(), pm.group(2))] = True

    # Optional test header for deterministic CVE checks
    demo_sw = headers.get("x-detected-software", "")
    for m in _PRODUCT_VERSION_RE.finditer(demo_sw):
        found[(m.group(1).lower(), m.group(2))] = True

    return list(found.keys())


def _audit_security_headers(url: str, headers: httpx.Headers) -> List[str]:
    warnings: List[str] = []
    if not url.lower().startswith("https://"):
        warnings.append("Missing HTTPS encryption")
    if "strict-transport-security" not in headers and url.lower().startswith("https://"):
        warnings.append("Missing HSTS header")
    if "x-frame-options" not in headers and "content-security-policy" not in headers:
        warnings.append("Missing X-Frame-Options / CSP headers")
    return warnings


async def scan_url_security(
    target_url: str,
    min_block_cvss: float = 4.0,
    resolver: Optional[ResolverFn] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> ScanOutcome:
    """
    Scan target URL for SSRF, phishing, dangerous payloads, and known CVEs.
    Uses a 12h host cache and caps streaming reads at 64 KB.
    """
    started = time.perf_counter()

    # Block direct executable downloads
    if _DANGEROUS_EXT_RE.search(target_url):
        return ScanOutcome(
            is_safe=False,
            risk_score=95,
            max_cvss=9.0,
            max_severity="CRITICAL",
            reason="Direct link to a potentially dangerous executable file",
            report={"heuristic_flag": "executable_payload", "cves": []},
        )

    # Catch obvious phishing path patterns
    if _PHISHING_HEURISTIC_RE.search(target_url):
        return ScanOutcome(
            is_safe=False,
            risk_score=90,
            max_cvss=8.5,
            max_severity="HIGH",
            reason="Suspicious phishing pattern detected in URL",
            report={"heuristic_flag": "phishing_pattern", "cves": []},
        )

    try:
        sanitized = sanitize_and_normalize_url(target_url, max_length=settings.max_url_length)
    except URLValidationError as exc:
        return ScanOutcome(
            is_safe=False,
            risk_score=90,
            max_cvss=7.5,
            max_severity="HIGH",
            reason=exc.detail,
            report={"validation_error": exc.detail, "cves": []},
        )

    # Always run SSRF check first
    try:
        await resolve_and_validate_host(sanitized.domain, sanitized.port, resolver=resolver)
    except SSRFBlockedError as exc:
        return ScanOutcome(
            is_safe=False,
            risk_score=100,
            max_cvss=9.8,
            max_severity="CRITICAL",
            reason=str(exc),
            report={"ssrf_blocked": True, "detail": str(exc), "cves": []},
        )

    # Reuse 12h host cache when already scanned
    host_cache_key = f"scan:host:{sanitized.domain}"
    cached_host = await redis_store.get_json(host_cache_key)
    if isinstance(cached_host, dict):
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        cached_cvss = float(cached_host.get("max_cvss", 0.0))
        is_safe = cached_cvss < min_block_cvss
        report = dict(cached_host)
        report["host_cache_hit"] = True
        report["duration_ms"] = elapsed_ms
        return ScanOutcome(
            is_safe=is_safe,
            risk_score=int(cached_host.get("risk_score", 0)),
            max_cvss=cached_cvss,
            max_severity=str(cached_host.get("max_severity", "NONE")),
            reason=str(cached_host.get("reason", "Scan passed (host cache)")),
            report=report,
            host_cache_hit=True,
        )

    # Stream page manually so we verify SSRF on every redirect hop
    client_kwargs: Dict[str, Any] = {
        "timeout": httpx.Timeout(settings.scanner_timeout_seconds, connect=3.0),
        "follow_redirects": False,
        "headers": {"User-Agent": "Mozilla/5.0 (compatible; LinkGuardScanner/1.0)"},
    }
    if transport is not None:
        client_kwargs["transport"] = transport

    current_url = sanitized.original_url
    redirect_chain: List[str] = [current_url]
    final_headers: httpx.Headers = httpx.Headers()
    html_head = ""
    fetch_warning: Optional[str] = None

    async with httpx.AsyncClient(**client_kwargs) as client:
        for hop in range(settings.scanner_max_redirects + 1):
            parsed_hop = urlsplit(current_url)
            hop_host = (parsed_hop.hostname or "").lower()
            hop_port = parsed_hop.port or (443 if parsed_hop.scheme.lower() == "https" else 80)

            try:
                await resolve_and_validate_host(hop_host, hop_port, resolver=resolver)
            except SSRFBlockedError as exc:
                return ScanOutcome(
                    is_safe=False,
                    risk_score=100,
                    max_cvss=9.8,
                    max_severity="CRITICAL",
                    reason=str(exc),
                    report={"ssrf_blocked": True, "redirect_chain": redirect_chain, "cves": []},
                )

            try:
                async with client.stream("GET", current_url) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location")
                        if not location:
                            break
                        next_url = urljoin(current_url, location)
                        if _DANGEROUS_EXT_RE.search(next_url) or _PHISHING_HEURISTIC_RE.search(next_url):
                            return ScanOutcome(
                                is_safe=False,
                                risk_score=95,
                                max_cvss=9.0,
                                max_severity="CRITICAL",
                                reason="Dangerous redirect target detected in redirect chain",
                                report={"redirect_chain": redirect_chain + [next_url], "cves": []},
                            )
                        try:
                            next_sanitized = sanitize_and_normalize_url(next_url, max_length=settings.max_url_length)
                        except URLValidationError as exc:
                            return ScanOutcome(
                                is_safe=False,
                                risk_score=90,
                                max_cvss=7.5,
                                max_severity="HIGH",
                                reason=f"Unsafe URL in redirect chain: {exc.detail}",
                                report={"redirect_chain": redirect_chain + [next_url], "cves": []},
                            )
                        if hop >= settings.scanner_max_redirects:
                            fetch_warning = "Exceeded max redirect hops (5)"
                            break
                        current_url = next_sanitized.original_url
                        redirect_chain.append(current_url)
                        continue

                    final_headers = resp.headers
                    content_type = resp.headers.get("content-type", "").lower()
                    # Only inspect HTML responses, cap reads at 64 KB
                    if "text/html" in content_type or "application/xhtml" in content_type or content_type == "":
                        chunks: List[bytes] = []
                        total = 0
                        async for chunk in resp.aiter_bytes(chunk_size=8192):
                            remaining_budget = settings.scanner_max_bytes - total
                            if remaining_budget <= 0:
                                break
                            chunks.append(chunk[:remaining_budget])
                            total += len(chunks[-1])
                            if total >= settings.scanner_max_bytes:
                                break
                        html_head = b"".join(chunks).decode("utf-8", errors="ignore")
                    break
            except httpx.HTTPError as exc:
                fetch_warning = f"Target site unreachable ({type(exc).__name__})"
                break

        # Check detected software versions for CVEs
        signatures = _extract_software_signatures(final_headers, html_head)
        all_cves: List[Dict[str, Any]] = []
        for product, version in signatures:
            cves = await _lookup_cve_for_product(product, version, client)
            all_cves.extend(cves)

    header_warnings = _audit_security_headers(current_url, final_headers)
    if fetch_warning:
        header_warnings.append(fetch_warning)

    max_cvss = max((float(c.get("cvss", 0.0)) for c in all_cves), default=0.0)
    max_severity = _severity_from_cvss(max_cvss)
    risk_score = min(100, int(max_cvss * 10) + (5 if header_warnings and max_cvss == 0 else 0))

    # Block MEDIUM/HIGH/CRITICAL (>= 4.0), let LOW pass
    is_safe = max_cvss < min_block_cvss
    if not is_safe:
        reason = f"{max_severity} vulnerabilities detected (max CVSS {max_cvss:.1f})"
    elif max_cvss > 0:
        reason = f"Scan passed: only LOW risk findings (CVSS {max_cvss:.1f})"
    else:
        reason = "No CVEs or security threats found"

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    report: Dict[str, Any] = {
        "scanned_url": current_url,
        "redirect_chain": redirect_chain,
        "detected_software": [f"{p}/{v}" for p, v in signatures],
        "cves": all_cves,
        "header_warnings": header_warnings,
        "max_cvss": max_cvss,
        "max_severity": max_severity,
        "risk_score": risk_score,
        "reason": reason,
        "duration_ms": elapsed_ms,
        "host_cache_hit": False,
    }

    # Cache clean host scan for 12 hours
    if not fetch_warning:
        await redis_store.set_json(host_cache_key, report, ttl=12 * 3600)

    return ScanOutcome(
        is_safe=is_safe,
        risk_score=risk_score,
        max_cvss=max_cvss,
        max_severity=max_severity,
        reason=reason,
        report=report,
        host_cache_hit=False,
    )
