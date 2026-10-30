"""HTTP clients for order_service and auth_service (service tokens).

Reliability rules (docs/service_communication.md §3-4, docs/order_workflow.md):
- Every call has a connect timeout and a read timeout, capped by the caller's deadline.
- Retries are bounded (at most one) and only for calls that are safe to repeat: the payable
  read. Result reports are not retried inline; the background job retries them later.
- Connection failures (the request never arrived) may be retried for any call.
- Errors are mapped to DependencyError so the caller decides how to compensate.
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings
from shopease_shared.request_id import REQUEST_ID_HEADER, get_request_id

logger = logging.getLogger(__name__)


class DependencyError(Exception):
    """A dependency failed. `kind`: timeout (outcome unknown), unavailable, or bad_response."""

    def __init__(self, service: str, kind: str, detail: str = "") -> None:
        super().__init__(f"{service} {kind} {detail}".strip())
        self.service, self.kind = service, kind


@dataclass
class Deadline:
    """Remaining time budget for one request; a retry happens only if it still fits."""

    expires_at: float

    @classmethod
    def after(cls, seconds: float) -> "Deadline":
        return cls(time.monotonic() + seconds)

    def remaining(self) -> float:
        return self.expires_at - time.monotonic()


NO_DEADLINE = Deadline(float("inf"))


class ServiceClients:
    def __init__(self, settings: Settings, http: httpx.Client) -> None:
        self.settings = settings
        self.http = http
        self._token: str | None = None
        self._token_expires = 0.0
        self._token_lock = threading.Lock()

    # --- Service token (client credentials, cached until shortly before expiry) ----------

    def _service_token(self, force_refresh: bool = False) -> str:
        with self._token_lock:
            if not force_refresh and self._token and time.monotonic() < self._token_expires - 30:
                return self._token
            response = self._send(
                "auth_service",
                "POST",
                f"{self.settings.auth_service_url}/internal/auth/service-token",
                json={
                    "client_id": self.settings.service_client_id,
                    "client_secret": self.settings.service_client_secret.get_secret_value(),
                },
                timeout=self.settings.service_token_timeout,
                retry=True,
                deadline=NO_DEADLINE,
            )
            if response.status_code != 200:
                logger.error("service token request rejected", extra={"status": response.status_code})
                raise DependencyError("auth_service", "unavailable", f"status {response.status_code}")
            body = response.json()
            self._token = body["access_token"]
            self._token_expires = time.monotonic() + float(body["expires_in"])
            return self._token

    # --- Transport with timeouts and bounded retries ---------------------------------------

    def _send(
        self,
        service: str,
        method: str,
        url: str,
        *,
        timeout: float,
        retry: bool,
        deadline: Deadline,
        **kwargs: Any,
    ) -> httpx.Response:
        """One attempt, plus one more if `retry` and the deadline allows it.

        Connection failures are retried even when `retry` is False: the request never
        reached the service. Read timeouts and 502/503/504 are retried only when `retry`.
        """
        attempts = 2
        last: DependencyError | None = None
        for attempt in range(1, attempts + 1):
            budget = min(timeout, deadline.remaining())
            if budget < 0.2:
                raise last or DependencyError(service, "timeout", "deadline exhausted")
            headers = {REQUEST_ID_HEADER: get_request_id() or "", **kwargs.pop("headers", {})}
            started = time.monotonic()
            try:
                response = self.http.request(
                    method,
                    url,
                    headers=headers,
                    timeout=httpx.Timeout(budget, connect=min(self.settings.connect_timeout, budget)),
                    **kwargs,
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last = DependencyError(service, "unavailable", type(exc).__name__)
                outcome = "connect_failed"
            except httpx.TimeoutException as exc:
                last = DependencyError(service, "timeout", type(exc).__name__)
                outcome = "timeout"
                if not retry:
                    self._log(service, method, url, outcome, started, attempt)
                    raise last from exc
            except httpx.HTTPError as exc:
                self._log(service, method, url, "error", started, attempt)
                raise DependencyError(service, "bad_response", type(exc).__name__) from exc
            else:
                self._log(service, method, url, response.status_code, started, attempt)
                if response.status_code in (502, 503, 504) and retry and attempt < attempts:
                    last = DependencyError(service, "unavailable", f"status {response.status_code}")
                    kwargs["headers"] = headers
                    continue
                if response.status_code >= 500:
                    kind = "timeout" if response.status_code == 504 else "unavailable"
                    raise DependencyError(service, kind, f"status {response.status_code}")
                return response
            self._log(service, method, url, outcome, started, attempt)
            kwargs["headers"] = headers
        raise last  # type: ignore[misc]

    @staticmethod
    def _log(service: str, method: str, url: str, outcome: Any, started: float, attempt: int) -> None:
        logger.info(
            "dependency call",
            extra={
                "dependency": service,
                "method": method,
                "path": httpx.URL(url).path,
                "outcome": outcome,
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
                "attempt": attempt,
            },
        )

    def _internal(
        self, service: str, method: str, url: str, *, timeout: float, retry: bool, deadline: Deadline, **kwargs: Any
    ) -> httpx.Response:
        """Call an /internal endpoint with a service token; refresh it once if it was rejected."""
        extra_headers = kwargs.pop("headers", {})
        for refresh in (False, True):
            headers = {"Authorization": f"Bearer {self._service_token(force_refresh=refresh)}", **extra_headers}
            response = self._send(service, method, url, timeout=timeout, retry=retry, deadline=deadline,
                                  headers=headers, **kwargs)
            if response.status_code != 401:
                return response
        logger.error("service token rejected twice", extra={"dependency": service})
        raise DependencyError(service, "unavailable", "service token rejected")

    # --- order_service ---------------------------------------------------------------------

    def payable(self, order_id: uuid.UUID, deadline: Deadline = NO_DEADLINE) -> httpx.Response:
        return self._internal(
            "order_service", "GET", f"{self.settings.order_service_url}/internal/orders/{order_id}/payable",
            timeout=self.settings.payable_timeout, retry=True, deadline=deadline,
        )

    def report_result(
        self, order_id: uuid.UUID, payment_id: uuid.UUID, outcome: str, reason: str | None = None
    ) -> httpx.Response:
        # order_service applies results idempotently, but a lost answer is handled by the
        # background retry rather than an inline one, to keep the client's request short.
        return self._internal(
            "order_service", "POST", f"{self.settings.order_service_url}/internal/orders/{order_id}/payment-result",
            json={"payment_id": str(payment_id), "outcome": outcome, "reason": reason},
            timeout=self.settings.payment_result_timeout, retry=False, deadline=NO_DEADLINE,
        )
