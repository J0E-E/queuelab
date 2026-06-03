-- claim.lua — transition an already-popped job to `running` (TDD §5.3).
--
-- The blocking grab-and-move (`BLMOVE`, ready -> processing:{worker}) runs in Python; this
-- script runs all-at-once or not at all (atomic) right after, for the worker that won the
-- pop. It stamps the claim deadline (the lease) and changes the state in one step so the
-- recovery sweep (reaper) can never see a half-claimed job.
--
-- KEYS[1] = ql:job:{id}      ARGV[1] = job_id
-- KEYS[2] = ql:leases        ARGV[2] = worker_id
-- KEYS[3] = ql:counts        ARGV[3] = visibility_timeout_ms
--                            ARGV[4] = state-change pub/sub channel
local job_key = KEYS[1]
local leases_key = KEYS[2]
local counts_key = KEYS[3]
local job_id = ARGV[1]
local worker_id = ARGV[2]
local visibility_ms = tonumber(ARGV[3])
local channel = ARGV[4]

-- Single authoritative clock: Redis TIME, never the caller's wall clock.
local t = redis.call('TIME')
local now_ms = (tonumber(t[1]) * 1000) + math.floor(tonumber(t[2]) / 1000)

redis.call('HSET', job_key, 'state', 'running', 'worker_id', worker_id, 'started_at', now_ms)
redis.call('ZADD', leases_key, now_ms + visibility_ms, job_id)
redis.call('HINCRBY', counts_key, 'queued', -1)
redis.call('HINCRBY', counts_key, 'running', 1)

local session_id = redis.call('HGET', job_key, 'session_id')
redis.call('PUBLISH', channel, cjson.encode({
  job_id = job_id,
  state = 'running',
  session_id = session_id,
  worker_id = worker_id,
  started_at = now_ms,
}))

return now_ms
