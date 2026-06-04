-- requeue.lua — cleanly return an in-flight job to the ready queue (TDD §5.4).
--
-- Used by a worker's graceful SIGTERM shutdown: it stops claiming, hands its in-flight job
-- straight back to ``ql:queue:ready`` as ``queued``, and exits. Unlike nack.lua this is NOT a
-- failed attempt — it **never touches `attempts`**, so an intentional drain never burns a
-- retry or fails a last-attempt job. Clearing the in-flight claim (processing list + lease)
-- and re-queuing must happen all-at-once or not at all (atomic), else the recovery sweep
-- (reaper) could act on a job that is already back on the queue.
--
-- Ownership check (fence): only the worker that currently holds this job may requeue it. If
-- an out-of-date (stale) requeue arrives from a worker that has been replaced (superseded) —
-- its claim expired, the reaper put the job back on the queue, and another worker may have
-- already grabbed it — we must do nothing and return (no-op). Mirrors ack.lua / nack.lua.
--
-- KEYS[1] = ql:job:{id}            ARGV[1] = job_id
-- KEYS[2] = ql:processing:{worker} ARGV[2] = worker_id
-- KEYS[3] = ql:leases              ARGV[3] = state-change pub/sub channel
-- KEYS[4] = ql:queue:ready
-- KEYS[5] = ql:counts
local job_key = KEYS[1]
local processing_key = KEYS[2]
local leases_key = KEYS[3]
local ready_key = KEYS[4]
local counts_key = KEYS[5]
local job_id = ARGV[1]
local worker_id = ARGV[2]
local channel = ARGV[3]

-- Ownership check (fence): ignore a requeue from anyone who no longer owns this job.
if redis.call('HGET', job_key, 'worker_id') ~= worker_id then
  return 'stale'
end

redis.call('LREM', processing_key, 0, job_id)
redis.call('ZREM', leases_key, job_id)
redis.call('HSET', job_key, 'state', 'queued')
redis.call('HDEL', job_key, 'worker_id')
redis.call('LPUSH', ready_key, job_id)
redis.call('HINCRBY', counts_key, 'running', -1)
redis.call('HINCRBY', counts_key, 'queued', 1)

local session_id = redis.call('HGET', job_key, 'session_id')
redis.call('PUBLISH', channel, cjson.encode({
  job_id = job_id,
  state = 'queued',
  session_id = session_id,
}))

return 'queued'
