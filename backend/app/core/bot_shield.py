from __future__ import annotations

import re
from fastapi import Request, Response

PREVIEW_BOT_RE = re.compile(
    r"(TelegramBot|WhatsApp|Discordbot|Slackbot|Twitterbot|facebookexternalhit|"
    r"vkShare|Facebot|LinkedInBot|Applebot|SkypeUriPreview|Google-PageRenderer|"
    r"Pinterestbot|Embedly|Quora Link Preview|Viber|Line/)",
    re.IGNORECASE,
)

PREFETCH_VALUES = frozenset({"prefetch", "prerender", "preview", "prefetch;prerender"})

NEUTRAL_OG_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Short Link</title>
  <meta name="robots" content="noindex, nofollow" />
  <meta property="og:type" content="website" />
  <meta property="og:title" content="Short Link" />
  <meta property="og:description" content="Protected shortened URL" />
</head>
<body>Short Link</body>
</html>
"""


def is_bot_or_prefetch_request(request: Request) -> bool:
    """Detect HEAD, browser prefetch/prerender, and messenger link-preview bots."""
    # Ignore HEAD probes
    if request.method.upper() == "HEAD":
        return True

    # Ignore browser link prefetching
    for header_name in ("purpose", "sec-purpose", "x-purpose", "x-moz"):
        val = request.headers.get(header_name, "").strip().lower()
        if any(token in val for token in PREFETCH_VALUES):
            return True

    # Ignore chat preview crawlers
    ua = request.headers.get("user-agent", "")
    if ua and PREVIEW_BOT_RE.search(ua):
        return True

    return False


def build_bot_preview_response(is_head: bool = False) -> Response:
    """Return neutral 200 OK preview without consuming link limits or touching DB."""
    return Response(
        content="" if is_head else NEUTRAL_OG_HTML,
        status_code=200,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "X-Robots-Tag": "noindex, nofollow",
            "X-Content-Type-Options": "nosniff",
        },
    )
