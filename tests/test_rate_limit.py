from __future__ import annotations

import pytest

from yomiage.rate_limit import TokenBucket


def test_consumes_tokens_up_to_capacity() -> None:
    bucket = TokenBucket(capacity=100, refill_amount=10, refill_interval=5.0, tokens=100, now=0.0)
    assert bucket.try_consume(40, now=0.0)
    assert bucket.tokens == 60
    assert bucket.try_consume(60, now=0.0)
    assert bucket.tokens == 0


def test_rejects_consumption_when_insufficient_tokens() -> None:
    bucket = TokenBucket(capacity=100, refill_amount=10, refill_interval=5.0, tokens=5, now=0.0)
    assert not bucket.try_consume(10, now=0.0)
    assert bucket.tokens == 5


def test_refills_after_interval() -> None:
    bucket = TokenBucket(capacity=100, refill_amount=10, refill_interval=5.0, tokens=0, now=0.0)
    assert not bucket.try_consume(1, now=4.9)
    assert bucket.try_consume(10, now=5.0)
    assert bucket.tokens == 0


def test_refills_multiple_periods_at_once() -> None:
    bucket = TokenBucket(capacity=100, refill_amount=10, refill_interval=5.0, tokens=0, now=0.0)
    assert bucket.try_consume(40, now=23.0)
    assert bucket.tokens == 0


def test_does_not_lose_fractional_refill_time() -> None:
    bucket = TokenBucket(capacity=100, refill_amount=10, refill_interval=10.0, tokens=0, now=0.0)
    assert bucket.try_consume(10, now=19.0)
    assert bucket.tokens == 0
    assert bucket.try_consume(10, now=20.0)
    assert bucket.tokens == 0


def test_never_exceeds_capacity() -> None:
    bucket = TokenBucket(capacity=50, refill_amount=1000, refill_interval=1.0, tokens=0, now=0.0)
    bucket._refill(100.0)
    assert bucket.tokens == 50


def test_wait_time_is_zero_when_enough_tokens() -> None:
    bucket = TokenBucket(capacity=100, refill_amount=10, refill_interval=5.0, tokens=50, now=0.0)
    assert bucket.wait_time_seconds(10, now=0.0) == 0.0


def test_wait_time_estimates_required_periods() -> None:
    bucket = TokenBucket(capacity=100, refill_amount=10, refill_interval=5.0, tokens=5, now=0.0)
    assert bucket.wait_time_seconds(30, now=0.0) == 15.0


def test_wait_time_accounts_for_partial_interval() -> None:
    bucket = TokenBucket(capacity=100, refill_amount=10, refill_interval=10.0, tokens=0, now=0.0)
    assert bucket.wait_time_seconds(10, now=9.0) == 1.0


@pytest.mark.parametrize(
    ("capacity", "refill_amount", "refill_interval"),
    [(0, 1, 1.0), (1, 0, 1.0), (1, 1, 0.0), (-1, 1, 1.0)],
)
def test_rejects_invalid_construction(
    capacity: int,
    refill_amount: int,
    refill_interval: float,
) -> None:
    with pytest.raises(ValueError, match=r".+"):
        TokenBucket(capacity=capacity, refill_amount=refill_amount, refill_interval=refill_interval)
