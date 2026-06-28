from __future__ import annotations

from starlette.requests import Request

from server.request_meta import (
    TRUSTED_PROXY_HEADER,
    TRUSTED_PROXY_VALUE,
    get_client_ip,
)


def _build_request(
    *,
    client_ip: str,
    headers: dict[str, str] | None = None,
) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in (headers or {}).items()
        ],
        "client": (client_ip, 50000),
    }
    return Request(scope)


def test_ignores_forwarded_headers_without_trusted_proxy_marker() -> None:
    request = _build_request(
        client_ip="172.18.0.5",
        headers={
            "X-Forwarded-For": "1.1.1.1, 8.8.4.4",
            "X-Real-IP": "8.8.4.4",
        },
    )

    assert get_client_ip(request) == "172.18.0.5"


def test_uses_real_ip_when_dashboard_is_edge_proxy() -> None:
    request = _build_request(
        client_ip="172.18.0.5",
        headers={
            "X-Forwarded-For": "1.1.1.1, 8.8.4.4",
            "X-Real-IP": "8.8.4.4",
            TRUSTED_PROXY_HEADER: TRUSTED_PROXY_VALUE,
        },
    )

    assert get_client_ip(request) == "8.8.4.4"


def test_uses_previous_forwarded_hop_when_dashboard_sits_behind_caddy() -> None:
    request = _build_request(
        client_ip="172.18.0.5",
        headers={
            "X-Forwarded-For": "1.1.1.1, 8.8.4.4, 172.19.0.9",
            "X-Real-IP": "172.19.0.9",
            TRUSTED_PROXY_HEADER: TRUSTED_PROXY_VALUE,
        },
    )

    assert get_client_ip(request) == "8.8.4.4"
