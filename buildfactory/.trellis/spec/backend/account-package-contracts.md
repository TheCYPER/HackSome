# Account Package Contracts

> External account-package contracts for agent containers. These are executable
> seams: env keys, mounted credential paths, cloud permission prerequisites, and
> validation commands. Do not record secret values here.

## Scenario: Foundagent Domain Rail

### 1. Scope / Trigger

Use this contract when wiring or validating `accounts/<id>/` capabilities that
let agents manage `*.foundagent.net`, read Search Console data, or provision GA4
measurement IDs for newly launched sites.

This is account-package work, not runtime code: the contract lives at the
boundary between ignored credentials, container env injection, MCP servers, and
repeatable Agent capabilities.

### 2. Signatures

Filesystem and mount signatures:

```text
accounts/<id>/secrets.env
accounts/<id>/google-sa.json
accounts/<id>/cookies/
container:/account:ro
```

Env signatures:

```sh
CLOUDFLARE_API_TOKEN=
GOOGLE_APPLICATION_CREDENTIALS=/account/google-sa.json
GA4_ACCOUNT_ID=
```

Active AgentSpec signature:

```text
agents/lead.yaml
agents/ephemeral/team-worker.yaml
agents/ephemeral/team-verifier.yaml
```

The repository bundles no business Skills. Lead/Worker receive GA4 and GSC
through `agents/mcp/ceo.json`; Verifier keeps its narrow inspection-only MCP
configuration.

### 3. Contracts

Secrets and files:

- `secrets.env`, `*.env`, `accounts/*/google-sa.json`, and
  `accounts/*/cookies/` must be ignored by git.
- `google-sa.json` is mounted read-only into containers through `/account`; code
  and Agent actions must not rewrite credentials.
- Ephemeral Worker and Verifier runtimes receive the same complete account
  package: `secrets.env` through Docker `--env-file` and the account directory
  mounted at `/account:ro`.
- Verifier keeps a zero-Skill, review-only runtime. Its account credentials are
  for authenticated inspection only; it must never publish, edit, delete, or
  repair external work even when the underlying token technically permits it.

Cloudflare DNS:

- DNS is the registry for `*.foundagent.net`; query before creating a record.
- Agents may create subdomain records such as `<product>.foundagent.net`.
- Vercel sites normally use CNAME `cname.vercel-dns.com`.
- Temporary TXT records for e2e are allowed, but must be deleted after the check.
- Never delete apex `google-site-verification=` TXT records or records owned by
  another agent.

Search Console:

- `foundagent.net` uses a Search Console Domain property:
  `sc-domain:foundagent.net`.
- The apex `google-site-verification=...` TXT is permanent because Google
  rechecks ownership.
- The service account must have Full access on the Domain property so the GSC MCP
  server can list/read it.

GA4:

- GA4 account creation is human-only because the Terms of Service must be
  accepted in the Analytics UI.
- The service account must be an Editor at GA4 account level, not only at one
  existing property.
- `GA4_ACCOUNT_ID` names the human-created account.
- A Worker may create per-site properties/data streams through available tools
  or APIs only after a site has a stable public URL. Do not create placeholder
  properties.

### 4. Validation & Error Matrix

| Condition | Expected validation / response |
|-----------|--------------------------------|
| `google-sa.json` is not gitignored | Stop before commit; add an ignore rule and verify with `git check-ignore -v`. |
| GSC Domain property missing or SA lacks access | `webmasters/v3/sites` or GSC MCP does not return `sc-domain:foundagent.net`; fix Search Console UI access. |
| Apex verification TXT deleted | Search Console ownership can lapse; restore the exact Google verification TXT. |
| Cloudflare token lacks DNS edit | TXT create/delete e2e fails; ask for token scope upgrade, do not route around DNS. |
| `GA4_ACCOUNT_ID` missing | Treat the manual prerequisite as unmet; do not start OAuth or create a different account. |
| SA has only property-level GA4 access | Future `properties.create` fails with permission errors; grant account-level Editor. |
| Verifier lacks Worker-equivalent account material | Independent external verification is impossible; runtime wiring/tests must fail. |
| Verifier can authenticate but the evidence is insufficient | Submit FAIL with the inspected evidence; do not execute or repair the work. |

### 5. Good / Base / Bad Cases

- Good: service account lists `sc-domain:foundagent.net`, GA4 account
  `accounts/$GA4_ACCOUNT_ID` is readable, and a temporary Cloudflare TXT record
  can be created/deleted with residual count `0`.
- Base: a newly launched site uses the existing account and GA4 API to create
  one property/data stream, then embeds the returned `measurement_id`.
- Bad: creating a GA4 account programmatically, using OAuth to bypass missing
  account id, deleting apex Google verification TXT, or committing
  `google-sa.json`.

### 6. Tests Required

For domain-rail/account-package changes:

- `git check-ignore -v accounts/<id>/google-sa.json accounts/<id>/secrets.env`
- Host-side GSC service-account read: `webmasters/v3/sites` includes
  `sc-domain:foundagent.net`.
- Container GSC MCP e2e: Lead or Worker returns
  `GSC_OK sc-domain:foundagent.net`.
- Host-side GA4 service-account read: `accounts/$GA4_ACCOUNT_ID` returns HTTP
  `200`.
- Container Cloudflare DNS e2e: create and delete a unique temporary TXT record;
  residual query count is `0`.
- `.venv-cua/bin/python -m pytest agent/tests/test_mcp_assets.py agent/tests/test_team_loadout.py agent/tests/test_resident_loadout.py -q` when AgentSpec or MCP assets are touched.
- `orchestration/tests/test_runtime_materialization.py` and
  `orchestration/tests/test_v7_mount_boundaries.py` verify Worker/Verifier account
  package parity while preserving Verifier's zero-Skill loadout and read-only
  project mount.

### 7. Wrong vs Correct

Wrong:

```sh
# Missing GA4_ACCOUNT_ID, then attempting an OAuth workaround or a new account.
python provision_ga4.py
```

Correct:

```sh
# Human creates the GA4 account and grants account-level Editor first.
export GA4_ACCOUNT_ID=387614425
export SITE_URL=https://example.foundagent.net
export DISPLAY_NAME=example.foundagent.net
# Use the Worker runtime's available GA4 API/tooling after the manual prerequisite.
```

Wrong:

```sh
# Cleanup script deletes every TXT at foundagent.net apex.
```

Correct:

```sh
# Temporary e2e records use unique subdomain names and delete only their own id.
```
