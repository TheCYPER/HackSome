# Workspace Index - percy

> Journal tracking for AI development sessions.

---

## Current Status

<!-- @@@auto:current-status -->
- **Active File**: `journal-1.md`
- **Total Sessions**: 1
- **Last Active**: 2026-07-25
<!-- @@@/auto:current-status -->

---

## Active Documents

<!-- @@@auto:active-documents -->
| File | Lines | Status |
|------|-------|--------|
| `journal-1.md` | ~39 | Active |
<!-- @@@/auto:active-documents -->

---

## Session History

<!-- @@@auto:session-history -->
| # | Date | Title | Commits | Branch |
|---|------|-------|---------|--------|
| 1 | 2026-07-25 | Implement Lead reflection memory | `944814b` | `codex/buildfactory-agent-reflection-skill` |
<!-- @@@/auto:session-history -->

---

## Notes

- Sessions are appended to journal files
- New journal file created when current exceeds 2000 lines
- Use `add_session.py` to record sessions
- Communication preference: default to Simplified Chinese for discussion,
  planning artifacts, and human-facing documentation. Keep code identifiers,
  external protocol names, and shared English contracts unchanged when
  translating them would reduce technical precision or make collaboration with
  Weston harder.
- Git collaboration preference: fetch and compare the latest `origin/main`
  before implementation, validation, and PR updates. Commit each validated
  implementation slice separately with a focused message, preserve a readable
  milestone history, and never bundle unrelated Trellis, onboarding, or
  teammate changes into Percy’s commits.