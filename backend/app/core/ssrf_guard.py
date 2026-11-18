from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Awaitable, Callable, List, Optional


class SSRFBlockedError(Exception):
    """Raised when a target host resolves to a private, loopback, or metadata IP."""


# Block internal, CGNAT, link-local, and cloud metadata subnets
_EXTRA_BLOCKED_NETWORKS = (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata",
    }
)


def is_ip_blocked(ip_str: str) -> bool:
    """Return True if the IP is loopback, private, link-local, metadata, or reserved."""
    clean = ip_str.split("%", 1)[0].strip("[]")
    try:
        ip_obj = ipaddress.ip_address(clean)
    except ValueError:
        return True

    # Unwrap IPv4-mapped IPv6 addresses like ::ffff:127.0.0.1
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped is not None:
        if is_ip_blocked(str(ip_obj.ipv4_mapped)):
            return True

    if (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
        or not ip_obj.is_global
    ):
        return True

    return any(ip_obj in net for net in _EXTRA_BLOCKED_NETWORKS)


ResolverFn = Callable[[str, int], Awaitable[List[str]]]


async def default_dns_resolver(hostname: str, port: int) -> List[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    ips: List[str] = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr:
            ips.append(str(sockaddr[0]))
    return ips


async def resolve_and_validate_host(
    hostname: str,
    port: int,
    resolver: Optional[ResolverFn] = None,
) -> List[str]:
    """Validate hostname literal and DNS results against SSRF / DNS rebinding."""
    host = hostname.strip().lower().rstrip(".")
    # Block local hostnames immediately
    if not host or host in _BLOCKED_HOSTNAMES or host.endswith(".local") or host.endswith(".internal"):
        raise SSRFBlockedError(f"Access to internal host '{host}' is forbidden (SSRF)")

    # Check literal IPs before DNS lookup
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        if is_ip_blocked(host):
            raise SSRFBlockedError(f"IP address '{host}' belongs to a protected network (SSRF)")
        return [host]

    resolve = resolver or default_dns_resolver
    try:
        resolved_ips = await resolve(host, port)
    except OSError as exc:
        raise SSRFBlockedError(f"Failed to resolve DNS for '{host}': {exc}") from exc

    if not resolved_ips:
        raise SSRFBlockedError(f"DNS returned no IP addresses for '{host}'")

    # Reject if any DNS record points inside private network
    for ip in resolved_ips:
        if is_ip_blocked(ip):
            raise SSRFBlockedError(f"Host '{host}' resolved to a protected IP '{ip}' (SSRF / DNS Rebinding)")

    return resolved_ips
