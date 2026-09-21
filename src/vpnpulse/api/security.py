"""Small, process-local HTTP guards for the production API."""
from __future__ import annotations

import hashlib
import secrets
from collections import OrderedDict
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    """Token buckets keyed by a salted, in-memory digest of the client address."""

    def __init__(self, now, max_keys: int = 10_000):
        self.now = now
        self.max_keys = max_keys
        self.salt = secrets.token_bytes(32)
        self.buckets: OrderedDict[tuple[str, bytes], _Bucket] = OrderedDict()

    def allow(self, route: str, address: str, per_minute: int) -> tuple[bool, int]:
        key = (route, hashlib.sha256(self.salt + address.encode("utf-8", "replace")).digest())
        current = self.now().timestamp()
        bucket = self.buckets.pop(key, None)
        if bucket is None:
            bucket = _Bucket(float(per_minute), current)
        else:
            elapsed = max(0.0, current - bucket.updated)
            bucket.tokens = min(float(per_minute), bucket.tokens + elapsed * per_minute / 60.0)
            bucket.updated = current
        allowed = bucket.tokens >= 1.0
        if allowed:
            bucket.tokens -= 1.0
        self.buckets[key] = bucket
        while len(self.buckets) > self.max_keys:
            self.buckets.popitem(last=False)
        retry_after = max(1, int((1.0 - bucket.tokens) * 60.0 / per_minute + 0.999))
        return allowed, retry_after


def client_address(request) -> str:
    peer = request.client.host if request.client else "unknown"
    if peer == "127.0.0.1":
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded
    return peer
