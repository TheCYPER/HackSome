# foundagent-mail-ingress — Cloudflare Email Worker

Cloud half of the domain-level mail backend. It streams every inbound raw MIME
for `*@foundagent.net` into R2; the platform singleton `mail-router` does
everything else (parse, global Company lookup, private journal append,
archiving). The Worker is deliberately dumb — do not add parsing or Company
routing here.

## R2 object contract

- `inbox/<epoch-ms>-<uuid>.eml` — pending raw email; `customMetadata.to` =
  envelope RCPT TO (the poller's routing key), `customMetadata.from` =
  envelope MAIL FROM.
- The router moves objects to `processed/` (persisted in a Company journal) or `unmatched/`
  (no registry match). Objects left in `inbox/` are retried — R2 is the
  durable buffer while the router is down.
- Inbound size limit: 25 MiB (Cloudflare rejects larger mail with a bounce).

## One-time operator steps (manual, no repo scripts)

See `.trellis/tasks/07-08-agent-email/design.md` §4.

1. **Email Routing on the zone** — dashboard: Email Service → Onboard Domain →
   `foundagent.net` (auto-adds MX/SPF, live in 5-15 min). Check first, v5 may
   have enabled it already:
   `GET https://api.cloudflare.com/client/v4/zones/{zone_id}/email/routing`
   (`status: ready` = done).
2. **R2 API token** — dashboard: R2 → Manage API Tokens → Object Read & Write,
   scoped to bucket `foundagent-mail`. Put the credentials into `vm/.env.local`:

   ```
   R2_ACCESS_KEY_ID=...
   R2_SECRET_ACCESS_KEY=...
   R2_ENDPOINT=https://<account_id>.r2.cloudflarestorage.com
   ```

3. **Cloudflare API token** — scope: Zone → Email Routing Rules: Edit. Used
   once for the catch-all call below.

## Deploy

```sh
wrangler r2 bucket create foundagent-mail
cd peripheral/email/worker && wrangler deploy
```

No routes/triggers config needed — an email worker is activated by the
catch-all rule, set once via REST (wrangler has no email-routing subcommand):

```sh
curl -X PUT \
  "https://api.cloudflare.com/client/v4/zones/{zone_id}/email/routing/rules/catch_all" \
  -H "Authorization: Bearer $CF_EMAIL_ROUTING_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"matchers":[{"type":"all"}],"actions":[{"type":"worker","value":["foundagent-mail-ingress"]}],"enabled":true}'
```

## Verify

This upstream reference is no longer wired into the active Team Compose. When
exercising it independently, build and run the router explicitly, then send
mail to a claimed address. An `inbox/*.eml` object appears in
`foundagent-mail`, the singleton router writes only the owning Company's
`state/<company>/mailboxes/messages.jsonl`, and the object moves to
`processed/`. An unclaimed address moves to `unmatched/`.

## Rollback

Cloud side is not covered by git revert: set the catch-all action back to
`{"type":"drop"}` (same PUT as above) to stop ingestion; the worker and bucket
can stay deployed, idle and free. Do not delete `state/_mail/registry.jsonl`
or any Company mail journal during rollback.
