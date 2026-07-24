# Research: route-neutral post-Idea-Card contract

- Query: Audit the current Useful and Creative outputs from final Idea Card onward, then identify the smallest route-neutral contract that both routes can expose without changing any pre-card candidate, gate, or report semantics.
- Scope: internal
- Date: 2026-07-24

## Findings

### Executive conclusion

There is no route-neutral “final cards” API today. The common Hub artifact record is reusable, but the two route-level discovery fields are deliberately asymmetric:

- Useful treats `run.json.idea_card_ids` as the final card list and leaves `result_artifact_ids` empty.
- Creative never populates `idea_card_ids`; its immutable C7 manifest makes every report/card/index/handoff/memory artifact a `result_artifact_id`.

Therefore, neither state field can become the shared contract by reinterpretation. The minimal safe boundary is a new **read-only, route-adapted post-card catalog** over already completed and route-valid runs, plus the existing Creative five-field Build handoff payload as the shared materialized handoff DTO.

The normalized catalog should retain route identity for dispatch/audit, but the Build handoff should remain byte/field compatible with Creative:

```json
{
  "source_run_id": "...",
  "idea_card_id": "...",
  "idea_card_sha256": "...",
  "challenge_markdown": "...",
  "initial_idea_card_markdown": "..."
}
```

Approval and Team bootstrap state should live outside the source run. In particular, publishing a new approval artifact or event into a completed Creative run would violate its frozen source-state and exact event-suffix checks.

### Files found

- `src/hacksome/artifacts.py` — Useful Markdown validation, Idea Card composition, and human-readable index renderer.
- `src/hacksome/workflow.py` — Useful card IDs, artifact records, index publication, completion, and lack of handoff publication.
- `src/hacksome/creative/artifacts.py` — Creative Final Idea Card’s exact twelve-section contract and deterministic composer.
- `src/hacksome/creative/report.py` — Creative C7 artifact constants, exact output order, cards, index, handoffs, report references, and hashes.
- `src/hacksome/creative/report_projection.py` — Hash-bound conversion from route-owned Challenge/Final Idea artifacts into the C7 renderer projection.
- `src/hacksome/creative/finalization.py` — Immutable manifest, planned artifact shape, result exposure, replay, and post-freeze mutation detection.
- `src/hacksome/creative/workflow.py` — Creative waiting/finalizing/completed lifecycle and C7 entry/replay behavior.
- `src/hacksome/hub.py` — Common run state, artifact record, content hashing, route-neutral core validation, and planned completion.
- `src/hacksome/routes.py` — Route registry, Useful/Creative inspectors, route-specific validators, and Creative cross-artifact closure.
- `src/hacksome/state.py` — Shared canonical JSON and exact-byte SHA-256 primitives.
- `src/hacksome/cli.py` — Route dispatch plus current run/status/validate/reconcile/review/resume lifecycle.
- `buildfactory/orchestration/team_store.py` — Actual BuildFactory bootstrap input and filesystem behavior.
- `tests/test_artifacts.py` / `tests/test_workflow.py` — Useful card and zero-card executable expectations.
- `tests/test_creative_report.py` / `tests/test_creative_finalization.py` / `tests/test_routes.py` — Creative output order, handoff closure, finalization, and inspect compatibility assertions.
- `README.md` — Current product boundary: handoff publication is not Build approval and no automatic handoff consumer exists.

### Common substrate that is safe to reuse

1. **Stable artifact record**

   `RunHub.publish_artifact()` computes SHA-256 over the exact UTF-8 content and registers:

   ```text
   artifact_id
   artifact_type
   path
   sha256
   task_id
   source_refs
   metadata
   created_at
   ```

   It rejects ID/path rebinding and conflicting bytes (`src/hacksome/hub.py:877-968`). `RunHub.read_artifact()` reloads text and verifies its recorded hash before returning it (`src/hacksome/hub.py:1269-1277`).

2. **Exact hash rules**

   Text hashes are SHA-256 of UTF-8 bytes. JSON identity uses strict, sorted, compact canonical JSON; file hashes are over exact file bytes (`src/hacksome/state.py:69-79`, `src/hacksome/state.py:141-154`). Creative JSON output adds one trailing newline after canonical bytes (`src/hacksome/creative/report.py:1648-1649`), so a handoff artifact hash includes that newline even though its inner `idea_card_sha256` hashes the card bytes.

