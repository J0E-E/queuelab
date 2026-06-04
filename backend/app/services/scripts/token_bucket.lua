-- token_bucket.lua — per-session rate limiter as a token bucket (TDD §5.9).
--
-- A bucket holds at most `capacity` tokens and gains one token every `refill_ms`
-- milliseconds. Each allowed action spends `cost` tokens; when the bucket is empty the
-- action is denied and the caller is told how long to wait. Checking the level, refilling,
-- and spending must happen all-at-once or not at all (atomic), so two requests from the
-- same session in the same instant can't both read "1 token left" and both be allowed.
--
-- Single authoritative clock: time comes from `redis.call('TIME')`, never the caller's
-- wall clock, so every api process sees one consistent schedule.
--
-- With capacity = 1 (the configured submit/chaos limits) there is no burst: one action,
-- then a full `refill_ms` wait before the next — exactly "1 submission / 5s".
--
-- KEYS[1] = ql:ratelimit:{action}:{session_id}   ARGV[1] = capacity (max tokens)
--                                                ARGV[2] = refill_ms (ms to gain 1 token)
--                                                ARGV[3] = cost (tokens this action spends)
-- Returns: { allowed (1 or 0), retry_after_ms } — retry_after_ms is 0 when allowed.
local bucket_key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_ms = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])

local t = redis.call('TIME')
local now_ms = (tonumber(t[1]) * 1000) + math.floor(tonumber(t[2]) / 1000)

-- Read the stored level, or start from a full bucket the first time this session acts.
local tokens = tonumber(redis.call('HGET', bucket_key, 'tokens'))
local updated_at_ms = tonumber(redis.call('HGET', bucket_key, 'updated_at_ms'))
if tokens == nil or updated_at_ms == nil then
  tokens = capacity
  updated_at_ms = now_ms
end

-- Add the tokens earned since the last check (time elapsed / refill rate), capped at full.
local elapsed_ms = now_ms - updated_at_ms
if elapsed_ms > 0 then
  tokens = math.min(capacity, tokens + (elapsed_ms / refill_ms))
end

local allowed = 0
local retry_after_ms = 0
if tokens >= cost then
  allowed = 1
  tokens = tokens - cost
else
  -- Round up the wait for the missing tokens to the next whole millisecond.
  retry_after_ms = math.ceil((cost - tokens) * refill_ms)
end

redis.call('HSET', bucket_key, 'tokens', tokens, 'updated_at_ms', now_ms)
-- Self-clean idle buckets: expire after the time to refill from empty to full
-- (capacity * refill_ms). By then any surviving bucket would be at least full again, and a
-- fresh full bucket is equivalent — so expiring changes nothing (a no-op on behavior) and
-- keeps Redis from accumulating keys for sessions that have gone quiet.
redis.call('PEXPIRE', bucket_key, math.ceil(capacity * refill_ms))

return { allowed, retry_after_ms }
