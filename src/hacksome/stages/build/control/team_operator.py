"""Fixed operator CLI for Team authorization, pool reconcile, and control."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from hacksome.stages.build.control.handoff import BuildAuthorizationEnvelopeV1, HandoffError
from hacksome.stages.build.control.runtime_store import StoreError
from hacksome.stages.build.control.team_pool import (
    ComposeTeamLifecycle,
    FakeTeamLifecycle,
    TeamLifecycle,
    TeamPool,
)
from hacksome.stages.build.control.team_registry import TeamRegistry


MAX_STDIN_BYTES = 16 * 1024 * 1024


class TeamOperator:
    def __init__(
        self,
        *,
        build_root: str | Path,
        lifecycle: TeamLifecycle,
        max_active_teams: int = 2,
    ) -> None:
        self.registry = TeamRegistry(build_root)
        self.pool = TeamPool(
            self.registry,
            lifecycle,
            max_active_teams=max_active_teams,
        )
        self.max_active_teams = max_active_teams

    def authorize(self, value: Any) -> dict[str, Any]:
        envelope = BuildAuthorizationEnvelopeV1.from_mapping(value)
        row = self.registry.authorize(envelope)
        self.pool.reconcile()
        row = self.registry.get(row["team_id"])
        observed = row["observed_state"]
        if observed in {"resuming", "pausing"}:
            observed = "starting"
        elif observed == "paused":
            observed = "active"
        observed = self.registry.record_authorization_receipt_state(
            row["team_id"],
            observed,
        )
        return {
            "schema_version": 1,
            "authorization_id": row["authorization_id"],
            "team_id": row["team_id"],
            "identity_sha256": row["identity_sha256"],
            "observed_state": observed,
        }

    def _status(self) -> dict[str, Any]:
        rows = self.registry.list()
        queued = sorted(
            (
                row
                for row in rows
                if row["observed_state"] == "queued"
            ),
            key=lambda row: (row["enqueue_seq"], row["team_id"]),
        )
        positions = {
            row["team_id"]: index
            for index, row in enumerate(queued, start=1)
        }
        return {
            "schema_version": 1,
            "max_active_teams": self.max_active_teams,
            "teams": [
                {
                    "team_id": row["team_id"],
                    "desired_state": row["desired_state"],
                    "observed_state": row["observed_state"],
                    "queue_position": positions.get(row["team_id"]),
                }
                for row in rows
            ],
        }

    def list(self) -> dict[str, Any]:
        return self._status()

    def inspect(self, team_id: str) -> dict[str, Any]:
        row = self.registry.get(team_id)
        status = next(
            team
            for team in self._status()["teams"]
            if team["team_id"] == team_id
        )
        return {
            "schema_version": 1,
            "team": status,
            "authorization_id": row["authorization_id"],
            "source_run_id": row["source_run_id"],
            "idea_card_id": row["idea_card_id"],
            "idea_card_sha256": row["idea_card_sha256"],
            "attempts": row["attempts"],
            "last_error": row["last_error"],
        }

    def reconcile(self) -> dict[str, Any]:
        self.pool.reconcile(retry_errors=True)
        return self._status()

    def pause(self, team_id: str, *, request_id: str) -> dict[str, Any]:
        self.pool.pause(team_id, request_id=request_id)
        return self.inspect(team_id)

    def resume(self, team_id: str, *, request_id: str) -> dict[str, Any]:
        self.pool.resume(team_id, request_id=request_id)
        return self.inspect(team_id)


def _common(command: argparse.ArgumentParser) -> None:
    command.add_argument("--build-root", type=Path, required=True)
    command.add_argument("--max-active-teams", type=int, default=2)
    command.add_argument("--json", action="store_true")
    command.add_argument(
        "--fake-lifecycle",
        action="store_true",
        help=argparse.SUPPRESS,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="team_operator")
    commands = parser.add_subparsers(dest="command", required=True)
    authorize = commands.add_parser("authorize")
    _common(authorize)
    authorize.add_argument("--json-stdin", action="store_true", required=True)
    for name in ("list", "reconcile"):
        command = commands.add_parser(name)
        _common(command)
    inspect = commands.add_parser("inspect")
    _common(inspect)
    inspect.add_argument("team_id")
    for name in ("pause", "resume"):
        command = commands.add_parser(name)
        _common(command)
        command.add_argument("team_id")
        command.add_argument("--request-id", required=True)
    return parser


def _stdin_json() -> dict[str, Any]:
    raw = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
    if len(raw) > MAX_STDIN_BYTES:
        raise HandoffError("operator input exceeds the safety limit")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HandoffError("operator input is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise HandoffError("operator input must be one JSON object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        lifecycle: TeamLifecycle
        if args.fake_lifecycle:
            lifecycle = FakeTeamLifecycle()
        else:
            lifecycle = ComposeTeamLifecycle()
        operator = TeamOperator(
            build_root=args.build_root,
            lifecycle=lifecycle,
            max_active_teams=args.max_active_teams,
        )
        if args.command == "authorize":
            result = operator.authorize(_stdin_json())
        elif args.command == "list":
            result = operator.list()
        elif args.command == "inspect":
            result = operator.inspect(args.team_id)
        elif args.command == "reconcile":
            result = operator.reconcile()
        elif args.command == "pause":
            result = operator.pause(
                args.team_id,
                request_id=args.request_id,
            )
        elif args.command == "resume":
            result = operator.resume(
                args.team_id,
                request_id=args.request_id,
            )
        else:
            raise StoreError(f"unknown operator command: {args.command}")
    except (HandoffError, StoreError, ValueError) as exc:
        print(
            json.dumps(
                {"code": type(exc).__name__, "message": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["TeamOperator", "build_parser", "main"]