3. **Route-aware validation**

   `validate_run()` first performs common Hub validation, then dispatches to the persisted route/version contract (`src/hacksome/routes.py:1701-1778`). Common validation already checks registered paths, exact file hashes, duplicate paths, unregistered files under `artifacts/`, publish events, and that exposed result IDs exist (`src/hacksome/hub.py:1554-1654`).

4. **Common title extraction**

   Both routes use `hacksome.artifacts.title_of()` for the single H1 title (`src/hacksome/artifacts.py:75-79`, `src/hacksome/creative/report.py:16-24`). A route-neutral UI can use the route-validated H1 for display; it does not need a second model-authored title.

These primitives are suitable for a post-card adapter. Candidate meanings, card H2 schemas, gate outcomes, report shape, and finalization policy are not suitable common abstractions.

### Useful route: exact post-card output

#### Final card identity and record

Useful Idea IDs are generated as:

```text
{problem_id}-g{generator_number:02d}-idea-{candidate_number:03d}
```

and are published as `idea` artifacts (`src/hacksome/workflow.py:454-479`). For each Red-Team pass, the final card is:

| Field | Current value |
| --- | --- |
| artifact ID | `idea-card-{idea_id}` |
| artifact type | `idea_card` |
| path | `artifacts/idea-cards/{card_id}.md` |
| task ID | `null` |
| source refs | `[idea_ref, problem_ref, red_team_ref]` |
| metadata | `{"idea_id": idea_id}` |

Evidence: `src/hacksome/workflow.py:543-583`.

The card bytes are controller-composed, not model-authored as a new artifact:

```text
# <Idea H1 title>

## Lineage
<sorted JSON containing idea/problem/gateway/task/session/review identities>

<exact Idea body without its H1, including the eight Useful Idea H2 sections>

## Red Team Validation
Decision: `pass`
<exact review body without its H1>
```

Evidence: `src/hacksome/artifacts.py:82-108`; lineage fields are assembled at `src/hacksome/workflow.py:560-574`. The Idea’s required H2 set is defined at `src/hacksome/artifacts.py:20-29`.

Important limitation: the final composed card is not passed through a separate exact-card validator after composition. Review Markdown is required to have one H1 but may itself contain H2 headings, so the implementation guarantees the controller-added sections and exact source bodies, not a closed “exactly these H2 and no others” final-card schema.

#### Index identity and shape

| Field | Current value |
| --- | --- |
| artifact ID | `idea-card-index` |
| artifact type | `idea_card_index` |
| path | `artifacts/idea-cards/index.md` |
| source refs | ordered final card artifact IDs |
| state discovery field | `run.json.idea_card_ids` |

For a non-empty run, each Markdown row is:

```text
- [<title>](<card_id>.md) — `<underlying idea_id>`
```

For an empty run, it says `No Idea passed the absolute quality gates.` (`src/hacksome/artifacts.py:111-123`). Publication and `idea_card_ids` assignment occur at `src/hacksome/workflow.py:584-602`.

The index does **not** display each card hash. Its artifact record has a hash, but the index is not a machine-verifiable card manifest by itself.

#### Handoff and completion

Useful publishes no Build handoff. After cards/index and `idea_card_ids` are stored, it performs a normal `completed` status transition and returns the index `Path`; it does not populate `result_artifact_ids` (`src/hacksome/workflow.py:179-191`, `src/hacksome/hub.py:1354-1358`). The parsed challenge artifact that can supply a future shared handoff is fixed as:

```text
challenge-brief
artifacts/challenge/challenge-brief.md
```

(`src/hacksome/workflow.py:193-210`).

An empty card set is a successful completed run with a real empty index and `idea_card_ids=[]` (`tests/test_workflow.py:244-272`).

### Creative route: exact post-card output

#### Final card identity and record

The pre-card Final Idea ID is `creative-idea-{index:03d}` (`src/hacksome/creative/contracts.py:256-258`) and is persisted as `creative_final_idea` with route-specific human-resolution lineage (`src/hacksome/creative/finalize.py:730-778`).

The C7 card is:

| Field | Current value |
| --- | --- |
| artifact ID | `{final_idea_id}-card` |
| artifact type | `creative_idea_card` |
| path | `artifacts/creative/idea-cards/{final_idea_id}.md` |
| task ID | `null` |
| source refs | currently empty |
| metadata | `finalization_id` and `source_projection_sha256` added by the finalizer |

