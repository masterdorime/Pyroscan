"""One outbound GET, with typed errors and credential redaction. No retries."""
from __future__ import annotations

import json

import requests

from .base import ProviderError
from .config import redact

HEADERS = {"User-Agent": "PyroScan/0.1 (+local research console)"}


def get_text(url: str, params: dict | None = None, *, timeout: int,
             secret: str | None = None, fetcher=None) -> str:
    """Fetch a URL as text. `fetcher` exists so tests never touch the network."""
    caller = fetcher or requests.get
    try:
        resp = caller(url, params=params, timeout=timeout, headers=HEADERS)
    except requests.RequestException as exc:
        raise ProviderError(
            "network", redact(f"{type(exc).__name__}: {exc}", secret)
        ) from None
    if resp.status_code >= 400:
        raise ProviderError(
            "http", redact(f"HTTP {resp.status_code} for {url}", secret)
        )
    return resp.text


def get_json(url: str, params: dict | None = None, *, timeout: int,
             secret: str | None = None, fetcher=None) -> dict:
    text = get_text(url, params, timeout=timeout, secret=secret, fetcher=fetcher)
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise ProviderError("parse", redact(f"not JSON: {exc}", secret)) from None
    if not isinstance(payload, dict):
        raise ProviderError("parse", "expected a JSON object")
    return payload
