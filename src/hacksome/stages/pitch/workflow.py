"""Deterministic Director -> Reviewer -> HTML -> Script Pitch controller."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol

from hacksome.core.codex import CodexRunner
from hacksome.core.config import CodexConfig, ReasoningEffort
from hacksome.contracts.build_to_pitch import (
    BuildToPitchInput,
    BuildToPitchInputError,
)
from hacksome.core.models import CodexResult, CodexTask
from hacksome.stages.pitch.prompting import pitch_prompt_catalog
from hacksome.core.prompting import PromptCatalog
from hacksome.core.state import atomic_write_bytes, atomic_write_json, atomic_write_text


PITCH_MODEL = "gpt-5.6-sol"
PITCH_REASONING_EFFORT: ReasoningEffort = "xhigh"
PITCH_CONTRACT_VERSION = "1"
PITCH_PROMPT_POLICY_VERSION = "5"
PITCH_STAGE_POLICY_VERSION = "1"
MAX_DIRECTOR_REVISIONS = 1

_OUTLINE_HEADING = re.compile(
    r"^## Slide\s+([A-Za-z0-9][A-Za-z0-9._-]{0,63})(?:\s+[—-].*)?\s*$",
    re.MULTILINE,
)
_SCRIPT_HEADING = re.compile(
    r"^## Slide\s+([A-Za-z0-9][A-Za-z0-9._-]{0,63})\s*$",
    re.MULTILINE,
)
_REVIEW_VERDICT = re.compile(r"^Verdict:\s*(PASS|REVISE)\s*$", re.MULTILINE)
_REVIEW_ISSUE = re.compile(
    r"^- Slide:\s*([A-Za-z0-9][A-Za-z0-9._-]{0,63})\s*\n"
    r"[ \t]+Problem:\s*(\S.*?)\s*\n"
    r"[ \t]+Required change:\s*(\S.*?)\s*$",
    re.MULTILINE,
)
_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_CSS_IMPORT = re.compile(r"@import\b", re.IGNORECASE)
_REQUIRED_KEYS = (
    "ArrowLeft",
    "ArrowRight",
    "PageUp",
    "PageDown",
    "Home",
    "End",
)


class PitchWorkflowError(RuntimeError):
    """The Pitch run violated an input, Agent, or publication contract."""


class Runner(Protocol):
    async def run(self, task: CodexTask) -> CodexResult: ...


class BrowserVerifier(Protocol):
    def executable_path(self) -> str: ...

    def verify(self, html_path: Path, slide_ids: Sequence[str]) -> str: ...


@dataclass(frozen=True, slots=True)
class PitchOutcome:
    run_dir: Path
    output_dir: Path
    deck_outline: Path
    pitch_deck: Path
    pitch_script: Path


@dataclass(slots=True)
class PitchWorkflow:
    """One immutable-snapshot Pitch run and its deterministic controller."""

    run_dir: Path
    catalog: PromptCatalog
    runner: Runner
    browser_verifier: BrowserVerifier
    manifest: dict[str, Any]
    task_timeout_seconds: float

    @classmethod
    def create(
        cls,
        project: str | Path,
        idea_card: str | Path,
        challenge: str | Path,
        output_root: str | Path,
        *,
        codex_config: CodexConfig | None = None,
        runner: Runner | None = None,
        browser_verifier: BrowserVerifier | None = None,
        browser_executable: str | Path | None = None,
        task_timeout_seconds: float | None = None,
    ) -> PitchWorkflow:
        try:
            build_input = BuildToPitchInput.validate(project, idea_card, challenge)
        except BuildToPitchInputError as exc:
            raise PitchWorkflowError(str(exc)) from exc
        source_project = build_input.project_directory
        source_idea_card = build_input.idea_card_file
        source_challenge = build_input.challenge_file
        run_dir = Path(output_root).expanduser().resolve()
        _validate_copy_boundary(source_project, run_dir)
        _validate_project_symlinks(source_project)
        if run_dir.exists():
            raise PitchWorkflowError(f"Pitch output root already exists: {run_dir}")

        selected_config = _pitch_config(codex_config)
        selected_timeout = (
            selected_config.default_timeout_seconds
            if task_timeout_seconds is None
            else task_timeout_seconds
        )
        if (
            isinstance(selected_timeout, bool)
            or not isinstance(selected_timeout, (int, float))
            or selected_timeout <= 0
        ):
            raise PitchWorkflowError("Pitch task timeout must be positive")

        try:
            input_dir = run_dir / "input"
            project_snapshot = input_dir / "project"
            input_dir.mkdir(parents=True)
            shutil.copytree(
                source_project,
                project_snapshot,
                copy_function=shutil.copy2,
                symlinks=True,
            )
            _rewrite_absolute_snapshot_symlinks(source_project, project_snapshot)
            _validate_project_symlinks(project_snapshot)
            shutil.copy2(source_idea_card, input_dir / "idea-card.md")
            shutil.copy2(source_challenge, input_dir / "challenge.md")
            for name in ("director", "review", "html", "script", "output"):
                (run_dir / name).mkdir()
            frozen = pitch_prompt_catalog.freeze(
                run_dir,
                route_id="pitch",
                contract_version=PITCH_CONTRACT_VERSION,
                prompt_policy_version=PITCH_PROMPT_POLICY_VERSION,
                stage_policy_version=PITCH_STAGE_POLICY_VERSION,
            )
        except Exception as exc:
            raise PitchWorkflowError(f"cannot create Pitch snapshot: {exc}") from exc

        manifest: dict[str, Any] = {
            "schema_version": 1,
            "status": "ready",
            "model": PITCH_MODEL,
            "reasoning_effort": PITCH_REASONING_EFFORT,
            "max_director_revisions": MAX_DIRECTOR_REVISIONS,
            "snapshot": {
                "project": "input/project",
                "idea_card": "input/idea-card.md",
                "challenge": "input/challenge.md",
            },
            "source": build_input.source_record(),
            "resources": frozen.manifest_reference(),
            "tasks": [],
            "outputs": None,
        }
        atomic_write_json(run_dir / "pitch-run.json", manifest)
        return cls(
            run_dir=run_dir,
            catalog=frozen.catalog,
            runner=runner or CodexRunner(selected_config),
            browser_verifier=browser_verifier
            or ChromiumBrowserVerifier(browser_executable),
            manifest=manifest,
            task_timeout_seconds=float(selected_timeout),
        )

    @property
    def project_snapshot(self) -> Path:
        return self.run_dir / "input" / "project"

    @property
    def idea_card_path(self) -> Path:
        return self.run_dir / "input" / "idea-card.md"

    @property
    def challenge_path(self) -> Path:
        return self.run_dir / "input" / "challenge.md"

    async def execute(self) -> PitchOutcome:
        if self.manifest["status"] != "ready":
            raise PitchWorkflowError("Pitch workflow can only execute once")
        self.manifest["status"] = "running"
        self._persist_manifest()

        try:
            context = self._base_context()
            director = await self._run_role(
                stage="pitch-director",
                task_id="pitch-director",
                cwd=self.run_dir / "director",
                blocks=(("RUN_MODE", "INITIAL"), *context),
            )
            director_session = _required_session(director, role="Pitch Director")
            outline_path = self.run_dir / "director" / "deck-outline.md"
            outline = _read_artifact(outline_path, label="deck outline")
            outline_ids = validate_outline(outline)

            review = await self._run_reviewer(
                attempt=1,
                outline=outline,
                context=context,
            )
            reviewer_session = _required_session(
                review,
                role="Accuracy Reviewer",
            )
            verdict = validate_review(
                self.run_dir / "review" / "outline-review.md",
                review.structured_output,
                outline_ids,
            )
            if verdict == "REVISE":
                review_text = _read_artifact(
                    self.run_dir / "review" / "outline-review.md",
                    label="outline review",
                )
                revised = await self._run_role(
                    stage="pitch-director",
                    task_id="pitch-director-revision-1",
                    cwd=self.run_dir / "director",
                    blocks=(
                        ("RUN_MODE", "REVISION"),
                        *context,
                        ("CURRENT_OUTLINE", outline),
                        ("OUTLINE_REVIEW", review_text),
                    ),
                    session_id=director_session,
                    resume=True,
                )
                if _required_session(revised, role="Pitch Director revision") != (
                    director_session
                ):
                    raise PitchWorkflowError(
                        "Pitch Director revision did not resume the original session"
                    )
                outline = _read_artifact(outline_path, label="revised deck outline")
                outline_ids = validate_outline(outline)
                review = await self._run_reviewer(
                    attempt=2,
                    outline=outline,
                    context=context,
                    prior_review=review_text,
                    session_id=reviewer_session,
                    resume=True,
                )
                if _required_session(
                    review,
                    role="Accuracy Reviewer verification",
                ) != reviewer_session:
                    raise PitchWorkflowError(
                        "Accuracy Reviewer verification did not resume the "
                        "original session"
                    )
                verdict = validate_review(
                    self.run_dir / "review" / "outline-review.md",
                    review.structured_output,
                    outline_ids,
                )
                if verdict != "PASS":
                    raise PitchWorkflowError(
                        "deck outline still requires revision after the bounded retry"
                    )

            browser_executable = self.browser_verifier.executable_path()
            html_result = await self._run_role(
                stage="pitch-html",
                task_id="pitch-html",
                cwd=self.run_dir / "html",
                blocks=(
                    *context,
                    ("FINAL_DECK_OUTLINE", outline),
                    ("CHROMIUM_EXECUTABLE", browser_executable),
                ),
            )
            html_path = self.run_dir / "html" / "pitch-deck.html"
            html = _read_artifact(html_path, label="pitch deck")
            html_ids = validate_html_contract(html, outline_ids)
            validate_html_agent_check(html_result.structured_output, html_ids)
            browser_name = self.browser_verifier.verify(html_path, html_ids)
            self._record_browser_check(browser_name, html_ids)

            script_result = await self._run_role(
                stage="pitch-script",
                task_id="pitch-script",
                cwd=self.run_dir / "script",
                blocks=(
                    *context,
                    ("FINAL_DECK_PATH", str(html_path.resolve())),
                    ("FINAL_DECK_HTML", html),
                ),
            )
            del script_result
            script_path = self.run_dir / "script" / "pitch-script.md"
            script = _read_artifact(script_path, label="pitch script")
            validate_script(script, html_ids)

            outcome = self._publish(outline_path, html_path, script_path)
            self.manifest["status"] = "completed"
            self.manifest["outputs"] = {
                "deck_outline": "output/deck-outline.md",
                "pitch_deck": "output/pitch-deck.html",
                "pitch_script": "output/pitch-script.md",
            }
            self._persist_manifest()
            return outcome
        except asyncio.CancelledError:
            self.manifest["status"] = "failed"
            self.manifest["error"] = "cancelled"
            self._persist_manifest()
            raise
        except Exception as exc:
            self.manifest["status"] = "failed"
            self.manifest["error"] = str(exc)
            self._persist_manifest()
            if isinstance(exc, PitchWorkflowError):
                raise
            raise PitchWorkflowError(str(exc)) from exc

    async def _run_reviewer(
        self,
        *,
        attempt: int,
        outline: str,
        context: Sequence[tuple[str, str]],
        prior_review: str | None = None,
        session_id: str | None = None,
        resume: bool = False,
    ) -> CodexResult:
        blocks: tuple[tuple[str, str], ...] = (
            ("RUN_MODE", "VERIFICATION" if resume else "INITIAL"),
            *context,
            ("DECK_OUTLINE", outline),
        )
        if prior_review is not None:
            blocks = (*blocks, ("PRIOR_REVIEW", prior_review))
        result = await self._run_role(
            stage="pitch-reviewer",
            task_id=f"pitch-review-{attempt}",
            cwd=self.run_dir / "review",
            blocks=blocks,
            session_id=session_id,
            resume=resume,
        )
        return result

    async def _run_role(
        self,
        *,
        stage: str,
        task_id: str,
        cwd: Path,
        blocks: Sequence[tuple[str, str]],
        session_id: str | None = None,
        resume: bool = False,
    ) -> CodexResult:
        spec = self.catalog.lookup(stage)
        rendered = self.catalog.render(stage, blocks)
        run_log_dir = cwd / "runs" / task_id
        run_log_dir.mkdir(parents=True, exist_ok=False)
        atomic_write_text(run_log_dir / "prompt.md", rendered.text)
        atomic_write_json(
            run_log_dir / "request.json",
            {
                "task_id": task_id,
                "stage": stage,
                "model": PITCH_MODEL,
                "reasoning_effort": PITCH_REASONING_EFFORT,
                "resume": resume,
                "session_id": session_id,
                "prompt": rendered.metadata(),
            },
        )
        task = CodexTask(
            task_id=task_id,
            prompt=rendered.text,
            cwd=cwd,
            output_schema=spec.schema_path,
            web_search=False,
            timeout_seconds=self.task_timeout_seconds,
            session_id=session_id,
            resume=resume,
            log_dir=run_log_dir / "raw",
        )
        try:
            result = await self.runner.run(task)
        except Exception as exc:
            self._record_task_failure(task_id, stage, resume, session_id, exc)
            raise PitchWorkflowError(f"{task_id} failed before completion: {exc}") from exc
        if not result.success:
            message = (
                result.error.message
                if result.error is not None
                else result.status.value
            )
            self._record_task_failure(
                task_id,
                stage,
                resume,
                result.session_id,
                PitchWorkflowError(message),
            )
            raise PitchWorkflowError(f"{task_id} failed: {message}")
        atomic_write_json(run_log_dir / "result.json", _result_record(result))
        try:
            actual_session = _required_session(result, role=stage)
            if resume:
                if actual_session != session_id:
                    raise PitchWorkflowError(
                        f"{task_id} did not resume the requested session"
                    )
            else:
                prior_sessions = {
                    task.get("session_id")
                    for task in self.manifest["tasks"]
                    if task.get("session_id")
                }
                if actual_session in prior_sessions:
                    raise PitchWorkflowError(
                        f"{task_id} did not use a fresh independent session"
                    )
        except PitchWorkflowError as exc:
            self._record_task_failure(
                task_id,
                stage,
                resume,
                result.session_id,
                exc,
            )
            raise
        self.manifest["tasks"].append(
            {
                "task_id": task_id,
                "stage": stage,
                "status": "succeeded",
                "model": PITCH_MODEL,
                "reasoning_effort": PITCH_REASONING_EFFORT,
                "resume": resume,
                "session_id": result.session_id,
            }
        )
        self._persist_manifest()
        return result

    def _record_task_failure(
        self,
        task_id: str,
        stage: str,
        resume: bool,
        session_id: str | None,
        error: Exception,
    ) -> None:
        self.manifest["tasks"].append(
            {
                "task_id": task_id,
                "stage": stage,
                "status": "failed",
                "model": PITCH_MODEL,
                "reasoning_effort": PITCH_REASONING_EFFORT,
                "resume": resume,
                "session_id": session_id,
                "error": str(error),
            }
        )
        self._persist_manifest()

    def _record_browser_check(
        self,
        browser_name: str,
        slide_ids: Sequence[str],
    ) -> None:
        self.manifest["browser_smoke"] = {
            "status": "passed",
            "browser": browser_name,
            "opened": True,
            "rendered_slide_ids": list(slide_ids),
        }
        self._persist_manifest()

    def _base_context(self) -> tuple[tuple[str, str], ...]:
        return (
            ("PROJECT_SNAPSHOT", str(self.project_snapshot.resolve())),
            ("IDEA_CARD", self.idea_card_path.read_text(encoding="utf-8")),
            (
                "HACKATHON_CHALLENGE",
                self.challenge_path.read_text(encoding="utf-8"),
            ),
        )

    def _publish(
        self,
        outline_path: Path,
        html_path: Path,
        script_path: Path,
    ) -> PitchOutcome:
        output_dir = self.run_dir / "output"
        if any(output_dir.iterdir()):
            raise PitchWorkflowError("Pitch output directory is not empty")
        staging_dir = Path(
            tempfile.mkdtemp(prefix=".pitch-output-", dir=self.run_dir)
        )
        staged = (
            (outline_path, staging_dir / "deck-outline.md"),
            (html_path, staging_dir / "pitch-deck.html"),
            (script_path, staging_dir / "pitch-script.md"),
        )
        try:
            for source, destination in staged:
                atomic_write_bytes(destination, source.read_bytes())
            output_dir.rmdir()
            os.replace(staging_dir, output_dir)
        except Exception as exc:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
            output_dir.mkdir(exist_ok=True)
            raise PitchWorkflowError(
                f"could not atomically publish Pitch outputs: {exc}"
            ) from exc
        destinations = tuple(
            output_dir / destination.name for _, destination in staged
        )
        return PitchOutcome(
            run_dir=self.run_dir,
            output_dir=output_dir,
            deck_outline=destinations[0],
            pitch_deck=destinations[1],
            pitch_script=destinations[2],
        )

    def _persist_manifest(self) -> None:
        atomic_write_json(self.run_dir / "pitch-run.json", self.manifest)


class ChromiumBrowserVerifier:
    """Exercise the final file in a real headless Chromium-family browser."""

    def __init__(self, executable: str | Path | None = None) -> None:
        self._requested = Path(executable).expanduser() if executable else None
        self._resolved: Path | None = None

    def executable_path(self) -> str:
        return str(self._resolve_executable())

    def verify(self, html_path: Path, slide_ids: Sequence[str]) -> str:
        executable = Path(self.executable_path())
        with tempfile.TemporaryDirectory(prefix="hacksome-pitch-browser-") as directory:
            temporary_root = Path(directory)
            harness_path = temporary_root / "browser-smoke.html"
            atomic_write_text(
                harness_path,
                _browser_harness(html_path.resolve(), slide_ids),
            )
            command = [
                str(executable),
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--no-first-run",
                "--no-default-browser-check",
                "--run-all-compositor-stages-before-draw",
                "--virtual-time-budget=30000",
                "--window-size=1280,720",
                f"--user-data-dir={temporary_root / 'profile'}",
                "--allow-file-access-from-files",
                "--dump-dom",
                harness_path.as_uri(),
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=40,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise PitchWorkflowError(
                    f"Chromium browser check could not run: {exc}"
                ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip()[-500:]
            raise PitchWorkflowError(
                f"Chromium could not open pitch-deck.html: {detail}"
            )
        if "<html" not in completed.stdout.lower():
            raise PitchWorkflowError("Chromium returned no rendered HTML document")
        evidence_parser = _BrowserEvidenceParser()
        evidence_parser.feed(completed.stdout)
        evidence_parser.close()
        if evidence_parser.evidence is None:
            detail = completed.stderr.strip()[-500:]
            raise PitchWorkflowError(
                "Chromium did not return browser-smoke evidence"
                + (f": {detail}" if detail else "")
            )
        try:
            evidence = json.loads(evidence_parser.evidence)
        except json.JSONDecodeError as exc:
            raise PitchWorkflowError(
                "Chromium returned invalid browser-smoke evidence"
            ) from exc
        if not isinstance(evidence, dict) or evidence.get("ok") is not True:
            evidence_detail = (
                evidence.get("error") if isinstance(evidence, dict) else evidence
            )
            raise PitchWorkflowError(
                f"Chromium browser smoke failed: {evidence_detail}"
            )
        if evidence.get("visited_slide_ids") != list(slide_ids):
            raise PitchWorkflowError(
                "Chromium navigation did not visit every slide in outline order"
            )
        if evidence.get("exercised_keys") != list(_REQUIRED_KEYS) + ["Space"]:
            raise PitchWorkflowError(
                "Chromium browser smoke did not exercise every required key"
            )
        return executable.name

    def _resolve_executable(self) -> Path:
        if self._resolved is not None:
            return self._resolved
        if self._requested is not None:
            candidate = self._requested.resolve()
            if not candidate.is_file() or not os.access(candidate, os.X_OK):
                raise PitchWorkflowError(
                    f"browser executable is unavailable: {candidate}"
                )
            self._resolved = candidate
            return self._resolved
        for candidate in _playwright_headless_shells():
            if candidate.is_file() and os.access(candidate, os.X_OK):
                self._resolved = candidate.resolve()
                return self._resolved
        candidates = (
            shutil.which("google-chrome"),
            shutil.which("google-chrome-stable"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        )
        for raw in candidates:
            if not raw:
                continue
            candidate = Path(raw)
            if candidate.is_file() and os.access(candidate, os.X_OK):
                self._resolved = candidate.resolve()
                return self._resolved
        raise PitchWorkflowError(
            "no Chromium-family browser is available for the required HTML check"
        )


class _DeckHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.slide_ids: list[str] = []
        self.invalid_slide: str | None = None
        self.resource_urls: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = {name.lower(): value for name, value in attrs}
        classes = (values.get("class") or "").split()
        if "slide" in classes:
            slide_id = values.get("id")
            data_slide_id = values.get("data-slide-id")
            if not slide_id or data_slide_id != slide_id:
                self.invalid_slide = (
                    "each .slide must have matching id and data-slide-id"
                )
            else:
                self.slide_ids.append(slide_id)
        if tag == "link" and values.get("href"):
            self.resource_urls.append(values["href"] or "")
        if tag == "script" and values.get("src"):
            self.resource_urls.append(values["src"] or "")
        if tag in {"img", "audio", "video", "source", "iframe"} and values.get("src"):
            self.resource_urls.append(values["src"] or "")


class _BrowserEvidenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.evidence: str | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag != "body":
            return
        values = {name.lower(): value for name, value in attrs}
        self.evidence = values.get("data-pitch-evidence")


def _browser_harness(html_path: Path, slide_ids: Sequence[str]) -> str:
    """Build a disposable wrapper that drives the exact final deck in an iframe."""

    template = """\
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
html, body, iframe { width: 100%; height: 100%; margin: 0; border: 0; overflow: hidden; }
</style>
</head>
<body>
<iframe id="deck" src=__DECK_URI__></iframe>
<script>
(() => {
  const expected = __EXPECTED_IDS__;
  const exercisedKeys = ["ArrowLeft", "ArrowRight", "PageUp", "PageDown", "Home", "End", "Space"];
  const frame = document.getElementById("deck");
  let finished = false;

  function finish(payload) {
    if (finished) return;
    finished = true;
    document.body.setAttribute("data-pitch-evidence", JSON.stringify(payload));
  }

  const deadline = setTimeout(
    () => finish({ok: false, error: "browser smoke timed out"}),
    25000,
  );

  const settle = () => new Promise((resolve) => setTimeout(resolve, 500));

  function keyDetails(name) {
    if (name === "Space") {
      return {key: " ", code: "Space", keyCode: 32, which: 32};
    }
    const codes = {
      ArrowLeft: 37,
      ArrowRight: 39,
      PageUp: 33,
      PageDown: 34,
      Home: 36,
      End: 35,
    };
    return {key: name, code: name, keyCode: codes[name], which: codes[name]};
  }

  frame.addEventListener("load", async () => {
    try {
      const win = frame.contentWindow;
      const doc = frame.contentDocument;
      if (!win || !doc) throw new Error("deck iframe is not readable");
      await settle();

      const slides = expected.map((id) => {
        const element = doc.getElementById(id);
        if (!element || !element.classList.contains("slide")) {
          throw new Error(`rendered deck is missing .slide#${id}`);
        }
        return element;
      });

      function activeId() {
        const candidates = slides.map((element) => {
          const style = win.getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          const left = Math.max(0, rect.left);
          const right = Math.min(win.innerWidth, rect.right);
          const top = Math.max(0, rect.top);
          const bottom = Math.min(win.innerHeight, rect.bottom);
          const area = Math.max(0, right - left) * Math.max(0, bottom - top);
          const opacity = Number.parseFloat(style.opacity || "1");
          const visible = (
            style.display !== "none"
            && style.visibility !== "hidden"
            && opacity > 0.01
            && area > 1
          );
          const explicit = (
            element.classList.contains("active")
            || element.classList.contains("current")
            || element.classList.contains("is-active")
            || element.getAttribute("aria-current") === "true"
          );
          return {id: element.id, score: visible ? area * opacity : 0, explicit};
        });
        const explicit = candidates.filter((candidate) => candidate.explicit);
        if (explicit.length === 1 && explicit[0].score > 0) return explicit[0].id;
        candidates.sort((left, right) => right.score - left.score);
        if (!candidates[0] || candidates[0].score <= 0) return null;
        if (
          candidates[1]
          && candidates[1].score >= candidates[0].score * 0.99
        ) return null;
        return candidates[0].id;
      }

      function assertPresentationFit(id) {
        const slide = doc.getElementById(id);
        if (!slide) throw new Error(`cannot inspect missing slide ${id}`);
        let stage = slide;
        let stageRect = null;
        while (
          stage
          && stage !== doc.body
          && stage !== doc.documentElement
        ) {
          const candidate = stage.getBoundingClientRect();
          const ratio = candidate.width / candidate.height;
          if (
            Number.isFinite(ratio)
            && candidate.width > 0
            && candidate.height > 0
            && Math.abs(ratio - (16 / 9)) <= 0.02
          ) {
            stageRect = candidate;
            break;
          }
          stage = stage.parentElement;
        }
        if (!stageRect) {
          const rect = slide.getBoundingClientRect();
          throw new Error(
            `slide ${id} is not rendered at 16:9 (${rect.width}x${rect.height})`,
          );
        }
        if (
          slide.scrollWidth > slide.clientWidth + 2
          || slide.scrollHeight > slide.clientHeight + 2
        ) {
          throw new Error(`slide ${id} overflows its rendered box`);
        }
        if (
          doc.documentElement.scrollWidth > win.innerWidth + 2
          || doc.documentElement.scrollHeight > win.innerHeight + 2
        ) {
          throw new Error(`deck viewport overflows while ${id} is active`);
        }
      }

      async function press(name, expectedId) {
        const details = keyDetails(name);
        const target = doc.activeElement || doc.body || doc.documentElement;
        target.dispatchEvent(new win.KeyboardEvent(
          "keydown",
          {...details, bubbles: true, cancelable: true},
        ));
        target.dispatchEvent(new win.KeyboardEvent(
          "keyup",
          {...details, bubbles: true, cancelable: true},
        ));
        await settle();
        const actual = activeId();
        if (actual !== expectedId) {
          throw new Error(
            `${name} should activate ${expectedId}, observed ${actual || "none/ambiguous"}`,
          );
        }
        assertPresentationFit(actual);
      }

      const visited = [];
      await press("Home", expected[0]);
      visited.push(expected[0]);
      for (let index = 1; index < expected.length; index += 1) {
        await press("ArrowRight", expected[index]);
        visited.push(expected[index]);
      }
      await press(
        "ArrowLeft",
        expected.length > 1 ? expected[expected.length - 2] : expected[0],
      );
      await press("End", expected[expected.length - 1]);
      await press(
        "PageUp",
        expected.length > 1 ? expected[expected.length - 2] : expected[0],
      );
      await press("PageDown", expected[expected.length - 1]);
      await press("Home", expected[0]);
      await press("Space", expected.length > 1 ? expected[1] : expected[0]);

      clearTimeout(deadline);
      finish({
        ok: true,
        visited_slide_ids: visited,
        exercised_keys: exercisedKeys,
        viewport: [win.innerWidth, win.innerHeight],
      });
    } catch (error) {
      clearTimeout(deadline);
      finish({ok: false, error: String(error && error.message || error)});
    }
  }, {once: true});
})();
</script>
</body>
</html>
"""
    return (
        template.replace("__DECK_URI__", json.dumps(html_path.as_uri()))
        .replace("__EXPECTED_IDS__", json.dumps(list(slide_ids)))
    )


def validate_outline(markdown: str) -> tuple[str, ...]:
    matches = list(_OUTLINE_HEADING.finditer(markdown))
    if not matches:
        raise PitchWorkflowError("deck outline contains no valid Slide headings")
    slide_ids = tuple(match.group(1) for match in matches)
    if len(set(slide_ids)) != len(slide_ids):
        raise PitchWorkflowError("deck outline contains duplicate slide IDs")
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        section = markdown[match.end() : end]
        for field in ("Purpose:", "On-slide:", "Visual:"):
            if not re.search(rf"^{re.escape(field)}\s*\S", section, re.MULTILINE):
                raise PitchWorkflowError(
                    f"outline slide {slide_ids[index]} is missing non-empty {field}"
                )
    return slide_ids


def validate_review(
    path: Path,
    structured_output: dict[str, Any],
    outline_ids: Sequence[str],
) -> str:
    markdown = _read_artifact(path, label="outline review")
    match = _REVIEW_VERDICT.search(markdown)
    if match is None:
        raise PitchWorkflowError("outline review has no legal Verdict")
    file_verdict = match.group(1)
    structured_verdict = structured_output.get("verdict")
    issues = structured_output.get("issues")
    if structured_verdict not in {"PASS", "REVISE"} or not isinstance(issues, list):
        raise PitchWorkflowError("Reviewer structured result is invalid")
    if structured_verdict != file_verdict:
        raise PitchWorkflowError(
            "Reviewer file verdict does not match its structured result"
        )
    parsed_issues = _parse_review_file_issues(markdown, file_verdict)
    if len(issues) > 10:
        raise PitchWorkflowError("Reviewer returned more than ten issues")
    normalized_issues: list[dict[str, str]] = []
    for issue in issues:
        if not isinstance(issue, dict) or set(issue) != {
            "slide_id",
            "problem",
            "required_change",
        }:
            raise PitchWorkflowError("Reviewer structured issue is invalid")
        if not all(
            isinstance(issue[key], str) and issue[key].strip()
            for key in ("slide_id", "problem", "required_change")
        ):
            raise PitchWorkflowError("Reviewer structured issue is invalid")
        normalized_issues.append(
            {
                "slide_id": issue["slide_id"].strip(),
                "problem": issue["problem"].strip(),
                "required_change": issue["required_change"].strip(),
            }
        )
    if normalized_issues != parsed_issues:
        raise PitchWorkflowError(
            "Reviewer file issues do not exactly match its structured result"
        )
    unknown_ids = [
        issue["slide_id"]
        for issue in normalized_issues
        if issue["slide_id"] not in outline_ids
    ]
    if unknown_ids:
        raise PitchWorkflowError(
            "Reviewer issues reference unknown slide IDs: " + ", ".join(unknown_ids)
        )
    return file_verdict


def _parse_review_file_issues(
    markdown: str,
    verdict: str,
) -> list[dict[str, str]]:
    issue_heading = re.search(r"^## Issues\s*$", markdown, re.MULTILINE)
    if verdict == "PASS":
        if issue_heading is not None or _REVIEW_ISSUE.search(markdown):
            raise PitchWorkflowError("PASS review must not contain issues")
        return []
    if issue_heading is None:
        raise PitchWorkflowError("REVISE review must contain an Issues section")
    issues_text = markdown[issue_heading.end() :]
    matches = list(_REVIEW_ISSUE.finditer(issues_text))
    if not matches:
        raise PitchWorkflowError("REVISE review must contain at least one issue")
    if len(matches) > 10:
        raise PitchWorkflowError("Reviewer returned more than ten issues")
    unmatched = _REVIEW_ISSUE.sub("", issues_text).strip()
    if unmatched:
        raise PitchWorkflowError("outline review contains malformed issue text")
    return [
        {
            "slide_id": match.group(1).strip(),
            "problem": match.group(2).strip(),
            "required_change": match.group(3).strip(),
        }
        for match in matches
    ]


def validate_html_contract(
    html: str,
    outline_ids: Sequence[str],
) -> tuple[str, ...]:
    parser = _DeckHTMLParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:
        raise PitchWorkflowError(f"pitch deck HTML cannot be parsed: {exc}") from exc
    if parser.invalid_slide is not None:
        raise PitchWorkflowError(parser.invalid_slide)
    html_ids = tuple(parser.slide_ids)
    if html_ids != tuple(outline_ids):
        raise PitchWorkflowError(
            "HTML slide IDs/order do not exactly match the final outline"
        )
    if len(set(html_ids)) != len(html_ids):
        raise PitchWorkflowError("HTML contains duplicate slide IDs")
    missing_keys = [key for key in _REQUIRED_KEYS if key not in html]
    if missing_keys or not re.search(r"(?:event|e)\.key", html):
        raise PitchWorkflowError(
            "HTML deck is missing required keyboard navigation handlers"
        )
    if "Space" not in html and not re.search(r"['\"] ['\"]", html):
        raise PitchWorkflowError("HTML deck is missing Space-key navigation")
    invalid_resources = [
        value
        for value in parser.resource_urls
        if value and not value.startswith(("data:", "#"))
    ]
    css_urls = [match.group(2).strip() for match in _CSS_URL.finditer(html)]
    invalid_css_urls = [
        value
        for value in css_urls
        if value and not value.startswith(("data:", "#"))
    ]
    if invalid_resources or invalid_css_urls or _CSS_IMPORT.search(html):
        raise PitchWorkflowError(
            "pitch-deck.html must not depend on external or sibling resources"
        )
    return html_ids


def validate_html_agent_check(
    structured_output: dict[str, Any],
    html_ids: Sequence[str],
) -> None:
    browser_check = structured_output.get("browser_check")
    if not isinstance(browser_check, dict):
        raise PitchWorkflowError("HTML Agent returned no browser-check evidence")
    if (
        browser_check.get("opened") is not True
        or browser_check.get("keyboard_navigation") is not True
        or browser_check.get("checked_slide_ids") != list(html_ids)
    ):
        raise PitchWorkflowError(
            "HTML Agent browser-check evidence does not cover the final slides"
        )


def validate_script(markdown: str, html_ids: Sequence[str]) -> None:
    matches = list(_SCRIPT_HEADING.finditer(markdown))
    script_ids = tuple(match.group(1) for match in matches)
    if script_ids != tuple(html_ids):
        raise PitchWorkflowError(
            "script slide IDs/order do not exactly match the final HTML"
        )
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        if not markdown[match.end() : end].strip():
            raise PitchWorkflowError(
                f"pitch script has no spoken content for slide {script_ids[index]}"
            )


def _pitch_config(config: CodexConfig | None) -> CodexConfig:
    selected = config or CodexConfig()
    return replace(
        selected,
        model=PITCH_MODEL,
        reasoning_effort=PITCH_REASONING_EFFORT,
        sandbox="workspace-write",
        max_concurrency=1,
    )


def _playwright_headless_shells() -> tuple[Path, ...]:
    roots: list[Path] = []
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured and configured != "0":
        roots.append(Path(configured).expanduser())
    roots.extend(
        (
            Path.home() / "Library" / "Caches" / "ms-playwright",
            Path.home() / ".cache" / "ms-playwright",
        )
    )
    matches: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved_root = root.resolve()
        if resolved_root in seen or not resolved_root.is_dir():
            continue
        seen.add(resolved_root)
        matches.extend(
            sorted(
                resolved_root.glob(
                    "chromium_headless_shell-*/"
                    "chrome-headless-shell-*/chrome-headless-shell"
                ),
                reverse=True,
            )
        )
    return tuple(matches)


def _required_directory(path: str | Path, *, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        raise PitchWorkflowError(f"{label} directory does not exist: {resolved}")
    return resolved


def _required_nonempty_file(path: str | Path, *, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise PitchWorkflowError(f"{label} file does not exist: {resolved}")
    if not resolved.read_bytes().strip():
        raise PitchWorkflowError(f"{label} file is empty: {resolved}")
    return resolved


def _validate_copy_boundary(source: Path, destination: Path) -> None:
    if destination == source or destination.is_relative_to(source):
        raise PitchWorkflowError(
            "Pitch output root must not be the Project or live inside it"
        )
    if source.is_relative_to(destination):
        raise PitchWorkflowError(
            "Pitch output root must not contain the source Project"
        )


def _project_symlinks(root: Path) -> tuple[Path, ...]:
    links: list[Path] = []
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_names.sort()
        file_names.sort()
        parent = Path(directory)
        for name in (*directory_names, *file_names):
            candidate = parent / name
            if candidate.is_symlink():
                links.append(candidate)
    return tuple(links)


def _validate_project_symlinks(root: Path) -> None:
    for link in _project_symlinks(root):
        relative = link.relative_to(root)
        try:
            target = link.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise PitchWorkflowError(
                f"Project symlink is broken or cyclic: {relative}"
            ) from exc
        if not target.is_relative_to(root):
            raise PitchWorkflowError(
                f"Project symlink escapes the Project snapshot boundary: {relative}"
            )


def _rewrite_absolute_snapshot_symlinks(source: Path, snapshot: Path) -> None:
    for snapshot_link in _project_symlinks(snapshot):
        raw_target = Path(os.readlink(snapshot_link))
        if not raw_target.is_absolute():
            continue
        relative = snapshot_link.relative_to(snapshot)
        source_link = source / relative
        try:
            source_target = source_link.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise PitchWorkflowError(
                f"Project symlink changed while snapshotting: {relative}"
            ) from exc
        if not source_target.is_relative_to(source):
            raise PitchWorkflowError(
                f"Project symlink escapes the Project snapshot boundary: {relative}"
            )
        snapshot_target = snapshot / source_target.relative_to(source)
        rewritten_target = os.path.relpath(snapshot_target, snapshot_link.parent)
        snapshot_link.unlink()
        snapshot_link.symlink_to(
            rewritten_target,
            target_is_directory=source_target.is_dir(),
        )


def _read_artifact(path: Path, *, label: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise PitchWorkflowError(f"{label} is missing: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PitchWorkflowError(f"cannot read {label}: {exc}") from exc
    if not text.strip():
        raise PitchWorkflowError(f"{label} is empty: {path}")
    return text


def _required_session(result: CodexResult, *, role: str) -> str:
    if result.session_id is None or not result.session_id.strip():
        raise PitchWorkflowError(f"{role} returned no resumable session ID")
    return result.session_id


def _result_record(result: CodexResult) -> dict[str, Any]:
    return {
        "task_id": result.task_id,
        "status": result.status.value,
        "session_id": result.session_id,
        "structured_output": result.structured_output,
        "usage": result.usage,
        "attempts": result.attempts,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "duration_seconds": result.duration_seconds,
    }


__all__ = [
    "MAX_DIRECTOR_REVISIONS",
    "PITCH_MODEL",
    "PITCH_REASONING_EFFORT",
    "BrowserVerifier",
    "ChromiumBrowserVerifier",
    "PitchOutcome",
    "PitchWorkflow",
    "PitchWorkflowError",
    "validate_html_agent_check",
    "validate_html_contract",
    "validate_outline",
    "validate_review",
    "validate_script",
]
