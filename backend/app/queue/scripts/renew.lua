-- renew.lua — extend the claim deadline (lease) for a still-running job (TDD §5.3).
--
-- A worker running a long job re-stamps its lease before the deadline passes, so the recovery
-- sweep (reaper) doesn't mistake a slow-but-alive worker for a dead one and put the job back
-- on the queue (requeue) while it is still being worked. Only the lease deadline moves; the
-- job stays `running`, so counts and the state channel are untouched (renewing is not a state
-- change).
--
-- Ownership check (fence): only the worker that currently holds this job may renew it. A stale
-- renew from a superseded worker (its lease already expired, the reaper requeued the job and
-- cleared worker_id, perhaps to another worker) does nothing and returns (no-op) — re-adding
-- the lease would resurrect a claim the worker no longer owns. Mirrors ack.lua / nack.lua.
--
-- KEYS[1] = ql:job:{id}   ARGV[1] = job_id
-- KEYS[2] = ql:leases     ARGV[2] = worker_id
--                         ARGV[3] = visibility_timeout_ms
local job_key = KEYS[1]
local leases_key = KEYS[2]
local job_id = ARGV[1]
local worker_id = ARGV[2]
local visibility_ms = tonumber(ARGV[3])

-- Ownership check (fence): ignore a renew from anyone who no longer owns this job.
if redis.call('HGET', job_key, 'worker_id') ~= worker_id then
  return 'stale'
end

-- Single authoritative clock: Redis TIME, never the caller's wall clock.
local t = redis.call('TIME')
local now_ms = (tonumber(t[1]) * 1000) + math.floor(tonumber(t[2]) / 1000)

local new_deadline = now_ms + visibility_ms
redis.call('ZADD', leases_key, new_deadline, job_id)
return new_deadline
