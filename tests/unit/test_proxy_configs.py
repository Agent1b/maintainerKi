from __future__ import annotations

from pathlib import Path


def test_nginx_webhook_proxy_caps_request_body_size() -> None:
    nginx_config = Path("docker/nginx/dashboard.conf").read_text()

    assert "client_max_body_size 10m;" in nginx_config


def test_hosted_caddy_proxy_caps_request_body_size() -> None:
    caddy_config = Path("docker/caddy/Caddyfile").read_text()

    assert "request_body {" in caddy_config
    assert "max_size 10MB" in caddy_config
