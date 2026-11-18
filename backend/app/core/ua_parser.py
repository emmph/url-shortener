from __future__ import annotations

import re
from typing import Tuple

_BOT_RE = re.compile(r"(bot|crawler|spider|curl|wget|python-httpx|httpclient)", re.IGNORECASE)
_TABLET_RE = re.compile(r"(ipad|tablet|playbook|silk|kindle)", re.IGNORECASE)
_MOBILE_RE = re.compile(r"(mobi|android|iphone|ipod|blackberry|opera mini|iemobile)", re.IGNORECASE)

_EDGE_RE = re.compile(r"Edg(?:e|A|iOS)?/", re.IGNORECASE)
_OPERA_RE = re.compile(r"(OPR/|Opera/)", re.IGNORECASE)
_CHROME_RE = re.compile(r"(Chrome/|CriOS/)", re.IGNORECASE)
_FIREFOX_RE = re.compile(r"(Firefox/|FxiOS/)", re.IGNORECASE)
_SAFARI_RE = re.compile(r"Safari/", re.IGNORECASE)


def parse_user_agent(user_agent: str) -> Tuple[str, str]:
    """Fast regex-only extraction of (device_type, browser) without storing raw UA."""
    if not user_agent:
        return ("unknown", "Other")

    ua = user_agent[:512]
    if _BOT_RE.search(ua):
        device = "bot"
    elif _TABLET_RE.search(ua):
        device = "tablet"
    elif _MOBILE_RE.search(ua):
        device = "mobile"
    else:
        device = "desktop"

    if _BOT_RE.search(ua):
        browser = "Bot"
    elif _EDGE_RE.search(ua):
        browser = "Edge"
    elif _OPERA_RE.search(ua):
        browser = "Opera"
    elif _CHROME_RE.search(ua):
        browser = "Chrome"
    elif _FIREFOX_RE.search(ua):
        browser = "Firefox"
    elif _SAFARI_RE.search(ua):
        browser = "Safari"
    else:
        browser = "Other"

    return (device, browser)