The renderer supplies only ID/type/path/content (`src/hacksome/creative/report.py:577-597`, `src/hacksome/creative/report.py:928-933`). The finalizer’s coercion therefore defaults `source_refs` and route metadata to empty, then adds its two finalization metadata fields (`src/hacksome/creative/finalization.py:1508-1522`, `src/hacksome/creative/finalization.py:1128-1158`). Creative lineage closure is consequently carried by the card body, report, manifest, and route validator—not by card artifact `source_refs`.

The card has one H1 and these twelve non-empty H2 sections, in this order:

```text
Intended Reaction
One-sentence Hook
First Thirty Seconds
Audience Action
Core Mechanism
Reveal and Aftertaste
Minimum Hackathon Demo
Why Someone May Share It
Novelty and References
Human Signal
Risks and Unresolved Disagreement
Lineage
```

The exact heading tuple and deterministic composer are at `src/hacksome/creative/artifacts.py:107-120` and `src/hacksome/creative/artifacts.py:205-240`. Route-specific source sections, novelty evidence, de-identified human signal, and lineage are mapped at `src/hacksome/creative/report.py:851-927`.

#### Index identity and shape

| Field | Current value |
| --- | --- |
| artifact ID | `creative-idea-card-index` |
| artifact type | `creative_idea_card_index` |
| path | `artifacts/creative/idea-cards/index.md` |
| source refs | currently empty |

Each non-empty row is:

```text
- [<title>](./<final_idea_id>.md) — `<card_artifact_id>` / `<card_sha256>`
```

The empty form says the completed run produced zero Final Idea Cards (`src/hacksome/creative/report.py:1015-1040`). Unlike Useful, this human-readable index binds both card artifact ID and exact card hash.

The authoritative machine list also appears in the success report JSON as `final_idea_card_ids`; `handoff_refs` is a parallel array (`src/hacksome/creative/report.py:1137-1144`).

#### Build handoff identity and exact shape

For each card:

| Field | Current value |
| --- | --- |
| artifact ID | `{final_idea_id}-handoff` |
| artifact type | `creative_build_handoff` |
| path | `artifacts/creative/handoffs/{final_idea_id}.json` |

The payload has exactly five keys:

```json
{
  "source_run_id": "<Creative run ID>",
  "idea_card_id": "<card artifact ID>",
  "idea_card_sha256": "<SHA-256 of exact card bytes>",
  "challenge_markdown": "<exact Creative Challenge Brief artifact text>",
  "initial_idea_card_markdown": "<exact card UTF-8 text>"
}
```

Renderer evidence: `src/hacksome/creative/report.py:994-1012`. The Challenge value is the C0 `creative_challenge_brief` artifact selected by the report projection (`src/hacksome/creative/report_projection.py:193-245`); its current fixed artifact ID/path is `creative-challenge-brief-r001` / `artifacts/creative/challenge/creative-challenge-brief-r001.md` (`src/hacksome/creative/workflow.py:1453-1472`).

#### Complete C7 bundle and lifecycle

Stable fixed artifact identities are declared at `src/hacksome/creative/report.py:53-61`. Successful output order is:

```text
creative-idea-report
creative-idea-report-json
0..N {final_idea_id}-card
creative-idea-card-index
0..N {final_idea_id}-handoff
creative-memory-record
```

`RenderedReportBundle.outputs` fixes that order (`src/hacksome/creative/report.py:604-624`), and `render_success_report()` deterministically sorts Final Ideas before rendering (`src/hacksome/creative/report.py:627-683`).

All outputs above—not only cards—become `result_artifact_ids`. The immutable manifest binds contiguous publish order, exact staged/final paths, exact bytes/hash/size, one timestamp, source projection hash, artifact records/events, and the final transition (`src/hacksome/creative/finalization.py:505-600`, `src/hacksome/creative/finalization.py:736-831`). Publication exposes results only in the last completion transition (`src/hacksome/creative/finalization.py:903-1089`).

Creative does not call `set_idea_cards()`, so its inherited `idea_card_ids` remains empty even for non-zero final cards.

### Route-specific differences that a shared consumer must not erase

