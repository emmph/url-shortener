from __future__ import annotations

import asyncio
from typing import List

import httpx
import pytest
from sqlalchemy import func, select

from app.db import session as db_session
from app.models.blocked_url import BlockedUrl
from app.models.click_event import ClickEvent
from app.models.link import Link
from app.services.scanner import scan_url_security
from app.workers.analytics_flusher import flush_analytics_batch
from app.workers.scan_worker import process_scan_for_code


async def _public_dns_resolver(hostname: str, port: int) -> List[str]:
    return ["93.184.216.34"]


async def _private_dns_resolver(hostname: str, port: int) -> List[str]:
    return ["10.0.0.42"]


def _make_mock_transport(
    status_code: int = 200,
    headers: dict = None,
    body: bytes = b"<html><head><title>Safe Page</title></head><body>OK</body></html>",
):
    resp_headers = {"content-type": "text/html; charset=utf-8", **(headers or {})}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=status_code, headers=resp_headers, content=body)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_create_links_and_max_clicks_bounds(test_client: httpx.AsyncClient):
    # Unlimited link (default mode)
    r1 = await test_client.post(
        "/api/v1/links",
        json={"original_url": "https://example.com/unlimited", "max_clicks": None},
    )
    assert r1.status_code == 201
    d1 = r1.json()
    assert d1["max_clicks"] is None
    assert d1["scan_status"] == "PENDING"

    # Limited link within 1..250
    r2 = await test_client.post(
        "/api/v1/links",
        json={"original_url": "https://example.com/max250", "max_clicks": 250},
    )
    assert r2.status_code == 201
    assert r2.json()["max_clicks"] == 250

    # Out-of-bounds: 0 and 251 must fail with unified 422 JSON
    r_zero = await test_client.post(
        "/api/v1/links",
        json={"original_url": "https://example.com/zero", "max_clicks": 0},
    )
    assert r_zero.status_code == 422
    assert r_zero.json()["error_code"] == 422
    assert r_zero.json()["error_url"] == "/error/422?reason=invalid_url"

    r_over = await test_client.post(
        "/api/v1/links",
        json={"original_url": "https://example.com/over", "max_clicks": 251},
    )
    assert r_over.status_code == 422
    assert r_over.json()["error_code"] == 422


