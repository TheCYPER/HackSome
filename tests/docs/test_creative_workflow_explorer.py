from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPLORER_ROOT = REPO_ROOT / "docs" / "creative-workflow-explorer"
APP_PATH = EXPLORER_ROOT / "app.js"
HTML_PATH = EXPLORER_ROOT / "index.html"
CSS_PATH = EXPLORER_ROOT / "styles.css"
EXPECTED_STAGES = [
    "C0",
    "C1",
    "C1W",
    "C2",
    "C3",
    "C4",
    "C5",
    "C6A",
    "C6B",
    "C6 Human",
    "C6C",
    "C7",
]


def _stage_data() -> list[dict[str, object]]:
    source = APP_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"const STAGE_DATA = Object\.freeze\(JSON\.parse\(String\.raw`\n"
        r"(?P<payload>.*?)\n`\)\);",
        source,
        re.DOTALL,
    )
    if match is None:
        raise AssertionError("app.js must expose parseable STAGE_DATA JSON")
    payload = json.loads(match.group("payload"))
    if not isinstance(payload, list):
        raise AssertionError("STAGE_DATA must be a JSON array")
    return payload


class CreativeWorkflowExplorerTests(unittest.TestCase):
    def test_stage_projection_is_complete_and_structured(self) -> None:
        stages = _stage_data()
        self.assertEqual([stage["stageId"] for stage in stages], EXPECTED_STAGES)

        required_fields = {
            "title",
            "actors",
            "goal",
            "inputs",
            "actions",
            "outputs",
            "fanout",
            "gate",
            "failureSemantics",
            "promptFiles",
            "schemaFiles",
            "codeFiles",
            "architecture",
            "actualRun",
            "misconception",
        }
        for stage in stages:
            with self.subTest(stage=stage["stageId"]):
                self.assertTrue(required_fields.issubset(stage))
                for field in ("inputs", "actions", "outputs", "codeFiles"):
                    self.assertTrue(stage[field], f"{stage['stageId']} {field}")

    def test_every_repo_resource_link_exists(self) -> None:
        for stage in _stage_data():
            for field in ("promptFiles", "schemaFiles", "codeFiles"):
                for relative in stage[field]:
                    with self.subTest(stage=stage["stageId"], path=relative):
                        self.assertFalse(str(relative).startswith("/"))
                        self.assertTrue((REPO_ROOT / str(relative)).is_file())

    def test_non_model_nodes_do_not_invent_prompts(self) -> None:
        stages = {stage["stageId"]: stage for stage in _stage_data()}
        for stage_id in ("C6 Human", "C7"):
            with self.subTest(stage=stage_id):
                stage = stages[stage_id]
                self.assertIs(stage["noModelPrompt"], True)
                self.assertEqual(stage["promptFiles"], [])
                self.assertEqual(stage["schemaFiles"], [])
                self.assertIn("没有模型 Prompt", stage["promptAbsence"])

        c6c = stages["C6C"]
        self.assertIn("keep / reject / taste_veto", c6c["promptAbsence"])
        self.assertIn("只有 revise / merge", c6c["promptAbsence"])

    def test_bilibili_trace_and_proxy_diagnostic_are_explicit(self) -> None:
        stages = {stage["stageId"]: stage for stage in _stage_data()}
        c1w = json.dumps(stages["C1W"]["actualRun"], ensure_ascii=False)
        self.assertIn("high-confidence signal", c1w)
        self.assertIn("unavailable", c1w)
        self.assertIn("空 palette", c1w)
        self.assertIn("7 CONCEPTS", stages["C3"]["actualRun"]["status"])
        self.assertIn("7 → 2", stages["C4"]["actualRun"]["status"])
        self.assertIn("2 → 1", stages["C6B"]["actualRun"]["status"])
        human = json.dumps(
            stages["C6 Human"]["actualRun"],
            ensure_ascii=False,
        )
        self.assertIn("synthetic E2E", human)
        self.assertIn("不是 Percy", human)
        self.assertIn("1 FINAL CARD", stages["C7"]["actualRun"]["status"])

        html = HTML_PATH.read_text(encoding="utf-8")
        self.assertIn("当前证据可以 false-pass 人类理解", html)
        self.assertIn("不是人类理解实验", html)

    def test_high_risk_stage_semantics_are_not_overclaimed(self) -> None:
        stages = {stage["stageId"]: stage for stage in _stage_data()}
        self.assertIn("fail-open", stages["C1W"]["failureSemantics"])
        self.assertIn("主线继续到 C2", stages["C1W"]["failureSemantics"])
        self.assertIn("只机械校验", stages["C3"]["architecture"]["diagnostic"])
        self.assertIn(
            "不理解或证明真实 product loop 分类",
            stages["C3"]["architecture"]["diagnostic"],
        )
        c5_actions = " ".join(stages["C5"]["actions"])
        self.assertIn("C5W 不直接输出 feasibility route decision", c5_actions)
        self.assertIn(
            "C5W 执行或验证失败为 fatal",
            stages["C5"]["failureSemantics"],
        )
        self.assertIn(
            "Memory Snapshot 的 hash/provenance 损坏为 fatal",
            stages["C5"]["failureSemantics"],
        )

    def test_controller_owned_output_paths_match_runtime_constants(self) -> None:
        stages = {stage["stageId"]: stage for stage in _stage_data()}
        self.assertIn(
            "input/software-demo-policy.json（Controller-owned、hash-bound）",
            stages["C1"]["outputs"],
        )
        self.assertIn(
            "artifacts/creative/cultural-signals/"
            "creative-cultural-signal-snapshot-r001.json",
            stages["C1W"]["outputs"],
        )
        self.assertIn(
            "state/creative-finalization/finalization-manifest.json",
            stages["C7"]["outputs"],
        )
        self.assertTrue(
            any(
                "artifacts/creative/ideas/creative-idea-" in output
                for output in stages["C6C"]["outputs"]
            )
        )

    def test_static_page_has_accessible_local_controls_and_fallback(self) -> None:
        html = HTML_PATH.read_text(encoding="utf-8")
        app = APP_PATH.read_text(encoding="utf-8")
        css = CSS_PATH.read_text(encoding="utf-8")

        self.assertIn('class="skip-link"', html)
        self.assertIn("<fieldset", html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn("<nav", html)
        self.assertIn("<noscript>", html)
        self.assertIn('href="styles.css"', html)
        self.assertIn('src="app.js"', html)
        self.assertNotRegex(html, r'https?://')

        self.assertIn('button.type = "button"', app)
        self.assertIn('button.setAttribute("aria-pressed"', app)
        self.assertIn('button.addEventListener("focus"', app)
        self.assertIn('button.addEventListener("click"', app)
        self.assertIn("navigator.clipboard", app)
        self.assertIn("textContent", app)
        for unsafe_dom_api in (
            "innerHTML",
            "outerHTML",
            "insertAdjacentHTML",
            "document.write",
        ):
            self.assertNotIn(unsafe_dom_api, app)

        self.assertIn("@media (max-width: 390px)", css)
        self.assertIn("overflow-x: auto", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn("animation: none", css)

    def test_hover_previews_full_detail_and_restores_the_pinned_stage(self) -> None:
        app = APP_PATH.read_text(encoding="utf-8")
        self.assertIn(
            'button.addEventListener("mouseenter", () => '
            "previewStage(stage, true));",
            app,
        )
        self.assertIn(
            'button.addEventListener("mouseleave", restorePinnedStage);',
            app,
        )
        self.assertIn(
            'button.addEventListener("focus", () => previewStage(stage, true));',
            app,
        )


if __name__ == "__main__":
    unittest.main()