| Concern | Useful | Creative | Shared-consumer rule |
| --- | --- | --- | --- |
| Card list authority | `idea_card_ids` | success report + C7 manifest/result set | Use a route adapter; never read one raw state field for both. |
| Card type | `idea_card` | `creative_idea_card` | Normalize after route validation; do not rename persisted types. |
| Card ID | `idea-card-{Useful idea_id}` | `{creative final idea ID}-card` | Treat as opaque. Never parse/prefix-strip generically. |
| Card path | `artifacts/idea-cards/...` | `artifacts/creative/idea-cards/...` | Resolve from the artifact record, not string construction in shared code. |
| Card content | Useful Idea + Red-Team validation + task/session lineage | twelve-section Creative card + novelty/human signal/lineage | Keep route-owned validators and renderers. |
| Index ID | `idea-card-index` | `creative-idea-card-index` | Normalize an index ref; do not standardize the persisted ID. |
| Index rows | title/link/underlying Idea ID | title/link/card ID/card hash | Do not parse Markdown as the machine manifest. |
| Card artifact `source_refs` | explicit Idea/Problem/Red-Team refs | empty for C7 outputs | Do not require a shared source-ref graph. |
| Handoff | absent | exact five-field canonical JSON | Adopt the Creative DTO; Useful can materialize it after cards exist. |
| Final state exposure | `idea_card_ids`; normal status transition | all C7 `result_artifact_ids`; frozen manifest | Do not repurpose either field. |
| Recovery | no run-level resume | closed C6 review or frozen C7 replay only | Post-card approval must not invoke route recovery. |
| Zero cards | valid empty index | valid report/index/memory with zero reason | Approval may select zero; zero must not become a failure. |

### CLI lifecycle and current public surface

- `hacksome run` defaults to Useful and dispatches `--route useful|creative`; route-only flags are rejected before run creation (`src/hacksome/cli.py:96-173`, `src/hacksome/cli.py:263-285`).
- Useful `run` executes to terminal completion and prints the Idea Card index (`src/hacksome/cli.py:299-326`).
- Creative `run` may return:
  - `waiting`, with a review batch and `hacksome review ...`;
  - `finalizing`, with a frozen plan, a resume command, and exit status 1;
  - `completed`, with the Creative report.

  Evidence: `src/hacksome/cli.py:329-369`, `src/hacksome/creative/workflow.py:547-654`.
- `status`, `validate`, and `reconcile` are shared commands; `review` and `resume` are Creative-only (`src/hacksome/cli.py:175-202`, `src/hacksome/cli.py:455-486`).
- Creative `resume` accepts only completed, frozen-finalization, or closed-review states; an open review is rejected (`src/hacksome/cli.py:538-571`). Workflow replay does not re-render a frozen plan (`src/hacksome/creative/workflow.py:681-828`).
- A Useful run presented to `review` or `resume` is rejected before workflow mutation by `_creative_run_snapshot()` (`src/hacksome/cli.py:472-486`).

There is no `cards`, `approve`, `handoff`, or `build` command. `status --json` is not a suitable substitute:

- Useful exposes only `idea_card_count`, not card identities/hashes; its exact field list is explicitly compatibility-tested (`src/hacksome/routes.py:100-121`, `tests/test_routes.py:48-71`).
- Creative exposes report/finalization summaries but no normalized card records (`src/hacksome/routes.py:346-409`).

A new post-card command/API is safer than changing the existing status projection.

### Current validators: strengths and gaps

#### Useful validator

Useful validation:

- loads the frozen prompt catalog;
- accepts only `pass|reject` decisions;
- for each ID listed in `idea_card_ids`, requires an `idea_card` artifact;
- requires its source refs to include an Idea that passed Red Team and a Problem that passed the Problem Gateway.

Evidence: `src/hacksome/routes.py:123-190`.

It currently does **not** establish a complete post-card bundle contract:

- it does not require a completed status;
- it does not require or validate `idea-card-index`;
- it does not prove `idea_card_ids` equals all registered `idea_card` artifacts;
- it does not validate final card Markdown/lineage/metadata;
- it does not require the Red-Team review artifact itself in the card’s source refs;
- it has no handoff closure to validate.

This is observable compatibility, not merely missing tests: a newly created empty Useful run validates successfully in `tests/test_routes.py:48-71`. A shared approval adapter must add a **versioned post-card readiness check** rather than silently strengthening all historical Useful `validate_run()` behavior unless that compatibility change is explicitly accepted.

#### Creative validator

Creative completed-run validation is much stronger:

- status-specific C7 rules reject result exposure before completion and require the completed finalization manifest (`src/hacksome/routes.py:2198-2348`);
- manifest output IDs, types, paths, counts, and order must exactly match persisted Final Ideas (`src/hacksome/routes.py:2430-2546`);
- each card must satisfy the twelve required headings;
- the index must contain each card ID and card hash exactly once;
- every handoff must be canonical JSON with exactly the five fields, exact run/card/hash bindings, exact card Markdown, and exact Challenge Markdown (`src/hacksome/routes.py:2589-2668`);
- success report card/handoff arrays must be exact (`src/hacksome/routes.py:2739-2792`).

