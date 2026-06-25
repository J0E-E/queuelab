"""Server-side guest-session store: bind a session id to its issued identity (TDD §5.8).

The guest identity handed out by ``POST /api/session`` is throwaway, but the api still has
to *trust* it. Without a server-side record, a client could submit jobs under any
``guest_handle`` it liked, or rotate ``session_id`` freely to dodge the per-session rate
limit. So when a session is minted we persist ``session_id -> {guest_handle, color}`` here,
and the submission endpoint reads the handle back from this store rather than believing the
request body. Records carry a TTL so abandoned sessions self-clean.

It mirrors :class:`app.services.rate_limit.RateLimiter` (injected Redis, ``from_settings``,
``aclose``) and shares the ``ql:`` key namespace.
"""

from __future__ import annotations

from redis.asyncio import Redis

from app.config import settings
from app.services.identity import GuestIdentity


def session_key(session_id: str) -> str:
    """Return the Redis key holding one guest session's issued identity."""
    return f"ql:session:{session_id}"


class SessionStore:
    """Records each issued guest identity so the api can trust a session id later on."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @classmethod
    def from_settings(cls) -> SessionStore:
        """Build a store against the configured Redis URL."""
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        return cls(redis)

    async def aclose(self) -> None:
        """Close the underlying Redis connection pool."""
        await self._redis.aclose()

    async def save(self, identity: GuestIdentity) -> None:
        """Store a freshly minted identity with a TTL so an abandoned session self-cleans.

        The write and its expiry go out as one ``MULTI``/``EXEC`` transaction, so a session
        record can never be left without a TTL (which would leak the key forever).
        """
        key = session_key(identity.session_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hset(key, mapping={"guest_handle": identity.guest_handle, "color": identity.color})
            pipe.expire(key, settings.session_ttl_seconds)
            await pipe.execute()

    async def get_handle(self, session_id: str) -> str | None:
        """Return the guest handle bound to this session, or ``None`` if unknown/expired."""
        return await self._redis.hget(session_key(session_id), "guest_handle")

    async def get_identity(self, session_id: str) -> dict[str, str] | None:
        """Return the ``{handle, color}`` bound to this session, or ``None`` if unknown/expired.

        The activity feed (Epic 17b) resolves an action's acting guest from its ``session_id``
        here — server-side, so the color attribution can't be spoofed by a client supplying its
        own handle. Returns the issued handle and its hex color together, since the feed colors
        both the handle and the whole line from them.
        """
        record = await self._redis.hgetall(session_key(session_id))
        if not record:
            return None
        return {"handle": record["guest_handle"], "color": record["color"]}
