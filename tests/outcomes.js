"use strict";

const assert = require("node:assert/strict");
const Outcome = require("../outcome-model.js");

const context = { consentRevision: 3, guides: [{ id: "daily", version: 2 }] };
const base = {
  consentRevision: 3,
  guideScope: [{ id: "daily", version: 2, title: "普通情境", source: "照护者", actorId: "caregiver", level: "here", rule: "现场可处理" }],
  redLines: ["无法唤醒"],
  participants: { caregiver: { id: "c", label: "照护者" }, substitute: { id: "s", label: "替班者" }, careRecipient: { id: "r", label: "本人" } },
  mode: "single-device",
  startedAt: "2026-07-25T08:00:00.000Z",
};

function ended(stage = "observe", status = "completed", overrides = {}) {
  let record = Outcome.createSession({ ...base, id: `test-${stage}-${status}-${Math.random()}`, stage, plannedDurationMinutes: stage === "observe" ? 5 : 20 });
  record = Outcome.endSession(record, {
    status,
    endedAt: "2026-07-25T08:20:00.000Z",
    actualElapsedSeconds: 1200,
    completedSteps: [true, true, true],
    routineUpdatesQueued: 2,
    pendingGaps: [],
    urgentAlertsRaised: 0,
    contactActionsOpened: [],
    ...overrides,
  });
  return record;
}

function fullyReported(record, caregiverChoice = "extend", substituteChoice = "extend", overrides = {}) {
  let result = Outcome.withCheckIn(record, "caregiver", { restHappened: record.startSnapshot.stage === "observe" ? "not-planned" : "yes", phoneChecks: "1-2", nonurgentInterrupted: "no", confidence: 4, feltUnsafe: false, choice: caregiverChoice, ...overrides.caregiver });
  result = Outcome.withCheckIn(result, "substitute", { ableToHandle: "yes", uncertainStep: "没有", contactedCaregiver: "no", feltUnsafe: false, choice: substituteChoice, ...overrides.substitute });
  return result;
}

assert.deepEqual(Outcome.recommendation([], context), { stage: "observe", decision: "measure", reasons: ["还没有实际彩排记录"], sourceSessionId: null, canExtend: false }, "real empty state has no invented outcome");

for (const stage of Outcome.STAGES) {
  const record = ended(stage);
  assert.equal(record.id.startsWith("test-"), true);
  assert.equal(record.startSnapshot.stage, stage);
  assert.equal(record.startSnapshot.consentRevision, 3);
  assert.equal(record.startSnapshot.guideScope[0].version, 2);
  assert.equal(record.facts.sourceType, "application-record");
  assert.equal(record.facts.actualElapsedSeconds, 1200);
}

const partial = Outcome.withCheckIn(ended("observe"), "caregiver", { restHappened: "not-planned", choice: "extend" });
assert.equal(Outcome.recommendation([partial], context).decision, "hold", "partial answers never extend");

const differing = fullyReported(ended("short-leave"), "extend", "repeat");
assert.equal(Outcome.recommendation([differing], context).decision, "repeat", "differing extend/repeat choices keep the level");
assert.equal(Outcome.recommendation([fullyReported(ended("short-leave"), "repeat", "repeat")], context).stage, "short-leave");
assert.equal(Outcome.recommendation([fullyReported(ended("short-leave"), "extend", "step-back")], context).stage, "observe", "one step-back immediately recommends the previous stage");

const medical = fullyReported(ended("short-leave", "completed", { pendingGaps: [{ id: "m", risk: "medical", status: "pending" }] }));
assert.equal(Outcome.recommendation([medical], context).decision, "medical-hold", "unresolved medical gap holds the stage");
const urgent = fullyReported(ended("short-leave", "completed", { urgentAlertsRaised: 1 }));
assert.equal(Outcome.recommendation([urgent], context).decision, "medical-hold", "urgent event conservatively holds the stage");

for (const status of ["interrupted", "abandoned", "expired", "revoked", "disconnected"]) {
  assert.equal(Outcome.recommendation([fullyReported(ended("short-leave", status))], context).decision, "hold", `${status} is not silently counted as completed`);
}
assert.equal(Outcome.recommendation([fullyReported(ended("short-leave", "interrupted"), "repeat", "step-back")], context).stage, "observe", "step-back is immediate even when the session did not complete");

const extend = fullyReported(ended("short-leave"));
assert.equal(Outcome.recommendation([extend], context).stage, "quiet-handoff", "both explicit extend answers can extend only with complete facts");
assert.equal(Outcome.recommendation([extend], { ...context, overrideStage: "observe" }).stage, "observe", "caregiver downward override wins");
assert.equal(Outcome.recommendation([extend], { ...context, consentRevision: 4 }).decision, "hold", "stale consent invalidates the recommendation");
assert.equal(Outcome.recommendation([extend], { ...context, guides: [{ id: "daily", version: 3 }] }).decision, "hold", "stale guide invalidates the recommendation");

const unsafe = fullyReported(ended("observe"), "extend", "extend", { substitute: { feltUnsafe: true } });
assert.equal(Outcome.recommendation([unsafe], context).decision, "hold", "reported unsafe feeling prevents extension");

const duplicateId = ended("short-leave");
assert.equal([Outcome.normalizeSession(duplicateId), Outcome.normalizeSession(duplicateId)].filter((item, index, all) => all.findIndex((candidate) => candidate.id === item.id) === index).length, 1, "stable IDs support idempotent snapshot application");

const metrics = Outcome.metrics([ended("observe"), ended("short-leave"), ended("quiet-handoff", "interrupted")]);
assert.deepEqual(metrics, { protectedMinutes: 20, independentHandoffs: 1, routineUpdatesDeferred: 6, urgentEvents: 0, actualRecords: 3, lastCaregiverConfidence: null, lastChoice: null }, "home metrics use factual records only");

const withContact = ended("short-leave", "completed", { contactActionsOpened: [{ at: "2026-07-25T08:10:00.000Z", target: "caregiver" }] });
assert.equal(withContact.facts.contactActionsOpened[0].label, "已打开联系操作（不代表通话接通）");

const redacted = Outcome.redactSession({ ...fullyReported(withContact), redacted: true }, ["daily"]);
assert.equal(redacted.redacted, true);
assert.deepEqual(redacted.startSnapshot.participants, {});
assert.deepEqual(redacted.startSnapshot.redLines, []);
assert.equal(redacted.checkIns.caregiver, null);
assert.equal(redacted.facts.actualElapsedSeconds, 1200, "withdrawal keeps only appropriate non-identifying facts");

const legacy = Outcome.normalizeSession({ id: "old", status: "legacy", startSnapshot: { stage: "short-leave" } });
assert.equal(legacy.facts, null);
assert.equal(Outcome.metrics([legacy]).actualRecords, 0, "legacy completion does not fabricate metrics");

console.log("Outcome model passed: empty state, all stages, partial/differing choices, conservative holds, terminal statuses, stale authorization, idempotency, truthful metrics, contact labels, and withdrawal redaction");
