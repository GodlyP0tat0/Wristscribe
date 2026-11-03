"""Helpers shared by the OpenAI-compatible API clients (speech-to-text and cleanup)."""

from __future__ import annotations

import requests


def describe_error(resp: requests.Response, service: str) -> str:
    """Turn an error response into a short message a user can act on."""
    try:
        detail = resp.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        detail = resp.text[:200]
    if resp.status_code == 401:
        return f"{service} rejected the API key: {detail}"
    if resp.status_code == 429:
        return f"{service} rate limit hit, try again shortly: {detail}"
    return f"{service} error {resp.status_code}: {detail}"
