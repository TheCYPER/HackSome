"""Command-line interface for the local Idea-only workflow."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import sys
import webbrowser
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from hacksome.codex import CodexRunner
from hacksome.build_approval.build_adapter import (
    SubprocessBuildControlAdapter,
)
from hacksome.build_approval.contracts import ApprovalError
from hacksome.build_approval.server import (
    ApprovalServerConfig,
    ApprovalServerError,
    BuildApprovalServer,
)
from hacksome.build_approval.service import ApprovalService
from hacksome.config import CodexConfig
from hacksome.creative.benchmark import (
    BenchmarkManifest,
    BlindCaseMap,
    BlindIdeaBinding,
    BlindReviewPacket,
    import_worksheet,
)
from hacksome.creative.contracts import CreativeWorkflowSettings
from hacksome.creative.finalize import CreativeFeedbackError
from hacksome.creative.review_backend import RunReviewBackend
from hacksome.creative.review_server import (
    CreativeReviewServer,
    ReviewServerConfig,
    ReviewServerError,
)
from hacksome.creative.workflow import (
    CreativeIdeaWorkflow,
    CreativeRunOutcome,
    CreativeWorkflowError,
)
from hacksome.hub import RunHub
from hacksome.models import CodexDoctorResult
from hacksome.pitch import (
    PITCH_MODEL,
    PITCH_REASONING_EFFORT,
    PitchWorkflow,
    PitchWorkflowError,
)
from hacksome.post_card.catalog import (
    PostCardCatalogError,
    project_post_card_catalog,
)
from hacksome.state import StateError
from hacksome.workflow import (
    UsefulIdeaWorkflow,
    WorkflowError,
    WorkflowSettings,
    inspect_run,
    validate_run,
)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _audience_limit(value: str) -> int:
    parsed = _positive_int(value)
    if parsed > 5:
        raise argparse.ArgumentTypeError("must not exceed 5 in v1")
    return parsed


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _port(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 0 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("must be between 0 and 65535")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    defaults = WorkflowSettings()
    codex_defaults = CodexConfig()
    parser = argparse.ArgumentParser(
        prog="hacksome",
        description="Run Useful or Creative hackathon Idea workflows with local Codex.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="start a new Idea discovery run")
    run.add_argument("challenge", nargs="?", type=Path, help="UTF-8 challenge file")
    run.add_argument("--prompt", help="literal challenge instead of a file")
    run.add_argument(
        "--route",
        choices=("useful", "creative"),
        default="useful",
        help="Idea workflow route (default: useful)",
    )
    run.add_argument("--runs-dir", type=Path, default=Path("runs"))
    run.add_argument("--run-id")
    run.add_argument("--codex", default=codex_defaults.executable, metavar="PATH")
    run.add_argument("--model", default=codex_defaults.model)
    run.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high", "xhigh", "max", "ultra"),
        default=codex_defaults.reasoning_effort,
    )
    run.add_argument(
        "--max-concurrency",
        type=_positive_int,
        default=codex_defaults.max_concurrency,
    )
    run.add_argument(
        "--infrastructure-retries",
        type=_non_negative_int,
        default=codex_defaults.infrastructure_retries,
    )
    run.add_argument("--max-audiences", type=_audience_limit, default=argparse.SUPPRESS)
    run.add_argument(
        "--researchers-per-audience",
        type=_positive_int,
        default=argparse.SUPPRESS,
    )
    run.add_argument(
        "--idea-generators-per-problem",
        type=_positive_int,
        default=argparse.SUPPRESS,
    )
    creative_brief = run.add_mutually_exclusive_group()
    creative_brief.add_argument(
        "--creative-brief",
        default=argparse.SUPPRESS,
        help="literal Creative Brief (Creative route only)",
    )
    creative_brief.add_argument(
        "--creative-brief-file",
        type=Path,
        default=argparse.SUPPRESS,
        help="UTF-8 Creative Brief file (Creative route only)",
    )
    run.add_argument(
        "--idea-memory",
        choices=("auto", "off"),
        default=argparse.SUPPRESS,
        help="eligible Idea Memory policy (Creative route only)",
    )
    run.add_argument(
        "--task-timeout",
        type=_positive_float,
        default=defaults.task_timeout_seconds,
        metavar="SECONDS",
    )
    run.add_argument(
        "--run-timeout",
        type=_positive_float,
        default=defaults.run_timeout_seconds,
        metavar="SECONDS",
    )

    pitch = commands.add_parser(
        "pitch",
        help="create a Pitch from one completed Project snapshot",
    )
    pitch.add_argument(
        "--project",
        type=Path,
        required=True,
        help="completed Project directory to copy",
    )
    pitch.add_argument(
        "--idea-card",
        type=Path,
        required=True,
        help="Idea Card Markdown file",
    )
    pitch.add_argument(
        "--challenge",
        type=Path,
        required=True,
        help="original hackathon challenge file",
    )
    pitch.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="new directory for this Pitch run",
    )
    pitch.add_argument("--codex", default=codex_defaults.executable, metavar="PATH")
    pitch.add_argument(
        "--infrastructure-retries",
        type=_non_negative_int,
        default=codex_defaults.infrastructure_retries,
    )
    pitch.add_argument(
        "--task-timeout",
        type=_positive_float,
        default=codex_defaults.default_timeout_seconds,
        metavar="SECONDS",
    )
    pitch.add_argument(
        "--browser",
        type=Path,
        help="Chromium-family executable for the final browser smoke",
    )

    status = commands.add_parser("status", help="inspect a saved run")
    status.add_argument("run_dir", type=Path)
    status.add_argument("--json", action="store_true")

    validate = commands.add_parser("validate", help="validate a saved run offline")
    validate.add_argument("run_dir", type=Path)

    reconcile = commands.add_parser(
        "reconcile",
        help="flush durable run records without calling an Agent",
    )
    reconcile.add_argument("run_dir", type=Path)

    review = commands.add_parser(
        "review",
        help="serve the human review page for a waiting Creative run",
    )
    review.add_argument("run_dir", type=Path)
    review.add_argument("--host", default="127.0.0.1")
    review.add_argument("--public-host")
    review.add_argument("--port", type=_port, default=0)
    review.add_argument("--no-open", action="store_true")

    resume = commands.add_parser(
        "resume",
        help="resume a closed Creative review or frozen finalization",
    )
    resume.add_argument("run_dir", type=Path)

    approve = commands.add_parser(
        "approve",
        help="serve the shared Build Dispatch Board for a completed run",
    )
    approve.add_argument("run_dir", type=Path)
    approve.add_argument("--approval-root", type=Path)
    approve.add_argument(
        "--build-root",
        type=Path,
        default=Path("buildfactory/state/build-pool"),
    )
    approve.add_argument(
        "--build-python",
        type=Path,
        default=Path(sys.executable),
    )
    approve.add_argument("--host", default="127.0.0.1")
    approve.add_argument("--port", type=_port, default=0)
    approve.add_argument(
        "--max-active-teams",
        type=_positive_int,
        default=2,
    )
    approve.add_argument("--no-open", action="store_true")

    for name, help_text in (
        ("build-status", "inspect Build Approval and Team pool state"),
        ("build-reconcile", "replay authorized handoffs and Team lifecycle"),
        ("build-validate", "validate the frozen Approval ledger offline"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("run_dir", type=Path)
        command.add_argument("--approval-root", type=Path)
        command.add_argument(
            "--build-root",
            type=Path,
            default=Path("buildfactory/state/build-pool"),
        )
        command.add_argument(
            "--build-python",
            type=Path,
            default=Path(sys.executable),
        )
        command.add_argument(
            "--max-active-teams",
            type=_positive_int,
            default=2,
        )
        command.add_argument("--json", action="store_true")

    benchmark = commands.add_parser(
        "benchmark",
        help="validate and plan an offline Creative benchmark",
    )
    benchmark.add_argument("manifest", nargs="?", type=Path)
    benchmark.add_argument(
        "--route",
        choices=("creative",),
        default=argparse.SUPPRESS,
    )
    benchmark.add_argument(
        "--continue",
        dest="continue_dir",
        type=Path,
        default=argparse.SUPPRESS,
        metavar="BENCH_DIR",
    )
    benchmark.add_argument(
        "--worksheet",
        type=Path,
        default=argparse.SUPPRESS,
    )

    doctor = commands.add_parser("doctor", help="check Codex CLI and login")
    doctor.add_argument("--codex", default=codex_defaults.executable, metavar="PATH")
    doctor.add_argument(
        "--timeout",
        type=_positive_float,
        default=codex_defaults.doctor_timeout_seconds,
    )
    doctor.add_argument("--json", action="store_true")
    return parser


def _read_challenge(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    if (args.challenge is None) == (args.prompt is None):
        parser.error("run requires exactly one of CHALLENGE or --prompt")
    if args.prompt is not None:
        if not args.prompt.strip():
            parser.error("--prompt must not be empty")
        return args.prompt
    assert args.challenge is not None
    content = args.challenge.expanduser().read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError(f"challenge file is empty: {args.challenge}")
    return content


def _explicit_options(
    args: argparse.Namespace,
    names: Sequence[str],
) -> list[str]:
    return [name for name in names if hasattr(args, name)]


def _render_options(names: Sequence[str]) -> str:
    return ", ".join("--" + name.replace("_", "-") for name in names)


def _validate_route_options(args: argparse.Namespace) -> None:
    useful_options = (
        "max_audiences",
        "researchers_per_audience",
        "idea_generators_per_problem",
    )
    creative_options = (
        "creative_brief",
        "creative_brief_file",
        "idea_memory",
    )
    if args.route == "creative":
        supplied = _explicit_options(args, useful_options)
        if supplied:
            raise ValueError(
                f"{_render_options(supplied)} can only be used with --route useful"
            )
        return
    supplied = _explicit_options(args, creative_options)
    if supplied:
        raise ValueError(
            f"{_render_options(supplied)} can only be used with --route creative"
        )


def _codex_config(args: argparse.Namespace) -> CodexConfig:
    return CodexConfig(
        executable=args.codex,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        max_concurrency=args.max_concurrency,
        infrastructure_retries=args.infrastructure_retries,
        default_timeout_seconds=args.task_timeout,
    )


def _run_useful_command(args: argparse.Namespace, challenge: str) -> int:
    defaults = WorkflowSettings()
    settings = WorkflowSettings(
        max_audiences=getattr(args, "max_audiences", defaults.max_audiences),
        researchers_per_audience=getattr(
            args,
            "researchers_per_audience",
            defaults.researchers_per_audience,
        ),
        idea_generators_per_problem=getattr(
            args,
            "idea_generators_per_problem",
            defaults.idea_generators_per_problem,
        ),
        task_timeout_seconds=args.task_timeout,
        run_timeout_seconds=args.run_timeout,
    )
    workflow = UsefulIdeaWorkflow.create(
        challenge,
        args.runs_dir,
        settings=settings,
        codex_config=_codex_config(args),
        run_id=args.run_id,
    )
    print(f"Run directory: {workflow.run_dir}")
    index = asyncio.run(workflow.execute())
    print(f"Idea Cards: {index}")
    _print_build_approval_next(workflow.run_dir)
    return 0


def _run_creative_command(args: argparse.Namespace, challenge: str) -> int:
    settings = CreativeWorkflowSettings(
        idea_memory_mode=getattr(args, "idea_memory", "auto"),
    )
    workflow = CreativeIdeaWorkflow.create(
        challenge,
        args.runs_dir,
        settings=settings,
        codex_config=_codex_config(args),
        run_id=args.run_id,
        creative_brief=getattr(args, "creative_brief", None),
        creative_brief_file=getattr(args, "creative_brief_file", None),
        run_timeout_seconds=args.run_timeout,
    )
    print(f"Run directory: {workflow.run_dir}")
    outcome = asyncio.run(workflow.execute())
    return _print_creative_outcome(outcome)


def _run_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    _validate_route_options(args)
    challenge = _read_challenge(args, parser)
    if args.route == "creative":
        return _run_creative_command(args, challenge)
    return _run_useful_command(args, challenge)


def _pitch_command(args: argparse.Namespace) -> int:
    config = CodexConfig(
        executable=args.codex,
        infrastructure_retries=args.infrastructure_retries,
        default_timeout_seconds=args.task_timeout,
        model=PITCH_MODEL,
        reasoning_effort=PITCH_REASONING_EFFORT,
    )
    workflow = PitchWorkflow.create(
        args.project,
        args.idea_card,
        args.challenge,
        args.output_root,
        codex_config=config,
        browser_executable=args.browser,
        task_timeout_seconds=args.task_timeout,
    )
    print(f"Pitch run directory: {workflow.run_dir}")
    outcome = asyncio.run(workflow.execute())
    print(f"Deck outline: {outcome.deck_outline}")
    print(f"Pitch deck: {outcome.pitch_deck}")
    print(f"Pitch script: {outcome.pitch_script}")
    return 0


def _print_creative_outcome(outcome: CreativeRunOutcome) -> int:
    print(f"Creative status: {outcome.status}")
    if outcome.status == "waiting":
        print(f"Review batch: {outcome.primary_artifact}")
    elif outcome.status == "completed":
        print(f"Creative report: {outcome.primary_artifact}")
    elif outcome.status == "finalizing":
        print(f"Finalization plan: {outcome.primary_artifact}")
        print("Finalization is recoverable from its frozen publication plan.")
    else:
        raise ValueError(f"unsupported Creative outcome status: {outcome.status!r}")
    if outcome.next_command is not None:
        print(f"Next: {outcome.next_command}")
    elif outcome.status == "completed":
        _print_build_approval_next(outcome.run_dir)
    return 1 if outcome.status == "finalizing" else 0


def _print_build_approval_next(run_dir: Path) -> None:
    try:
        catalog = project_post_card_catalog(run_dir)
    except (OSError, PostCardCatalogError, StateError):
        # A workflow result can be supplied by a test double or older integration
        # that has not persisted the route-neutral catalog inputs yet.  The hint
        # must never turn an otherwise successful Idea run into a CLI failure.
        return
    if catalog.cards:
        print(f"Next: hacksome approve {run_dir}")
    else:
        print(
            "No final Idea Cards are available to Build. "
            f"Open the explicit empty state with: hacksome approve {run_dir}"
        )


def _status_command(args: argparse.Namespace) -> int:
    payload = inspect_run(args.run_dir)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if payload.get("route_id") == "creative":
        return _creative_status(payload)
    print(f"Run: {payload['run_id']}")
    print(f"Status: {payload['status']}")
    print(f"Current stage: {payload.get('current_stage') or '-'}")
    counts = payload.get("task_counts", {})
    rendered = ", ".join(
        f"{status}={count}" for status, count in sorted(counts.items())
    ) if isinstance(counts, dict) and counts else "none"
    print(f"Tasks: {rendered}")
    print(f"Decisions: {payload.get('decision_count', 0)}")
    print(f"Idea Cards: {payload.get('idea_card_count', 0)}")
    return 0


def _creative_status(payload: dict[str, Any]) -> int:
    counts = payload.get("task_counts", {})
    rendered_tasks = (
        ", ".join(
            f"{status}={count}" for status, count in sorted(counts.items())
        )
        if isinstance(counts, dict) and counts
        else "none"
    )
    concepts = payload.get("concept_counts")
    rendered_concepts = (
        ", ".join(
            f"{name}={count}" for name, count in sorted(concepts.items())
        )
        if isinstance(concepts, dict) and concepts
        else "none"
    )
    memory = _object_or_empty(payload.get("memory"))
    review = _object_or_empty(payload.get("review"))
    finalization = _object_or_empty(payload.get("finalization"))
    report_ref = payload.get("report_ref") or payload.get("partial_report_ref") or "-"

    print(f"Run: {payload['run_id']}")
    print("Route: creative")
    print(f"Status: {payload['status']}")
    print(f"Current stage: {payload.get('current_stage') or '-'}")
    print(f"Tasks: {rendered_tasks}")
    print(f"Concepts: {rendered_concepts}")
    print(
        "Memory: "
        f"mode={memory.get('mode') or '-'}, "
        f"status={memory.get('status') or '-'}, "
        f"entries={memory.get('eligible_entry_count', 0)}, "
        f"cues={memory.get('selected_cue_count', 0)}"
    )
    print(
        "Review: "
        f"status={review.get('status') or '-'}, "
        f"round={review.get('round_id') or '-'}, "
        f"reviewers={review.get('reviewer_count', 0)}, "
        f"coverage={review.get('covered_concept_count', 0)}/"
        f"{review.get('shortlist_count', 0)}, "
        f"resumable={_yes_no(review.get('resumable'))}"
    )
    print(
        "Finalization: "
        f"status={finalization.get('status') or '-'}, "
        f"published={finalization.get('published_artifact_count', 0)}/"
        f"{finalization.get('planned_artifact_count', 0)}, "
        f"resumable={_yes_no(finalization.get('resumable'))}"
    )
    print(f"Report: {report_ref}")
    return 0


def _object_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _yes_no(value: Any) -> str:
    return "yes" if value is True else "no"


def _validate_command(args: argparse.Namespace) -> int:
    errors = validate_run(args.run_dir)
    if errors:
        print(f"Validation failed with {len(errors)} error(s):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Run is valid.")
    return 0


def _reconcile_command(args: argparse.Namespace) -> int:
    count = RunHub(args.run_dir).reconcile_pending()
    print(f"Reconciled records: {count}")
    return 0


def _creative_run_snapshot(
    run_dir: Path,
    *,
    command: str,
) -> tuple[RunHub, dict[str, Any]]:
    hub = RunHub(run_dir)
    state = hub.load_state()
    route = state.get("route")
    route_id = route.get("id") if isinstance(route, dict) else None
    if route_id != "creative":
        raise ValueError(
            f"{command} only supports persisted Creative runs; "
            f"found route {route_id or 'unknown'!r}"
        )
    return hub, state


def _review_command(args: argparse.Namespace) -> int:
    hub, state = _creative_run_snapshot(args.run_dir, command="review")
    wait = state.get("wait")
    if (
        state.get("status") != "waiting"
        or state.get("current_stage") != "creative-human-review"
        or not isinstance(wait, dict)
        or wait.get("kind") != "creative_human_review"
    ):
        raise ValueError(
            "review requires a Creative run waiting at human review"
        )

    backend = RunReviewBackend(hub.run_dir)
    config = ReviewServerConfig(
        run_dir=hub.run_dir,
        host=args.host,
        public_host=args.public_host,
        port=args.port,
    )
    server = CreativeReviewServer(backend, config)
    try:
        print(f"Review URL: {server.review_url}")
        print(f"Curator URL: {server.curator_url}")
        if not _is_loopback_host(args.host):
            print(
                "WARNING: this server has no TLS. Use it only on a trusted "
                "local network and never expose it to the public internet.",
                file=sys.stderr,
            )
        print("Serving Creative review; press Ctrl-C to stop.")
        if not args.no_open:
            webbrowser.open(server.curator_url)
        server.serve_forever()
    finally:
        server.stop()
    print(f"Review server stopped. Resume with: hacksome resume {hub.run_dir}")
    return 0


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _resume_command(args: argparse.Namespace) -> int:
    hub, state = _creative_run_snapshot(args.run_dir, command="resume")
    status = state.get("status")
    stage = state.get("current_stage")
    wait = state.get("wait")
    completed = status == "completed"
    finalizing = status == "running" and stage == "creative-finalization"
    closed_review = (
        status == "waiting"
        and stage == "creative-human-review"
        and isinstance(wait, dict)
        and wait.get("kind") == "creative_human_review"
        and wait.get("status") == "closed"
    )
    if (
        status == "waiting"
        and stage == "creative-human-review"
        and isinstance(wait, dict)
        and wait.get("kind") == "creative_human_review"
        and wait.get("status") == "open"
    ):
        raise ValueError(
            f"Creative review is still open; continue with `hacksome review {hub.run_dir}`"
        )
    if not (completed or finalizing or closed_review):
        raise ValueError(
            "Creative run is not at a resumable closed-review or "
            "frozen-finalization boundary"
        )

    workflow = CreativeIdeaWorkflow.open(hub.run_dir)
    outcome = asyncio.run(workflow.resume())
    print(f"Run directory: {outcome.run_dir}")
    return _print_creative_outcome(outcome)


def _build_adapter(args: argparse.Namespace) -> SubprocessBuildControlAdapter:
    executable = args.build_python.expanduser().resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError(
            f"--build-python must be an executable file: {executable}"
        )
    return SubprocessBuildControlAdapter(
        build_root=args.build_root,
        build_python=executable,
        max_active_teams=args.max_active_teams,
    )


def _approval_service(
    args: argparse.Namespace,
    *,
    with_build: bool,
) -> ApprovalService:
    return ApprovalService.open(
        args.run_dir,
        approval_root=args.approval_root,
        build_adapter=_build_adapter(args) if with_build else None,
    )


def _approve_command(args: argparse.Namespace) -> int:
    service = _approval_service(args, with_build=True)
    config = ApprovalServerConfig(
        approval_root=service.store.root,
        host=args.host,
        port=args.port,
    )
    server = BuildApprovalServer(service, config)
    try:
        print(f"Build Approval URL: {server.approval_url}")
        print("Serving the Build Dispatch Board; press Ctrl-C to stop.")
        if not args.no_open:
            webbrowser.open(server.approval_url)
        server.serve_forever()
    finally:
        server.stop()
    return 0


def _print_build_snapshot(payload: dict[str, Any]) -> None:
    print(f"Run: {payload['run_id']}")
    print(
        f"Route: {payload['route_id']}/"
        f"{payload['route_contract_version']}"
    )
    print(f"Approval: {payload['approval_status']}")
    print(f"Active cap: {payload['max_active_teams']}")
    if payload.get("source_integrity_error"):
        print(f"Source integrity: {payload['source_integrity_error']}")
    cards = payload.get("cards", [])
    if not cards:
        print("Cards: none")
        return
    print("Cards:")
    for card in cards:
        suffix = f" · {card['team_id']}" if card.get("team_id") else ""
        queue = (
            f" · queue {card['queue_position']}"
            if card.get("queue_position") is not None
            else ""
        )
        print(
            f"  {card['ordinal'] + 1:02d} "
            f"{card['status']}: {card['title']}{suffix}{queue}"
        )


def _build_status_command(args: argparse.Namespace) -> int:
    payload = _approval_service(args, with_build=True).snapshot()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_build_snapshot(payload)
    return 0


def _build_reconcile_command(args: argparse.Namespace) -> int:
    payload = _approval_service(args, with_build=True).reconcile()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_build_snapshot(payload)
    return 0


def _build_validate_command(args: argparse.Namespace) -> int:
    service = _approval_service(args, with_build=False)
    errors = service.validate()
    payload = {
        "valid": not errors,
        "approval_root": str(service.store.root),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    elif errors:
        print(
            f"Build Approval validation failed with {len(errors)} error(s):",
            file=sys.stderr,
        )
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
    else:
        print("Build Approval is valid.")
    return 1 if errors else 0


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} is not valid UTF-8: {path}") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{label} is not valid JSON at line {exc.lineno}, "
            f"column {exc.colno}: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain one JSON object: {path}")
    return value


def _manifest_input_path(manifest_path: Path, relative_path: str) -> Path:
    root = manifest_path.parent.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"benchmark input escapes the manifest directory: {relative_path}"
        ) from exc
    if not candidate.is_file():
        raise ValueError(f"benchmark input file does not exist: {candidate}")
    return candidate


def _read_nonempty_utf8(path: Path, *, label: str) -> None:
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} is not valid UTF-8: {path}") from exc
    if not content.strip():
        raise ValueError(f"{label} must not be empty: {path}")


def _load_benchmark_manifest(
    path: Path,
    *,
    validate_inputs: bool,
) -> BenchmarkManifest:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"benchmark manifest does not exist: {resolved}")
    manifest = BenchmarkManifest.from_mapping(
        _read_json_object(resolved, label="benchmark manifest")
    )
    if not validate_inputs:
        return manifest
    for case in manifest.ordered_cases:
        challenge = _manifest_input_path(resolved, case.challenge_path)
        brief = _manifest_input_path(resolved, case.creative_brief_path)
        _read_nonempty_utf8(
            challenge,
            label=f"challenge for benchmark case {case.case_id}",
        )
        _read_nonempty_utf8(
            brief,
            label=f"Creative Brief for benchmark case {case.case_id}",
        )
        if case.review_fixture_path is not None:
            fixture = _manifest_input_path(
                resolved,
                case.review_fixture_path,
            )
            _read_json_object(
                fixture,
                label=f"review fixture for benchmark case {case.case_id}",
            )
    return manifest


def _benchmark_plan_command(path: Path) -> int:
    manifest = _load_benchmark_manifest(path, validate_inputs=True)
    print("Creative benchmark plan validated; no arms were started.")
    print(f"Benchmark: {manifest.benchmark_id}")
    print(f"Mode: {manifest.mode}")
    print(f"Model: {manifest.model} ({manifest.reasoning_effort})")
    print(f"Cases: {len(manifest.cases)}")
    for case in manifest.ordered_cases:
        if case.comparison_kind == "workflow_vs_oneshot":
            arms = "workflow(memory=off) vs oneshot(memory=off)"
        else:
            arms = "workflow(memory=auto) vs workflow(memory=off)"
        print(
            f"  - {case.case_id}: {case.comparison_kind}; {arms}; "
            "freeze one shared memory snapshot before either arm"
        )
    print(
        "Next: connect a benchmark execution controller, then rerun this "
        "manifest to freeze memory and start its arms."
    )
    return 0


def _exact_object(
    value: Any,
    *,
    fields: frozenset[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown fields: {', '.join(unknown)}")
        raise ValueError(f"{label} has " + "; ".join(details))
    return value


def _object_array(value: Any, *, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(
        isinstance(item, dict) for item in value
    ):
        raise ValueError(f"{label} must be an array of JSON objects")
    return value


def _required_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value


def _blind_binding(value: Any, *, label: str) -> BlindIdeaBinding:
    raw = _exact_object(
        value,
        fields=frozenset(
            {
                "blind_idea_id",
                "source_idea_id",
                "idea_card_sha256",
            }
        ),
        label=label,
    )
    return BlindIdeaBinding(
        blind_idea_id=_required_string(
            raw["blind_idea_id"],
            label=f"{label} blind_idea_id",
        ),
        source_idea_id=_required_string(
            raw["source_idea_id"],
            label=f"{label} source_idea_id",
        ),
        idea_card_sha256=_required_string(
            raw["idea_card_sha256"],
            label=f"{label} idea_card_sha256",
        ),
    )


def _blind_case_map(value: Any) -> BlindCaseMap:
    raw = _exact_object(
        value,
        fields=frozenset(
            {
                "case_id",
                "arm_a_arm_id",
                "arm_b_arm_id",
                "arm_a_ideas",
                "arm_b_ideas",
            }
        ),
        label="blind arm-map case",
    )
    arm_a = _object_array(raw["arm_a_ideas"], label="arm_a_ideas")
    arm_b = _object_array(raw["arm_b_ideas"], label="arm_b_ideas")
    return BlindCaseMap(
        case_id=_required_string(raw["case_id"], label="arm-map case_id"),
        arm_a_arm_id=_required_string(
            raw["arm_a_arm_id"],
            label="arm-map arm_a_arm_id",
        ),
        arm_b_arm_id=_required_string(
            raw["arm_b_arm_id"],
            label="arm-map arm_b_arm_id",
        ),
        arm_a_ideas=tuple(
            _blind_binding(item, label="arm-map Arm A Idea") for item in arm_a
        ),
        arm_b_ideas=tuple(
            _blind_binding(item, label="arm-map Arm B Idea") for item in arm_b
        ),
    )


def _load_blind_packet(
    bench_dir: Path,
    manifest: BenchmarkManifest,
) -> BlindReviewPacket:
    packet_path = bench_dir / "blind-review-packet.json"
    markdown_path = bench_dir / "blind-review-packet.md"
    arm_map_path = bench_dir / "arm-map.json"
    for path, label in (
        (packet_path, "blind review packet"),
        (markdown_path, "blind review Markdown"),
        (arm_map_path, "benchmark arm map"),
    ):
        if not path.is_file():
            raise ValueError(f"{label} does not exist: {path}")
    packet_bytes = packet_path.read_bytes()
    markdown_bytes = markdown_path.read_bytes()
    arm_map_bytes = arm_map_path.read_bytes()
    arm_map = _read_json_object(arm_map_path, label="benchmark arm map")
    raw = _exact_object(
        arm_map,
        fields=frozenset(
            {
                "schema_version",
                "benchmark_id",
                "packet_sha256",
                "cases",
            }
        ),
        label="benchmark arm map",
    )
    if raw["schema_version"] != 1:
        raise ValueError("unsupported benchmark arm-map schema version")
    benchmark_id = _required_string(
        raw["benchmark_id"],
        label="arm-map benchmark_id",
    )
    if benchmark_id != manifest.benchmark_id:
        raise ValueError("arm-map benchmark_id does not match the manifest")
    case_maps = tuple(
        _blind_case_map(item)
        for item in _object_array(raw["cases"], label="arm-map cases")
    )
    expected_case_ids = {case.case_id for case in manifest.cases}
    if {case.case_id for case in case_maps} != expected_case_ids:
        raise ValueError("arm-map case set does not match the benchmark manifest")
    return BlindReviewPacket(
        benchmark_id=benchmark_id,
        mode=manifest.mode,
        packet_sha256=_required_string(
            raw["packet_sha256"],
            label="arm-map packet_sha256",
        ),
        packet_json_bytes=packet_bytes,
        packet_markdown_bytes=markdown_bytes,
        arm_map_json_bytes=arm_map_bytes,
        case_maps=case_maps,
    )


def _benchmark_manifest_in_dir(bench_dir: Path) -> Path:
    candidates = [
        path
        for path in (
            bench_dir / "benchmark-manifest.json",
            bench_dir / "manifest.json",
        )
        if path.is_file()
    ]
    if not candidates:
        raise ValueError(
            "benchmark directory has no benchmark-manifest.json or manifest.json"
        )
    if len(candidates) > 1:
        raise ValueError(
            "benchmark directory has ambiguous manifest files: "
            + ", ".join(str(path) for path in candidates)
        )
    return candidates[0]


def _benchmark_continue_command(
    bench_dir_arg: Path,
    worksheet_path: Path | None,
) -> int:
    bench_dir = bench_dir_arg.expanduser().resolve()
    if not bench_dir.is_dir():
        raise ValueError(f"benchmark directory does not exist: {bench_dir}")
    manifest = _load_benchmark_manifest(
        _benchmark_manifest_in_dir(bench_dir),
        validate_inputs=False,
    )
    packet = _load_blind_packet(bench_dir, manifest)
    worksheet_note = ""
    if worksheet_path is not None:
        worksheet = _read_json_object(
            worksheet_path.expanduser().resolve(),
            label="benchmark worksheet",
        )
        receipt = import_worksheet(packet, worksheet)
        worksheet_note = (
            f" Worksheet {receipt.review_id!r} was validated but not persisted."
        )
    raise ValueError(
        "benchmark continuation is unavailable because this build has no "
        "execution-state controller."
        f"{worksheet_note} No arm was started or resumed and no benchmark "
        "state was changed."
    )


def _benchmark_command(args: argparse.Namespace) -> int:
    continue_dir = getattr(args, "continue_dir", None)
    worksheet = getattr(args, "worksheet", None)
    route = getattr(args, "route", None)
    if args.manifest is not None and continue_dir is not None:
        raise ValueError(
            "benchmark accepts either MANIFEST.json or --continue BENCH_DIR, not both"
        )
    if continue_dir is not None:
        if route is not None:
            raise ValueError("--route is only valid for a benchmark manifest")
        return _benchmark_continue_command(continue_dir, worksheet)
    if args.manifest is None:
        raise ValueError(
            "benchmark requires MANIFEST.json or --continue BENCH_DIR"
        )
    if worksheet is not None:
        raise ValueError("--worksheet requires --continue BENCH_DIR")
    if route != "creative":
        raise ValueError("benchmark manifest mode requires --route creative")
    return _benchmark_plan_command(args.manifest)


def _doctor_payload(result: CodexDoctorResult) -> dict[str, Any]:
    return {
        "healthy": result.healthy,
        "executable": result.executable,
        "available": result.available,
        "version": result.version,
        "authenticated": result.authenticated,
        "capabilities": result.capabilities,
        "error": result.error,
    }


def _doctor_command(args: argparse.Namespace) -> int:
    result = asyncio.run(
        CodexRunner(
            CodexConfig(executable=args.codex, doctor_timeout_seconds=args.timeout)
        ).doctor()
    )
    payload = _doctor_payload(result)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Codex: {'healthy' if result.healthy else 'unhealthy'}")
        print(f"Executable: {result.executable}")
        print(f"Version: {result.version or '-'}")
        print(f"Authenticated: {result.authenticated}")
        if result.error:
            print(f"Error: {result.error}")
    return 0 if result.healthy else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return _run_command(args, parser)
        if args.command == "pitch":
            return _pitch_command(args)
        if args.command == "status":
            return _status_command(args)
        if args.command == "validate":
            return _validate_command(args)
        if args.command == "reconcile":
            return _reconcile_command(args)
        if args.command == "review":
            return _review_command(args)
        if args.command == "resume":
            return _resume_command(args)
        if args.command == "approve":
            return _approve_command(args)
        if args.command == "build-status":
            return _build_status_command(args)
        if args.command == "build-reconcile":
            return _build_reconcile_command(args)
        if args.command == "build-validate":
            return _build_validate_command(args)
        if args.command == "benchmark":
            return _benchmark_command(args)
        if args.command == "doctor":
            return _doctor_command(args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except (
        OSError,
        StateError,
        ValueError,
        WorkflowError,
        PitchWorkflowError,
        CreativeWorkflowError,
        CreativeFeedbackError,
        ApprovalError,
        ApprovalServerError,
        PostCardCatalogError,
        ReviewServerError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parser.error(f"unknown command: {args.command}")
    return 2


__all__ = ["build_parser", "main"]
