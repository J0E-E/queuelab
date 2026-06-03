-- reap.lua — the recovery sweep that cleans up after failures (TDD §5.3). One all-at-once or
-- not-at-all pass (atomic) so a job can never be both moved to ready and re-claimed at once,
-- and counts move exactly once per job.
--
-- Pass A: move ready delayed jobs back to the active queue (promote) once their retry wait
--         has elapsed.
-- Pass B: put jobs back on the queue (requeue) whose claim deadline (lease) passed — a
--         destroyed/dead worker's in-flight job, treated as a failed attempt (same
--         RETRY-DECISION as nack.lua).
--
-- Single-node assumption: Pass B builds ql:job:{id} and ql:processing:{worker} keys
-- inline (not declared in KEYS), which Redis Cluster forbids.
--
-- max_batch caps EACH pass independently, so one sweep touches at most 2 * max_batch jobs
-- (up to max_batch promotions + up to max_batch recoveries) — a soft per-tick ceiling, not
-- a hard total.
--
-- KEYS[1] = ql:queue:delayed   ARGV[1] = job_ttl_seconds
-- KEYS[2] = ql:queue:ready     ARGV[2] = max_batch (per-pass cap; see header)
-- KEYS[3] = ql:leases          ARGV[3] = state-change pub/sub channel
-- KEYS[4] = ql:counts
local delayed_key = KEYS[1]
local ready_key = KEYS[2]
local leases_key = KEYS[3]
local counts_key = KEYS[4]
local ttl_seconds = tonumber(ARGV[1])
local max_batch = tonumber(ARGV[2])
local channel = ARGV[3]

local t = redis.call('TIME')
local now_ms = (tonumber(t[1]) * 1000) + math.floor(tonumber(t[2]) / 1000)

local promoted = 0
local recovered = 0

-- Pass A — move ready delayed jobs to the active queue (promote) -------------------
local due = redis.call('ZRANGEBYSCORE', delayed_key, 0, now_ms, 'LIMIT', 0, max_batch)
for _, id in ipairs(due) do
  redis.call('ZREM', delayed_key, id)
  local jkey = 'ql:job:' .. id
  redis.call('HSET', jkey, 'state', 'queued')
  redis.call('LPUSH', ready_key, id)
  redis.call('HINCRBY', counts_key, 'retrying', -1)
  redis.call('HINCRBY', counts_key, 'queued', 1)
  local session_id = redis.call('HGET', jkey, 'session_id')
  redis.call('PUBLISH', channel, cjson.encode({
    job_id = id,
    state = 'queued',
    session_id = session_id,
  }))
  promoted = promoted + 1
end

-- Pass B — recover jobs whose claim expired, or lease (dead workers) ---------------
local expired = redis.call('ZRANGEBYSCORE', leases_key, 0, now_ms, 'LIMIT', 0, max_batch)
for _, id in ipairs(expired) do
  redis.call('ZREM', leases_key, id)
  local jkey = 'ql:job:' .. id
  local worker_id = redis.call('HGET', jkey, 'worker_id')
  if worker_id then
    redis.call('LREM', 'ql:processing:' .. worker_id, 0, id)
  end

  -- RETRY-DECISION (keep in sync with nack.lua) ----------------------------------
  local attempts = redis.call('HINCRBY', jkey, 'attempts', 1)
  local max_retries = tonumber(redis.call('HGET', jkey, 'max_retries'))
  local state
  if attempts <= max_retries then
    state = 'retrying'
    local retry_delay_ms = tonumber(redis.call('HGET', jkey, 'retry_delay_ms'))
    redis.call('HSET', jkey, 'state', state, 'last_error', 'lease expired')
    redis.call('HDEL', jkey, 'worker_id')
    redis.call('ZADD', delayed_key, now_ms + retry_delay_ms, id)
    redis.call('HINCRBY', counts_key, 'running', -1)
    redis.call('HINCRBY', counts_key, 'retrying', 1)
  else
    state = 'failed'
    redis.call('HSET', jkey, 'state', state, 'last_error', 'lease expired')
    redis.call('HDEL', jkey, 'worker_id')
    redis.call('HINCRBY', counts_key, 'running', -1)
    redis.call('HINCRBY', counts_key, 'failed', 1)
    redis.call('EXPIRE', jkey, ttl_seconds)
  end
  -- end RETRY-DECISION -----------------------------------------------------------

  local session_id = redis.call('HGET', jkey, 'session_id')
  redis.call('PUBLISH', channel, cjson.encode({
    job_id = id,
    state = state,
    session_id = session_id,
    attempts = attempts,
  }))
  recovered = recovered + 1
end

return {promoted, recovered}
