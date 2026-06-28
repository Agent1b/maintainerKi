from __future__ import annotations

import ipaddress

from fastapi import Request

TRUSTED_PROXY_HEADER = "x-maintainerki-proxy"
TRUSTED_PROXY_VALUE = "dashboard-nginx"


def get_client_ip(request: Request) -> str:
    direct_client = request.client.host if request.client else "unknown"
    forwarded_client = _trusted_forwarded_ip(request, direct_client=direct_client)
    if forwarded_client:
        return forwarded_client
    return direct_client


def _trusted_forwarded_ip(request: Request, *, direct_client: str) -> str | None:
    if not _is_private_or_loopback(direct_client):
        return None
    if request.headers.get(TRUSTED_PROXY_HEADER, "").strip().lower() != TRUSTED_PROXY_VALUE:
        return None

    real_ip = _header_ip(request, "x-real-ip")
    forwarded_hops = _forwarded_for_hops(request)

    if real_ip and not _is_private_or_loopback(real_ip):
        return real_ip

    if real_ip and forwarded_hops and forwarded_hops[-1] == real_ip:
        # In the bundled hosted stack nginx may sit behind one more trusted proxy
        # (for example Caddy). That means X-Real-IP is nginx's peer, while the
        # previous X-Forwarded-For hop is the browser/GitHub source address.
        for hop in reversed(forwarded_hops[:-1]):
            if hop != real_ip:
                return hop

    if real_ip:
        return real_ip
    if forwarded_hops:
        return forwarded_hops[-1]
    return None


def _header_ip(request: Request, header_name: str) -> str | None:
    raw = request.headers.get(header_name, "").strip()
    if not raw:
        return None
    return raw if _is_ip_address(raw) else None


def _forwarded_for_hops(request: Request) -> list[str]:
    raw = request.headers.get("x-forwarded-for", "").strip()
    if not raw:
        return []
    return [hop for hop in (part.strip() for part in raw.split(",")) if _is_ip_address(hop)]


def _is_private_or_loopback(value: str) -> bool:
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        return False
    return parsed.is_private or parsed.is_loopback


def _is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True
