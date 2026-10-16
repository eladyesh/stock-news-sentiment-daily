"""Bounded public GETs; never pass Telegram credentials to collectors."""
from __future__ import annotations

import ipaddress
import json
import socket
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

USER_AGENT = "StockNewsSentimentDaily/0.1 (+https://github.com/eladyesh/stock-news-sentiment-daily)"


def public_url(url: str) -> None:
    p = urlsplit(url)
    if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
        raise ValueError("Invalid public source URL")
    if p.port not in {None, 80, 443}:
        raise ValueError("Nonstandard source port")
    if p.hostname.lower() == "localhost" or p.hostname.lower().endswith((".localhost", ".local", ".internal")):
        raise ValueError("Non-public source hostname")
    try:
        literal = ipaddress.ip_address(p.hostname)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise ValueError("Non-public source address")
    try:
        addresses = socket.getaddrinfo(p.hostname, p.port or 443)
    except socket.gaierror:
        # Some managed HTTPS transports resolve public hostnames at the proxy.
        # Literal/private host checks still apply; the transport retains its own egress rules.
        return
    if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
        raise ValueError("Non-public source address")


class PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Client:
    def __init__(self, timeout: float = 15):
        self.timeout = timeout
        self.lock = threading.Lock()
        self.next_request: dict[str, float] = {}

    def get(self, url: str, *, max_bytes: int = 3_000_000) -> tuple[bytes, str, str]:
        public_url(url)
        host = urlsplit(url).hostname or ""
        gap = 5.2 if "gdeltproject" in host else 0.6
        with self.lock:
            due = max(time.monotonic(), self.next_request.get(host, 0))
            self.next_request[host] = due + gap
        time.sleep(max(0, due - time.monotonic()))
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        # Public RSS and APIs only. No proxy rotation, challenge solving or paywall bypass.
        with build_opener(PublicRedirect()).open(request, timeout=self.timeout) as result:
            data = result.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError("Source exceeded response-size limit")
            return data, result.geturl(), result.headers.get("Content-Type", "")

    def json(self, url: str):
        return json.loads(self.get(url)[0])


def error_label(error: Exception) -> str:
    if isinstance(error, HTTPError):
        return f"HTTP {error.code}; source unavailable in this run"
    # Do not print arbitrary URLs or exception bodies, which can contain secrets.
    return f"{type(error).__name__}; source unavailable in this run"
