"""Forwards /api/* requests to the owning service, with method, path, query and body unchanged.

What the gateway changes on the way:
- Request: removes hop-by-hop headers and any identity or forwarding header a client could
  use to impersonate a user or an internal caller; sets X-Request-ID and X-Forwarded-*.
- Response: passes status codes, bodies and headers through, except that it hides upstream
  internals: an upstream 5xx that isn't a ShopEase error envelope, a body that isn't the JSON
  it claims to be, or an invalid status becomes a gateway error (502); redirects pointing at
  an internal URL are rewritten to a path; server-identifying headers are dropped.
- Failures: connection errors → 503, timeouts → 504, protocol errors → 502. Only GET/HEAD are
  retried, once, and only when the request never reached the service.
"""

import json
import logging
import time

import httpx
from fastapi import Request, Response

from app.config import Upstream
from shopease_shared import ShopEaseError
from shopease_shared.request_id import REQUEST_ID_HEADER

logger = logging.getLogger(__name__)

# Hop-by-hop headers (RFC 9110 §7.6.1).
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
# Headers the gateway sets itself, or that a client must never be able to set.
_STRIP_FROM_REQUEST = _HOP_BY_HOP | {"host", "content-length", "x-request-id", "forwarded", "x-real-ip"}
_SPOOFABLE_PREFIXES = ("x-user-", "x-internal-", "x-service-", "x-forwarded-")
# httpx already decoded the body (length/encoding recomputed); server identity stays private.
_STRIP_FROM_RESPONSE = _HOP_BY_HOP | {"content-encoding", "content-length", "x-request-id", "server", "x-powered-by", "via"}

_SAFE_RETRY_METHODS = {"GET", "HEAD"}


def resolve(path: str, upstreams: list[Upstream]) -> Upstream | None:
    for upstream in upstreams:
        if path == upstream.prefix or path.startswith(upstream.prefix + "/"):
            return upstream
    return None


def _forwardable(name: str) -> bool:
    lowered = name.lower()
    return lowered not in _STRIP_FROM_REQUEST and not lowered.startswith(_SPOOFABLE_PREFIXES)


def _is_envelope(body: bytes) -> bool:
    try:
        parsed = json.loads(body)
    except ValueError:
        return False
    return isinstance(parsed, dict) and isinstance(parsed.get("error"), dict) and "code" in parsed["error"]


def _bad_response(service: str, reason: str) -> ShopEaseError:
    logger.warning("invalid upstream response", extra={"upstream": service, "reason": reason})
    return ShopEaseError(502, "BAD_UPSTREAM_RESPONSE", f"The {service.replace('_', ' ')} returned an invalid response.")


def _check_response(upstream: Upstream, response: httpx.Response) -> None:
    """Refuse to pass on anything that could leak internals or that clients can't parse."""
    if not 200 <= response.status_code <= 599:
        raise _bad_response(upstream.service, f"status {response.status_code}")
    if response.status_code >= 500 and not _is_envelope(response.content):
        # e.g. a crash page or proxy error from inside the network: never shown to clients.
        raise _bad_response(upstream.service, f"unstructured {response.status_code}")
    content_type = response.headers.get("content-type", "")
    if "json" in content_type and response.content:
        try:
            json.loads(response.content)
        except ValueError:
            raise _bad_response(upstream.service, "malformed JSON") from None


async def forward(request: Request, client: httpx.AsyncClient, upstream: Upstream, body: bytes) -> Response:
    url = upstream.base_url.rstrip("/") + request.url.path
    if request.url.query:
        url += "?" + request.url.query

    headers = [(k, v) for k, v in request.headers.items() if _forwardable(k)]
    headers.append((REQUEST_ID_HEADER, request.state.request_id))
    if request.client:
        headers.append(("X-Forwarded-For", request.client.host))
    headers.append(("X-Forwarded-Proto", request.url.scheme))

    service = upstream.service.replace("_", " ")
    attempts = 2 if request.method in _SAFE_RETRY_METHODS else 1
    for attempt in range(1, attempts + 1):
        started = time.perf_counter()
        try:
            upstream_response = await client.request(
                request.method, url, headers=headers, content=body, timeout=upstream.timeout()
            )
            break
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            _log(upstream, "unavailable", started, attempt)
            if attempt < attempts:
                continue  # the request never reached the service: safe to try once more
            raise ShopEaseError(
                503, "SERVICE_UNAVAILABLE", f"The {service} is temporarily unavailable.", headers={"Retry-After": "2"}
            ) from exc
        except httpx.TimeoutException as exc:
            _log(upstream, "timeout", started, attempt)
            raise ShopEaseError(504, "UPSTREAM_TIMEOUT", f"The {service} did not respond in time.") from exc
        except httpx.HTTPError as exc:
            _log(upstream, "protocol_error", started, attempt)
            raise _bad_response(upstream.service, type(exc).__name__) from exc
    _log(upstream, upstream_response.status_code, started, attempt)

    _check_response(upstream, upstream_response)
    response = Response(content=upstream_response.content, status_code=upstream_response.status_code)
    for name, value in upstream_response.headers.multi_items():
        lowered = name.lower()
        if lowered in _STRIP_FROM_RESPONSE:
            continue
        if lowered == "location" and value.startswith(upstream.base_url.rstrip("/")):
            value = value[len(upstream.base_url.rstrip("/")):] or "/"  # never reveal internal hosts
        response.headers.append(name, value)
    return response


def _log(upstream: Upstream, outcome, started: float, attempt: int) -> None:
    # Service name and outcome only: no URLs, query strings or headers (tokens) are logged.
    logger.info(
        "upstream call",
        extra={
            "upstream": upstream.service,
            "outcome": outcome,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "attempt": attempt,
        },
    )
