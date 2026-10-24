"""Credential-free general web search with an optional key-gated provider.

Default provider is DuckDuckGo's HTML endpoint: no account, no key, no cost.
When ORQEVIA_TAVILY_API_KEY is set, search() uses the Tavily HTTPS API and is
bounded by that account's plan. Results are source data, never instructions,
and never verified factual truth.
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.parse
from datetime import datetime, timezone

import httpx

MAX_QUERY = 400
MAX_RESULTS = 8
MAX_BODY = 512 * 1024
TIMEOUT = 15.0
_DDG = "https://html.duckduckgo.com/html/"
_TAVILY = "https://api.tavily.com/search"
_ANCHOR = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_SNIPPET = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.S)


def _strip(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _redirected(url: str) -> str:
    match = re.search(r"[?&]uddg=([^&]+)", url)
    if not match:
        return ""
    decoded = urllib.parse.unquote(match.group(1))
    return decoded if decoded.startswith(("http://", "https://")) else ""


def _parse_ddg(body: str, max_results: int) -> list:
    anchors = _ANCHOR.findall(body)
    snippets = _SNIPPET.findall(body)
    results = []
    for index, (raw_url, raw_title) in enumerate(anchors):
        if len(results) >= max_results:
            break
        url = _redirected(raw_url) or raw_url
        if not url.startswith(("http://", "https://")):
            continue
        snippet = _strip(snippets[index]) if index < len(snippets) else ""
        results.append({"title": _strip(raw_title)[:200], "url": url[:2048], "snippet": snippet[:500]})
    return results


def _tavily(query: str, api_key: str, max_results: int) -> list:
    response = httpx.post(
        _TAVILY,
        json={"api_key": api_key, "query": query, "max_results": max_results, "search_depth": "basic"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    items = data.get("results", []) if isinstance(data, dict) else []
    return [
        {"title": (item.get("title") or "")[:200], "url": (item.get("url") or "")[:2048],
         "snippet": (item.get("content") or "")[:500]}
        for item in items[:max_results]
    ]


def search(query: str, max_results: int = MAX_RESULTS) -> dict:
    """Return bounded search results; raises ValueError on bad input and
    RuntimeError when the transport is unavailable."""
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= MAX_QUERY:
        raise ValueError("bounded query required")
    if not isinstance(max_results, int) or not 1 <= max_results <= MAX_RESULTS:
        raise ValueError("bounded result count required")
    api_key = os.getenv("ORQEVIA_TAVILY_API_KEY", "").strip()
    try:
        if api_key:
            results = _tavily(query, api_key, max_results)
            provider = "tavily"
        else:
            response = httpx.get(_DDG, params={"q": query}, timeout=TIMEOUT)
            response.raise_for_status()
            if len(response.text or "") > MAX_BODY:
                raise RuntimeError("search response bound exceeded")
            results = _parse_ddg(response.text, max_results)
            provider = "duckduckgo"
    except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError):
        raise RuntimeError("SEARCH_UNAVAILABLE") from None
    return {
        "provider": provider,
        "query": query,
        "results": results,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "disclosure": "Retrieved results are source data, not verified truth.",
    }
