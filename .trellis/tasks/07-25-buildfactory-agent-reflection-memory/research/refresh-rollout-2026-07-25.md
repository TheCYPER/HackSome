# Refresh-session rollout evidence — 2026-07-25

## Scope

Upgraded the static Compose services (Hub, Lead, Worker Manager, and Verifier
Manager) for these existing Teams from the canonical pushed branch:

- `rest-01-shiftmeet`
- `rest-04-handoff-rehearsal`
- `rest-05-yuye`
- `rest-07-cpap-rehearsal`

Each deployment used the existing ignored Team state and account directories,
the tracked `ops/build/docker-compose.yml` plus `docker-compose.local.yml`,
and `LEAD_REFLECTION_MEMORY_ENABLED=1`. No dynamic Worker or Verifier was a
Compose target or explicitly removed.

## Observed post-upgrade state

- All four Hub containers reported `healthy` before their dependent services
  started.
- All four Lead, Worker Manager, and Verifier Manager containers were running.
- Every Lead exposed `LEAD_REFLECTION_MEMORY_ENABLED=1`.
- Every Lead mounted
  `/private/tmp/hacksome-buildfactory-agent-reflection-skill/src/hacksome` at
  `/opt/hacksome/hacksome`.
- Existing and newly created dynamic Worker/Verifier containers remained on
  their original Team networks, showing manager reconciliation continued after
  the static-service restart.

## Remaining empirical gate

This proves deployment and session-refresh configuration, not the PRD's
three-round `goal_batch_drained` comparison. That pilot remains active and
must record brief quality, repeated-read behavior, and per-wake token usage.
