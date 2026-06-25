-- ack.lua — mark a successfully finished job `completed` (TDD §5.3).
--
-- Clearing the in-flight claim (the processing list + the time-limited claim, or lease) and
-- marking the job completed must happen all-at-once or not at all (atomic), else the recovery
-- sweep (reaper) could put a job back on the queue (requeue) that has already finished.
--
-- Ownership check (fence): only the worker that currently holds this job may finish it. If an
-- out-of-date (stale) finish signal arrives from a worker that has been replaced (superseded)
-- — its claim expired, the reaper put the job back on the queue, and another worker may have
-- already grabbed it — we must do nothing and return (no-op). Acting anyway would wrongly
-- remove the new holder's claim entry (`ZREM` the lease), mark their in-flight job completed,
-- and subtract from the `running` count twice. We only act if the job's current worker_id matches.
--
-- KEYS[1] = ql:job:{id}            ARGV[1] = job_id
-- KEYS[2] = ql:processing:{worker} ARGV[2] = worker_id
-- KEYS[3] = ql:leases              ARGV[3] = job_ttl_seconds
-- KEYS[4] = ql:counts              ARGV[4] = state-change pub/sub channel
local job_key = KEYS[1]
local processing_key = KEYS[2]
local leases_key = KEYS[3]
local counts_key = KEYS[4]
local job_id = ARGV[1]
local worker_id = ARGV[2]
local ttl_seconds = tonumber(ARGV[3])
local channel = ARGV[4]

-- Ownership check (fence): ignore a finish signal from anyone who no longer owns this job.
if redis.call('HGET', job_key, 'worker_id') ~= worker_id then
  return 'stale'
end

local t = redis.call('TIME')
local now_ms = (tonumber(t[1]) * 1000) + math.floor(tonumber(t[2]) / 1000)

redis.call('LREM', processing_key, 0, job_id)
redis.call('ZREM', leases_key, job_id)
redis.call('HSET', job_key, 'state', 'completed', 'completed_at', now_ms)
redis.call('HDEL', job_key, 'worker_id')
redis.call('HINCRBY', counts_key, 'running', -1)
redis.call('HINCRBY', counts_key, 'completed', 1)
-- A completion after one or more failed attempts is a recovery (a nack retry or a reaper requeue
-- that eventually succeeded). Tally it separately so the dashboard can show how many failures were
-- ultimately recovered — a cumulative subset of `completed`. attempts is bumped only by nack.lua /
-- reap.lua, so attempts > 0 here means this job failed at least once before this success.
if (tonumber(redis.call('HGET', job_key, 'attempts')) or 0) > 0 then
  redis.call('HINCRBY', counts_key, 'recovered', 1)
end
-- Hot record ages out after 1h; the durable copy lives in Postgres (Epic 4).
redis.call('EXPIRE', job_key, ttl_seconds)

local session_id = redis.call('HGET', job_key, 'session_id')
local started_at = tonumber(redis.call('HGET', job_key, 'started_at'))
-- Carry worker_id (the owner the fence above matched) on the completed event too, so the
-- durable-writer (Epic 10a) records who ran the job even if it never saw the `running` event
-- — e.g. a writer that started after the claim. We HDEL it from the hash above, but the local
-- still holds it.
redis.call('PUBLISH', channel, cjson.encode({
  job_id = job_id,
  state = 'completed',
  session_id = session_id,
  worker_id = worker_id,
  started_at = started_at,
  completed_at = now_ms,
}))

return now_ms