The finalizer also reconstructs and hashes the pre-C7 source state, source files, four ledger heads, and exact planned event suffix. Extra route artifact/state/ledger publication after completion causes validation conflict (`src/hacksome/creative/finalization.py:1306-1461`).

### Minimal recommended route-neutral contract

#### 1. Read-only normalized catalog

Expose a new contract separate from `inspect_run()`:

```json
{
  "schema_version": 1,
  "source_run": {
    "run_id": "...",
    "route_id": "useful|creative",
    "route_contract_version": "1"
  },
  "status": "completed",
  "challenge": {
    "artifact_id": "...",
    "path": "...",
    "sha256": "..."
  },
  "index": {
    "artifact_id": "...",
    "path": "...",
    "sha256": "..."
  },
  "cards": [
    {
      "idea_card_id": "...",
      "path": "...",
      "idea_card_sha256": "..."
    }
  ]
}
```

Contract rules:

1. Return a catalog only when `validate_run(run_dir) == []` and persisted status is `completed`.
2. Treat `idea_card_id` and paths as opaque.
3. Preserve the route’s deterministic card order.
4. Hash exact registered bytes; do not hash normalized Markdown.
5. The catalog is the machine index. Existing Markdown indexes remain route-owned display artifacts and are only bound as an artifact ref/hash.
6. `cards=[]` is valid.
7. A canonical hash of this catalog can be stored by the later approval request to prevent stale batch selection.

Route adapters:

- Useful: challenge=`challenge-brief`; index=`idea-card-index`; card order=`idea_card_ids`; additionally prove index/card set closure for post-card readiness.
- Creative: challenge=success report’s validated `challenge_ref`; index=`creative-idea-card-index`; card order=validated report `final_idea_card_ids`, cross-checked with the manifest. Do not derive cards by filtering all `result_artifact_ids`.

The adapter should be a separate post-card provider/registry rather than a required new method on `RunContract`: `register_run_contract()` is public, so adding a mandatory Protocol method could break third-party route contracts (`src/hacksome/routes.py:79-97`, `src/hacksome/routes.py:1707-1715`).

#### 2. Shared materialized Build handoff v1

Adopt Creative’s exact five-field payload without adding `source_route_id`. Route identity remains in the catalog/approval envelope; preserving the handoff key set allows current Creative artifacts and validator to remain byte/field compatible.

For Useful, the provider can materialize:

- `source_run_id` from `run.json`;
- `idea_card_id` and `idea_card_sha256` from the normalized card record;
- `challenge_markdown` from `challenge-brief`;
- `initial_idea_card_markdown` from the exact hash-verified card bytes.

For Creative, load and verify the already-persisted handoff instead of regenerating it. A regenerated semantically equal object is insufficient when the frozen artifact’s exact bytes/hash are part of C7.

The minimum cross-run card identity is:

```text
(source_run_id, idea_card_id, idea_card_sha256)
```

This matches the existing normative Creative contract and avoids card-ID collision across runs (`.trellis/spec/backend/creative-agent-workflow-contracts.md:260-265`). `route_id` should still be retained in approval/audit records for adapter dispatch.

#### 3. Approval and Build boundary

Recommended flow:

```text
completed source run
→ route validate
→ read-only normalized catalog
→ human approves 0..N immutable card identities
→ revalidate source run + card/catalog hashes
→ materialize/verify Build handoff v1
→ stable external Team identity
→ TeamLayout.bootstrap(challenge_markdown, initial_idea_card_markdown)
```

Keep these boundaries:

- Approval is a separate product decision; it must not rewrite Useful Red-Team decisions or Creative C6 dispositions.
- Handoff publication is not authorization to start a Team.
- Approval records, Build attempts, and Team identities belong to a separate orchestration store outside the source run’s artifact/state/ledger space.
- The Build adapter consumes JSON/text, not Creative or BuildFactory private Python types.
- The adapter must recompute `idea_card_sha256` immediately before bootstrap.
- A stable Team key should use at least the identity triple above; raw `idea_card_id` alone is insufficient.

BuildFactory currently accepts only the two Markdown strings, checks type/UTF-8/NUL, atomically creates `project/reference/{challenge.md,initial-idea-card.md}`, and rejects when the reference directory already exists (`buildfactory/orchestration/team_store.py:31-40`, `buildfactory/orchestration/team_store.py:68-106`). It does not validate run/card identity or hashes. Those checks must remain in the top-level adapter.