@pytest.mark.asyncio
async def test_url_sanitizer_and_ssrf_guard(test_client: httpx.AsyncClient):
    # Invalid schemes, embedded credentials, CRLF, homograph, >2048 length
    bad_urls = [
        ("javascript:alert(1)", 422),
        ("data:text/html,<script>alert(1)</script>", 422),
        ("https://google.com@evil.example.org/phish", 422),
        ("https://example.com/\r\nSet-Cookie: a=1", 422),
        ("https://аpple.com/login", 422),  # Cyrillic 'а' mixed with Latin 'pple'
        ("https://example.com/" + ("a" * 2050), 413),
    ]
    for url, expected_code in bad_urls:
        resp = await test_client.post("/api/v1/links", json={"original_url": url})
        assert resp.status_code == expected_code, f"Failed for {url}: {resp.text}"
        assert resp.json()["error_code"] == expected_code

    # Direct SSRF literals and DNS Rebinding
    s1 = await scan_url_security("http://127.0.0.1:6379/info")
    assert s1.is_safe is False
    assert s1.max_severity == "CRITICAL"

    s2 = await scan_url_security("http://169.254.169.254/latest/meta-data/")
    assert s2.is_safe is False

    s3 = await scan_url_security("https://rebind.example.org", resolver=_private_dns_resolver)
    assert s3.is_safe is False
    assert s3.report.get("ssrf_blocked") is True

    # Redirect hop leading to SSRF
    def redirect_to_ssrf(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://127.0.0.1:5432/"})

    s4 = await scan_url_security(
        "https://redirector.example.org",
        resolver=_public_dns_resolver,
        transport=httpx.MockTransport(redirect_to_ssrf),
    )
    assert s4.is_safe is False


@pytest.mark.asyncio
async def test_pending_wait_and_bot_prefetch_shield_on_one_time_link(test_client: httpx.AsyncClient):
    create_resp = await test_client.post(
        "/api/v1/links",
        json={"original_url": "https://example.com/secret-one-time", "max_clicks": 1},
    )
    assert create_resp.status_code == 201
    code = create_resp.json()["short_code"]

    # While PENDING: browser gets redirected to /scanning/{code}, API gets 423 Locked, and limit is NOT burned
    browser_wait = await test_client.get(f"/{code}", headers={"Accept": "text/html"}, follow_redirects=False)
    assert browser_wait.status_code == 307
    assert browser_wait.headers["location"] == f"/scanning/{code}"

    api_wait = await test_client.get(f"/{code}", follow_redirects=False)
    assert api_wait.status_code == 423
    assert "Retry-After" in api_wait.headers

    status_resp = await test_client.get(f"/api/v1/links/{code}/scan-status")
    assert status_resp.status_code == 200
    assert status_resp.json()["scan_status"] == "PENDING"

    # Run scanner -> SAFE
    outcome = await process_scan_for_code(
        code,
        resolver=_public_dns_resolver,
        transport=_make_mock_transport(headers={"strict-transport-security": "max-age=31536000"}),
    )
    assert outcome is not None and outcome.is_safe is True

    # Bot & Prefetch Shield: HEAD, TelegramBot, WhatsApp, Sec-Purpose: prefetch must NOT consume max_clicks=1
    bot_checks = [
        ("HEAD", {"User-Agent": "Mozilla/5.0"}),
        ("GET", {"User-Agent": "TelegramBot (like TwitterBot)"}),
        ("GET", {"User-Agent": "WhatsApp/2.23.20 A"}),
        ("GET", {"User-Agent": "Mozilla/5.0", "Sec-Purpose": "prefetch;prerender"}),
    ]
    for method, hdrs in bot_checks:
        res = await test_client.request(method, f"/{code}", headers=hdrs, follow_redirects=False)
        assert res.status_code == 200
        if method == "GET":
            assert 'property="og:title"' in res.text

    # Real user click 1 -> succeeds with 307 and secure redirect headers
    real_click_1 = await test_client.get(
        f"/{code}",
        headers={"User-Agent": "Mozilla/5.0 Chrome/128.0.0.0"},
        follow_redirects=False,
    )
    assert real_click_1.status_code == 307
    assert real_click_1.headers["location"] == "https://example.com/secret-one-time"
    assert real_click_1.headers["referrer-policy"] == "no-referrer"
    assert real_click_1.headers["x-content-type-options"] == "nosniff"
    assert real_click_1.headers["cross-origin-opener-policy"] == "same-origin"
    assert "no-store" in real_click_1.headers["cache-control"]

    # Real user click 2 -> limit exhausted -> browser gets /error/410?reason=unavailable, API gets 410
    real_click_2_browser = await test_client.get(
        f"/{code}",
        headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0 Chrome/128.0.0.0"},
        follow_redirects=False,
    )
    assert real_click_2_browser.status_code == 307
    assert real_click_2_browser.headers["location"] == "/error/410?reason=unavailable"

    real_click_2_api = await test_client.get(f"/{code}", follow_redirects=False)
    assert real_click_2_api.status_code == 410
    assert real_click_2_api.json()["error_url"] == "/error/410?reason=unavailable"


@pytest.mark.asyncio
async def test_cve_policy_low_allowed_and_medium_deletes_and_blocks(test_client: httpx.AsyncClient):
    # 1. LOW severity (CVSS 2.6 < 4.0) should PASS and link becomes SAFE
    low_resp = await test_client.post(
        "/api/v1/links",
        json={"original_url": "https://low-risk.example.org/page"},
    )
    low_code = low_resp.json()["short_code"]
    low_outcome = await process_scan_for_code(
        low_code,
        resolver=_public_dns_resolver,
        transport=_make_mock_transport(headers={"X-Detected-Software": "demo-low-lib/1.0.0"}),
    )
    assert low_outcome is not None
    assert low_outcome.is_safe is True
    assert low_outcome.max_severity == "LOW"

    go_low = await test_client.get(f"/{low_code}", follow_redirects=False)
    assert go_low.status_code == 307

    # 2. Second link on same host hits 12h Redis host cache
    low_resp_2 = await test_client.post(
        "/api/v1/links",
        json={"original_url": "https://low-risk.example.org/second-page"},
    )
    low_code_2 = low_resp_2.json()["short_code"]
    low_outcome_2 = await process_scan_for_code(
        low_code_2,
        resolver=_public_dns_resolver,
        transport=_make_mock_transport(status_code=500),  # should not even be called due to host cache!
    )
    assert low_outcome_2 is not None and low_outcome_2.host_cache_hit is True and low_outcome_2.is_safe is True

    # 3. MEDIUM severity (nginx/1.24.0 -> CVSS 5.3 >= 4.0) MUST delete link and permanently block URL
    med_url = "https://vulnerable-medium.example.org/app"
    med_resp = await test_client.post("/api/v1/links", json={"original_url": med_url})
    med_code = med_resp.json()["short_code"]

    med_outcome = await process_scan_for_code(
        med_code,
        resolver=_public_dns_resolver,
        transport=_make_mock_transport(headers={"Server": "nginx/1.24.0"}),
    )
    assert med_outcome is not None
    assert med_outcome.is_safe is False
    assert med_outcome.max_severity == "MEDIUM"

    # Link deleted from `links`, URL added to `blocked_urls`
    async with db_session.AsyncSessionLocal() as session:
        deleted_link = await session.scalar(select(Link).where(Link.short_code == med_code))
        blocked_row = await session.scalar(select(BlockedUrl).where(BlockedUrl.original_url == med_url))
        assert deleted_link is None
        assert blocked_row is not None
        assert blocked_row.max_severity == "MEDIUM"

    # Scan-status reports REMOVED_UNSAFE -> /error/410?reason=unavailable
    scan_st = await test_client.get(f"/api/v1/links/{med_code}/scan-status")
    assert scan_st.json()["scan_status"] == "REMOVED_UNSAFE"
    assert scan_st.json()["error_url"] == "/error/410?reason=unavailable"

    # Redirect on deleted short code -> /error/410?reason=unavailable
    med_redirect = await test_client.get(f"/{med_code}", headers={"Accept": "text/html"}, follow_redirects=False)
    assert med_redirect.status_code == 307
    assert med_redirect.headers["location"] == "/error/410?reason=unavailable"

    # Re-shortening the blocked URL is immediately rejected with 403
    re_create = await test_client.post("/api/v1/links", json={"original_url": med_url})
    assert re_create.status_code == 403
    assert re_create.json()["error_url"] == "/error/403?reason=unsafe_url"


@pytest.mark.asyncio
async def test_concurrent_race_condition_and_analytics_batch_flusher(test_client: httpx.AsyncClient):
    resp = await test_client.post(
        "/api/v1/links",
        json={"original_url": "https://example.com/race", "max_clicks": 3},
    )
    code = resp.json()["short_code"]
    await process_scan_for_code(
        code,
        resolver=_public_dns_resolver,
        transport=_make_mock_transport(),
    )

    # Fire 10 simultaneous GET requests
    results = await asyncio.gather(
        *[
            test_client.get(
                f"/{code}",
                headers={"User-Agent": "Mozilla/5.0 Chrome/128.0.0.0"},
                follow_redirects=False,
            )
            for _ in range(10)
        ]
    )
    statuses = [r.status_code for r in results]
    assert statuses.count(307) == 3
    assert statuses.count(410) == 7

    # Flush write-behind buffer into DB and verify exact counts
    flushed = await flush_analytics_batch(500)
    assert flushed == 3

    async with db_session.AsyncSessionLocal() as session:
        link = await session.scalar(select(Link).where(Link.short_code == code))
        events_count = await session.scalar(
            select(func.count(ClickEvent.id)).where(ClickEvent.link_id == link.id)
        )
        assert link.clicks_count == 3
        assert link.is_active is False
        assert events_count == 3


@pytest.mark.asyncio
async def test_antibruteforce_404_shield_and_admin_auth_lockout_and_management(test_client: httpx.AsyncClient):
    # Admin endpoints require authentication
    unauth = await test_client.get("/api/v1/admin/overview")
    assert unauth.status_code == 401

    # Bruteforce 404/DEAD short codes -> triggers 429 shield after threshold (30)
    got_429 = False
    for i in range(32):
        r = await test_client.get(f"/deadcode{i:02d}", follow_redirects=False)
        if r.status_code == 429:
            got_429 = True
            assert r.json()["error_url"] == "/error/429?reason=rate_limit"
            break
    assert got_429 is True

    # Admin lockout after 5 wrong login attempts (using distinct X-Forwarded-For IP)
    attacker_hdr = {"X-Forwarded-For": "198.51.100.77"}
    for _ in range(4):
        bad = await test_client.post(
            "/api/v1/admin/login",
            json={"username": "admin", "password": "wrong"},
            headers=attacker_hdr,
        )
        assert bad.status_code == 401
    fifth = await test_client.post(
        "/api/v1/admin/login",
        json={"username": "admin", "password": "wrong"},
        headers=attacker_hdr,
    )
    assert fifth.status_code == 429

    # Valid admin login from clean IP sets HttpOnly cookie
    admin_hdr = {"X-Forwarded-For": "203.0.113.10"}
    login_ok = await test_client.post(
        "/api/v1/admin/login",
        json={"username": "admin", "password": "admin123"},
        headers=admin_hdr,
    )
    assert login_ok.status_code == 200
    assert login_ok.json()["authenticated"] is True
    assert "admin_session" in test_client.cookies

    # Create and block a vulnerable URL, then view & unblock via Admin API
    vuln_url = "https://vuln-admin.example.org/wp"
    cr = await test_client.post("/api/v1/links", json={"original_url": vuln_url}, headers=admin_hdr)
    v_code = cr.json()["short_code"]
    await process_scan_for_code(
        v_code,
        resolver=_public_dns_resolver,
        transport=_make_mock_transport(headers={"X-Powered-By": "PHP/8.0.1"}),
    )

    overview = await test_client.get("/api/v1/admin/overview")
    assert overview.status_code == 200
    assert overview.json()["blocked_urls_count"] >= 1

    blocked_list = await test_client.get("/api/v1/admin/blocked-urls")
    assert blocked_list.status_code == 200
    items = blocked_list.json()["items"]
    assert any(item["original_url"] == vuln_url for item in items)
    target_id = next(item["id"] for item in items if item["original_url"] == vuln_url)

    unblock = await test_client.delete(f"/api/v1/admin/blocked-urls/{target_id}")
    assert unblock.status_code == 200

    # After unblocking, URL can be shortened again
    re_cr = await test_client.post("/api/v1/links", json={"original_url": vuln_url}, headers=admin_hdr)
    assert re_cr.status_code == 201

    # Admin can pause public link creation on the fly
    curr_settings = (await test_client.get("/api/v1/admin/settings")).json()
    curr_settings["allow_public_creation"] = False
    put_res = await test_client.put("/api/v1/admin/settings", json=curr_settings)
    assert put_res.status_code == 200
    assert put_res.json()["allow_public_creation"] is False

    paused_cr = await test_client.post(
        "/api/v1/links",
        json={"original_url": "https://example.com/during-pause"},
        headers=admin_hdr,
    )
    assert paused_cr.status_code == 503
    assert paused_cr.json()["error_url"] == "/error/503?reason=maintenance"


@pytest.mark.asyncio
async def test_health_metrics_and_64kb_streaming_cap(test_client: httpx.AsyncClient):
    h = await test_client.get("/healthz")
    assert h.status_code == 200 and h.json()["status"] == "ok"

    rdy = await test_client.get("/readyz")
    assert rdy.status_code == 200 and rdy.json()["status"] == "ready"

    m = await test_client.get("/metrics")
    assert m.status_code == 200

    # Body > 64KB: software signature placed at byte 100KB should NOT be scanned beyond 64KB cap
    huge_body = (b"<html><head><title>Big</title></head><body>" + (b"A" * 80000) + b'<script src="/jquery-1.12.4.min.js"></script></body></html>')
    outcome = await scan_url_security(
        "https://large-page.example.org/",
        resolver=_public_dns_resolver,
        transport=_make_mock_transport(body=huge_body),
    )
    assert outcome.is_safe is True
    assert outcome.report.get("cves") == []
