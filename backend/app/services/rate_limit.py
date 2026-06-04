"""Per-session rate limiting with a Redis token bucket (TDD §5.9).

Anyone can act on the shared system, so each session is held to a steady pace: **1 job
submission / 5s** and **1 chaos action / 10s**. The actual bucket math lives in
``scripts/token_bucket.lua`` and runs all-at-once or not at all (atomic) inside Redis, using
Redis ``TIME`` as the one clock; this client just registers that script and exposes a small
typed API. It mirrors :class:`app.queue.client.JobQueue` (injected Redis, ``from_settings``).

A denied action raises :class:`app.services.guardrails.RateLimitedError`, which the app's
guardrail handlers turn into a ``429`` with a ``Retry-After`` header.
"""

from __future__ import annotations

import math
from pathlib import Path

from redis.asyncio import Redis
from redis.commands.core import AsyncScript

from app.config import settings
from app.services.guardrails import RateLimitedError

# A bucket holds at most one token (no burst): one action, then a full interval's wait.
BUCKET_CAPACITY = 1

_SCRIPTS_DIR = Path(__file__).parent / "scripts"

# Read the Lua source once at import; each RateLimiter registers it on its own client.
_TOKEN_BUCKET_SOURCE = (_SCRIPTS_DIR / "token_bucket.lua").read_text(encoding="utf-8")


def bucket_key(action: str, session_id: str) -> str:
    """Return the Redis key holding one session's bucket for one action.

    Submit and chaos use separate keys so spending a submit token never touches the chaos
    budget (and vice versa).
    """
    return f"ql:ratelimit:{action}:{session_id}"


class RateLimiter:
    """Per-session token-bucket rate limiter, as an async, dependency-injectable client."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        # register_script returns a callable that runs the script by its hash (`EVALSHA`) and
        # re-uploads it on a cold Redis (`NOSCRIPT`), so a Redis restart self-heals.
        self._token_bucket: AsyncScript = redis.register_script(_TOKEN_BUCKET_SOURCE)

    @classmethod
    def from_settings(cls) -> RateLimiter:
        """Build a limiter against the configured Redis URL."""
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        return cls(redis)

    async def aclose(self) -> None:
        """Close the underlying Redis connection pool."""
        await self._redis.aclose()

    async def check_submission(self, session_id: str) -> None:
        """Allow one job submission per ``submit_rate_seconds`` for this session.

        Returns without raising when the submission is allowed. Raises
        :class:`RateLimitedError` (shaped to ``429``) when the session is going too fast, with
        a ``[WARN] rate limit: 1 submission / Ns`` message.
        """
        rate = settings.submit_rate_seconds
        await self._check(
            action="submit",
            session_id=session_id,
            refill_seconds=rate,
            denied_message=f"[WARN] rate limit: 1 submission / {rate}s",
        )

    async def check_session(self, client_ip: str) -> None:
        """Allow one session minting per ``session_rate_seconds`` for this client IP.

        Keyed by IP (not session id — there is no session yet) so a caller can't rotate fresh
        identities faster than it could submit. Returns without raising when allowed; raises
        :class:`RateLimitedError` (shaped to ``429``) when the IP is going too fast.
        """
        rate = settings.session_rate_seconds
        await self._check(
            action="session",
            session_id=client_ip,
            refill_seconds=rate,
            denied_message=f"[WARN] rate limit: 1 session / {rate}s",
        )

    async def check_chaos(self, session_id: str) -> None:
        """Allow one chaos action per ``chaos_rate_seconds`` for this session.

        Returns without raising when the action is allowed. Raises :class:`RateLimitedError`
        (shaped to ``429``) when the session is going too fast, with a
        ``[WARN] rate limit: 1 chaos action / Ns`` message.
        """
        rate = settings.chaos_rate_seconds
        await self._check(
            action="chaos",
            session_id=session_id,
            refill_seconds=rate,
            denied_message=f"[WARN] rate limit: 1 chaos action / {rate}s",
        )

    async def _check(
        self, action: str, session_id: str, refill_seconds: int, denied_message: str
    ) -> None:
        """Spend one token for ``action`` from this session's bucket, or deny and explain.

        Returns without raising when a token was spent (allowed). When the bucket is empty,
        converts the script's millisecond wait into whole seconds (rounded up, at least 1) for
        the ``Retry-After`` header and raises :class:`RateLimitedError`. This raise-or-pass
        contract matches the other guardrail checks in :mod:`app.services.validation`.
        """
        allowed, retry_after_ms = await self._token_bucket(
            keys=[bucket_key(action, session_id)],
            args=[BUCKET_CAPACITY, refill_seconds * 1000, 1],
        )
        if int(allowed) == 1:
            return

        retry_after_seconds = max(1, math.ceil(int(retry_after_ms) / 1000))
        raise RateLimitedError(retry_after_seconds, denied_message)
