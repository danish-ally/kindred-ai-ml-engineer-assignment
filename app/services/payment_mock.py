from dataclasses import dataclass
from threading import Lock

from app.config import settings


class PaymentTimeoutError(Exception):
    """Raised when the (mock) payment provider times out with an ambiguous
    response — the caller does not know whether the charge went through."""


@dataclass
class ChargeResult:
    status: str  # "succeeded" | "failed"


class PaymentMockClient:
    def __init__(self) -> None:
        # Every attempted charge, in order — a stand-in for the provider's own
        # ledger, useful for proving a bug caused two real-world charges.
        self.charge_log: list[int] = []
        self._idempotent_results: dict[str, ChargeResult] = {}
        self._lock = Lock()

    def charge(self, amount_cents: int, idempotency_key: str | None = None) -> ChargeResult:
        with self._lock:
            if idempotency_key is not None and idempotency_key in self._idempotent_results:
                return self._idempotent_results[idempotency_key]

            self.charge_log.append(amount_cents)
            if amount_cents == settings.payment_timeout_trigger_cents:
                raise PaymentTimeoutError("provider timed out")
            if amount_cents <= 0:
                result = ChargeResult(status="failed")
            else:
                result = ChargeResult(status="succeeded")

            if idempotency_key is not None:
                self._idempotent_results[idempotency_key] = result
            return result

    def reset(self) -> None:
        with self._lock:
            self.charge_log.clear()
            self._idempotent_results.clear()


payment_mock_client = PaymentMockClient()
