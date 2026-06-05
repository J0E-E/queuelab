-- nack.lua — handle a failed job: retry with backoff, or fail terminally (TDD §5.3).
--
-- Increasing the attempt count and choosing the next step must happen all-at-once or not at
-- all (atomic), otherwise two failures at the same time could both read the same attempt
-- count and both retry (or both fail).
--
-- Ownership check (fence): only the worker that currently holds this job may fail it. If an
-- out-of-date (stale) failure signal arrives from a worker that has been replaced (superseded)
-- — its claim expired, the recovery sweep (reaper) put the job back on the queue, and another
-- worker may have already grabbed it — we must do nothing and return (no-op). Acting anyway
-- would wrongly remove the new holder's claim entry (`ZREM` the lease), bump their attempt
-- count, and corrupt the state counts. We only act if the job's current worker_id matches.
--
-- KEYS[1] = ql:job:{id}            ARGV[1] = job_id
-- KEYS[2] = ql:processing:{worker} ARGV[2] = worker_id
-- KEYS[3] = ql:leases              ARGV[3] = job_ttl_seconds
-- KEYS[4] = ql:queue:delayed       ARGV[4] = error_message
-- KEYS[5] = ql:counts              ARGV[5] = state-change pub/sub channel
local job_key = KEYS[1]
local processing_key = KEYS[2]
local leases_key = KEYS[3]
local delayed_key = KEYS[4]
local counts_key = KEYS[5]
local job_id = ARGV[1]
local worker_id = ARGV[2]
local ttl_seconds = tonumber(ARGV[3])
local error_msg = ARGV[4]
local channel = ARGV[5]

-- Ownership check (fence): ignore a failure signal from anyone who no longer owns this job.
if redis.call('HGET', job_key, 'worker_id') ~= worker_id then
  return 'stale'
end

local t = redis.call('TIME')
local now_ms = (tonumber(t[1]) * 1000) + math.floor(tonumber(t[2]) / 1000)

redis.call('LREM', processing_key, 0, job_id)
redis.call('ZREM', leases_key, job_id)

-- RETRY-DECISION (keep in sync with reap.lua) -------------------------------------
local attempts = redis.call('HINCRBY', job_key, 'attempts', 1)
local max_retries = tonumber(redis.call('HGET', job_key, 'max_retries'))
local state
if attempts <= max_retries then
  state = 'retrying'
  local retry_delay_ms = tonumber(redis.call('HGET', job_key, 'retry_delay_ms'))
  redis.call('HSET', job_key, 'state', state, 'last_error', error_msg)
  redis.call('HDEL', job_key, 'worker_id')
  redis.call('ZADD', delayed_key, now_ms + retry_delay_ms, job_id)
  redis.call('HINCRBY', counts_key, 'running', -1)
  redis.call('HINCRBY', counts_key, 'retrying', 1)
else
  state = 'failed'
  redis.call('HSET', job_key, 'state', state, 'last_error', error_msg)
  redis.call('HDEL', job_key, 'worker_id')
  redis.call('HINCRBY', counts_key, 'running', -1)
  redis.call('HINCRBY', counts_key, 'failed', 1)
  redis.call('EXPIRE', job_key, ttl_seconds)
end
-- end RETRY-DECISION ---------------------------------------------------------------

local session_id = redis.call('HGET', job_key, 'session_id')
-- The durable-writer (Epic 10a) records these onto the Postgres row. last_error rides every
-- failure; a terminal `failed` also carries the run timing (started_at + finished_at) so the
-- writer can store the finish time and duration. A `retrying` job will run again, so it has no
-- finish time yet — cjson omits the nil fields.
local event = {
  job_id = job_id,
  state = state,
  session_id = session_id,
  attempts = attempts,
  last_error = error_msg,
}
if state == 'failed' then
  event.started_at = tonumber(redis.call('HGET', job_key, 'started_at'))
  event.finished_at = now_ms
end
redis.call('PUBLISH', channel, cjson.encode(event))

return state
