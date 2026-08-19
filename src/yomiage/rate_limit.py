"""Pure, Discord-independent token bucket rate limiter."""

from __future__ import annotations

import time


class TokenBucket:
    """Token bucket that refills in fixed-size periods without losing fractional time.

    ``capacity`` is the maximum number of tokens the bucket can hold, ``refill_amount``
    is how many tokens are added every ``refill_interval`` seconds. Time is measured
    with ``time.monotonic()`` by default (overridable via ``now`` for tests) so system
    clock changes cannot affect refill timing.
    """

    def __init__(
        self,
        capacity: int,
        refill_amount: int,
        refill_interval: float,
        *,
        tokens: int | None = None,
        now: float | None = None,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if refill_amount <= 0:
            raise ValueError("refill_amount must be > 0")
        if refill_interval <= 0:
            raise ValueError("refill_interval must be > 0")

        self.capacity = capacity
        self.refill_amount = refill_amount
        self.refill_interval = refill_interval
        self.tokens = min(tokens, capacity) if tokens is not None else capacity
        self._last_refill = now if now is not None else time.monotonic()

    def _refill(self, now: float) -> None:
        elapsed = now - self._last_refill
        if elapsed < self.refill_interval:
            return
        periods = int(elapsed // self.refill_interval)
        self.tokens = min(self.capacity, self.tokens + periods * self.refill_amount)
        self._last_refill += periods * self.refill_interval

    def try_consume(self, amount: int, *, now: float | None = None) -> bool:
        """Attempt to consume ``amount`` tokens. Returns True if successful."""
        current = now if now is not None else time.monotonic()
        self._refill(current)
        if self.tokens < amount:
            return False
        self.tokens -= amount
        return True

    def wait_time_seconds(self, amount: int, *, now: float | None = None) -> float:
        """Estimate how many seconds until ``amount`` tokens are available."""
        current = now if now is not None else time.monotonic()
        self._refill(current)
        if self.tokens >= amount:
            return 0.0
        shortage = amount - self.tokens
        periods = -(-shortage // self.refill_amount)
        next_available_at = self._last_refill + periods * self.refill_interval
        return max(0.0, next_available_at - current)