### Compatibility risks

1. **Changing `status --json` is observable.** Useful’s exact key order/set is pinned by a test (`tests/test_routes.py:48-71`). Prefer a new endpoint/command.
2. **Using `idea_card_ids` cross-route loses Creative cards.** Creative leaves it empty.
3. **Using `result_artifact_ids` cross-route loses Useful cards and over-selects Creative reports/index/memory.**
4. **Parsing Markdown indexes is unsafe.** Row syntax differs, Useful omits hashes, and neither index should become the routing database.
5. **Generic artifact-type filtering is insufficient.** Type names differ and may not preserve authoritative order.
6. **Generic `source_refs` validation would reject Creative C7 cards.** Their artifact records currently have empty refs; closure is elsewhere.
7. **Adding fields to handoff v1 breaks Creative’s exact-key validator.** Keep route/version metadata in the outer catalog/approval record.
8. **Hash normalization causes false identity.** Hash exact bytes. In particular, canonical JSON artifact hashes include the terminal newline.
9. **Challenge source must be route-adapted.** Both current handoff semantics use the parsed Challenge Brief, but its artifact ID/type/path differ; do not substitute `input/challenge.md` silently.
10. **Post-completion source-run writes are unsafe.** Creative finalization rejects extra state/artifact/ledger changes; approval must be external.
11. **Strengthening Useful validation can invalidate historical/current nonterminal runs.** Add post-card readiness as a versioned contract first.
12. **Build bootstrap is not an identity validator.** It also raises on an existing reference directory, so the orchestration layer needs explicit idempotency/conflict handling for retries.
13. **Zero cards are valid.** A batch approval of zero must complete without creating a Team.
14. **Useful legacy scope is ambiguous.** `UsefulRunContract` supports run schema v1 and v2 while Creative supports only v2 (`src/hacksome/routes.py:100-108`, `src/hacksome/routes.py:193-200`). The new post-card contract should explicitly require v2 or define a tested legacy projection; it should not accidentally promise both.

### Recommended implementation boundaries

- `src/hacksome` shared layer: DTOs/canonical encoding for `PostCardCatalogV1`, card identity, and `BuildHandoffV1`; no candidate or BuildFactory imports.
- Route-owned adapters: Useful and Creative discovery/readiness checks, challenge/card/index resolution, and persisted Creative handoff verification.
- Existing `routes.validate_run()`: remains the first integrity gate; do not duplicate its route semantics in approval code.
- New external approval/orchestration store: append-only approval requests/selections and Build-attempt idempotency, keyed by immutable card identities and catalog hash.
- Build-side adapter: verifies the handoff and calls `TeamLayout.bootstrap()`; no source-route private imports.
- Existing route files: retain all card headings, IDs, artifact types, paths, report structures, gate meanings, and lifecycle/replay behavior.

### Related specs

- `.trellis/spec/backend/agent-workflow-contracts.md:290-337` — Useful Hub ownership, deterministic card validation, offline validation, and no run-level resume.
- `.trellis/spec/backend/creative-agent-workflow-contracts.md:10-33` — shared Harness but explicitly non-shared candidate/gate/report semantics.
- `.trellis/spec/backend/creative-agent-workflow-contracts.md:213-281` — exact C7 output order, card schema, Build handoff boundary, identity triple, and immutable finalization.
- `.trellis/spec/backend/creative-agent-workflow-contracts.md:283-295` — failed Creative runs must not expose valid cards/handoffs/results.
- `.trellis/spec/guides/cross-layer-thinking-guide.md:17-59` — define exact formats and one validation owner at boundaries.
- `.trellis/spec/guides/code-reuse-thinking-guide.md:14-53` — reuse the existing data owner/decoder rather than duplicate payload interpretation.

### External references

None. This was an internal code/spec audit. Relevant persisted versions in the current implementation are route contract `1`, run schema v2 for both current routes (with Useful legacy v1 projection), report policy `1`, and Creative finalization manifest schema `1`.

## Caveats / Not Found

- No current cross-route approval ledger, batch-selection contract, post-card catalog API, Build adapter, Team identity store, or CLI command was found.
- No Useful Build handoff artifact or validator exists.
- No code currently consumes Creative handoffs automatically; the README explicitly states that selection, hash verification, and Team initialization remain future top-level adapter work (`README.md:175-194`).
- This audit did not execute workflows or mutate product code. Findings are based on current source, specs, and executable test assertions in the isolated worktree.
