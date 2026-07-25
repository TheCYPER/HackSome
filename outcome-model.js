(function initOutcomeModel(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.RelayOutcomeModel = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function outcomeModelFactory() {
  "use strict";

  const VERSION = 1;
  const STAGES = Object.freeze(["observe", "short-leave", "quiet-handoff"]);
  const CHOICES = Object.freeze(["extend", "repeat", "step-back"]);
  const TERMINAL_STATUSES = Object.freeze(["completed", "interrupted", "abandoned", "expired", "revoked", "disconnected"]);
  const STAGE_LABELS = Object.freeze({
    observe: "在旁观察",
    "short-leave": "短时离开",
    "quiet-handoff": "安静接班",
  });
  const STATUS_LABELS = Object.freeze({
    active: "进行中",
    completed: "现场完成",
    interrupted: "中途结束",
    abandoned: "已放弃",
    expired: "连接到期",
    revoked: "授权撤回",
    disconnected: "连接中断后结束",
    legacy: "较早完成 · 未记录详细结果",
  });

  function clone(value) {
    if (value == null) return value;
    return JSON.parse(JSON.stringify(value));
  }

  function stableId(prefix = "session") {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return `${prefix}-${crypto.randomUUID()}`;
    return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  }

  function stageIndex(stage) {
    const index = STAGES.indexOf(stage);
    return index < 0 ? 0 : index;
  }

  function previousStage(stage) {
    return STAGES[Math.max(0, stageIndex(stage) - 1)];
  }

  function nextStage(stage) {
    return STAGES[Math.min(STAGES.length - 1, stageIndex(stage) + 1)];
  }

  function normalizeChoice(value) {
    return CHOICES.includes(value) ? value : null;
  }

  function normalizeCheckIn(value, role) {
    if (!value || typeof value !== "object") return null;
    const base = {
      schemaVersion: VERSION,
      role,
      sourceType: "self-report",
      respondentId: String(value.respondentId || role),
      submittedAt: value.submittedAt || null,
      partial: value.partial !== false,
    };
    if (role === "caregiver") return {
      ...base,
      restHappened: ["yes", "partly", "no", "not-planned", "unsure"].includes(value.restHappened) ? value.restHappened : null,
      phoneChecks: ["0", "1-2", "3-5", "6+", "unsure"].includes(String(value.phoneChecks)) ? String(value.phoneChecks) : null,
      nonurgentInterrupted: ["yes", "no", "unsure"].includes(value.nonurgentInterrupted) ? value.nonurgentInterrupted : null,
      confidence: Number.isInteger(Number(value.confidence)) && Number(value.confidence) >= 1 && Number(value.confidence) <= 5 ? Number(value.confidence) : null,
      feltUnsafe: typeof value.feltUnsafe === "boolean" ? value.feltUnsafe : null,
      choice: normalizeChoice(value.choice),
      notes: String(value.notes || "").slice(0, 500),
    };
    if (role === "substitute") return {
      ...base,
      ableToHandle: ["yes", "partly", "no", "unsure"].includes(value.ableToHandle) ? value.ableToHandle : null,
      uncertainStep: String(value.uncertainStep || "").slice(0, 500),
      contactedCaregiver: ["yes", "no", "unsure"].includes(value.contactedCaregiver) ? value.contactedCaregiver : null,
      feltUnsafe: typeof value.feltUnsafe === "boolean" ? value.feltUnsafe : null,
      choice: normalizeChoice(value.choice),
      notes: String(value.notes || "").slice(0, 500),
    };
    return {
      ...base,
      response: ["answered", "not-asked", "declined"].includes(value.response) ? value.response : "not-asked",
      comfort: ["comfortable", "mixed", "uncomfortable", "unsure"].includes(value.comfort) ? value.comfort : null,
      preference: String(value.preference || "").slice(0, 500),
    };
  }

  function normalizeFacts(value) {
    if (!value || typeof value !== "object") return null;
    const completedSteps = Array.isArray(value.completedSteps) ? value.completedSteps.map(Boolean).slice(0, 12) : [];
    const pendingGaps = Array.isArray(value.pendingGaps) ? value.pendingGaps.map((gap) => ({
      id: String(gap?.id || ""),
      risk: gap?.risk === "medical" ? "medical" : "ordinary",
      status: gap?.status === "resolved" ? "resolved" : "pending",
    })) : [];
    return {
      sourceType: "application-record",
      recordedAt: value.recordedAt || value.endedAt || null,
      endedAt: value.endedAt || null,
      actualElapsedSeconds: Number.isFinite(Number(value.actualElapsedSeconds)) ? Math.max(0, Math.round(Number(value.actualElapsedSeconds))) : null,
      completedSteps,
      routineUpdatesQueued: Number.isFinite(Number(value.routineUpdatesQueued)) ? Math.max(0, Math.round(Number(value.routineUpdatesQueued))) : null,
      pendingGaps,
      urgentAlertsRaised: Number.isFinite(Number(value.urgentAlertsRaised)) ? Math.max(0, Math.round(Number(value.urgentAlertsRaised))) : null,
      contactActionsOpened: Array.isArray(value.contactActionsOpened) ? value.contactActionsOpened.map((item) => ({
        at: item?.at || null,
        target: ["caregiver", "emergency-contact", "emergency-service"].includes(item?.target) ? item.target : "caregiver",
        label: "已打开联系操作（不代表通话接通）",
      })) : [],
    };
  }

  function createSession(input) {
    if (!input || !STAGES.includes(input.stage)) throw new Error("valid session stage required");
    const startedAt = input.startedAt || new Date().toISOString();
    const guideScope = Array.isArray(input.guideScope) ? input.guideScope.map((guide) => ({
      id: String(guide.id),
      version: Math.max(1, Number(guide.version) || 1),
      title: String(guide.title || ""),
      source: String(guide.source || ""),
      actorId: String(guide.actorId || ""),
      level: String(guide.level || ""),
      rule: String(guide.rule || ""),
    })) : [];
    const record = {
      schemaVersion: VERSION,
      id: String(input.id || stableId()),
      demo: input.demo === true,
      status: input.status || "active",
      startSnapshot: {
        schemaVersion: VERSION,
        stage: input.stage,
        plannedDurationMinutes: Math.max(1, Number(input.plannedDurationMinutes) || 1),
        consentRevision: Math.max(1, Number(input.consentRevision) || 1),
        guideScope,
        redLines: Array.isArray(input.redLines) ? input.redLines.map(String) : [],
        participants: clone(input.participants || {}),
        mode: input.mode === "two-device" ? "two-device" : "single-device",
        startedAt,
        safetyRevision: input.safetyRevision || null,
        policyVersion: input.policyVersion || null,
      },
      facts: normalizeFacts(input.facts),
      checkIns: {
        caregiver: normalizeCheckIn(input.checkIns?.caregiver, "caregiver"),
        substitute: normalizeCheckIn(input.checkIns?.substitute, "substitute"),
        careRecipient: normalizeCheckIn(input.checkIns?.careRecipient, "careRecipient"),
      },
      recommendationAppliedAt: input.recommendationAppliedAt || null,
      legacyNote: input.legacyNote || "",
      redacted: input.redacted === true,
    };
    return record;
  }

  function normalizeSession(value) {
    if (!value || typeof value !== "object" || !value.id) return null;
    if (value.status === "legacy") {
      return {
        schemaVersion: VERSION,
        id: String(value.id),
        demo: value.demo === true,
        status: "legacy",
        startSnapshot: value.startSnapshot ? clone(value.startSnapshot) : null,
        facts: null,
        checkIns: { caregiver: null, substitute: null, careRecipient: null },
        recommendationAppliedAt: null,
        legacyNote: "较早完成，详细结果未记录",
        redacted: value.redacted === true,
      };
    }
    try {
      return createSession({
        ...value,
        ...(value.startSnapshot || {}),
        id: value.id,
        status: value.status,
        stage: value.startSnapshot?.stage,
        plannedDurationMinutes: value.startSnapshot?.plannedDurationMinutes,
        consentRevision: value.startSnapshot?.consentRevision,
        guideScope: value.startSnapshot?.guideScope,
        redLines: value.startSnapshot?.redLines,
        participants: value.startSnapshot?.participants,
        mode: value.startSnapshot?.mode,
        startedAt: value.startSnapshot?.startedAt,
        safetyRevision: value.startSnapshot?.safetyRevision,
        policyVersion: value.startSnapshot?.policyVersion,
        facts: value.facts,
        checkIns: value.checkIns,
      });
    } catch {
      return null;
    }
  }

  function endSession(record, input) {
    const normalized = normalizeSession(record);
    if (!normalized || normalized.status !== "active") return normalized;
    const status = TERMINAL_STATUSES.includes(input?.status) ? input.status : "interrupted";
    return {
      ...normalized,
      status,
      facts: normalizeFacts({
        recordedAt: input?.endedAt || new Date().toISOString(),
        endedAt: input?.endedAt || new Date().toISOString(),
        actualElapsedSeconds: input?.actualElapsedSeconds,
        completedSteps: input?.completedSteps || [],
        routineUpdatesQueued: input?.routineUpdatesQueued ?? 0,
        pendingGaps: input?.pendingGaps || [],
        urgentAlertsRaised: input?.urgentAlertsRaised ?? 0,
        contactActionsOpened: input?.contactActionsOpened || [],
      }),
    };
  }

  function withCheckIn(record, role, response) {
    const normalized = normalizeSession(record);
    if (!normalized || !["caregiver", "substitute", "careRecipient"].includes(role)) return normalized;
    const checkIn = normalizeCheckIn({ ...response, submittedAt: response?.submittedAt || new Date().toISOString() }, role);
    return { ...normalized, checkIns: { ...normalized.checkIns, [role]: checkIn } };
  }

  function currentAuthorization(record, context) {
    const guides = Array.isArray(context?.guides) ? context.guides : [];
    const guideVersionsCurrent = !guides.length || (record?.startSnapshot?.guideScope || []).every((snapshot) => guides.some((guide) => String(guide.id) === String(snapshot.id) && Number(guide.version) === Number(snapshot.version)));
    return Boolean(record?.startSnapshot && !record.redacted && Number(record.startSnapshot.consentRevision) === Number(context?.consentRevision) && guideVersionsCurrent && (!context?.safetyRevision || !record.startSnapshot.safetyRevision || record.startSnapshot.safetyRevision === context.safetyRevision));
  }

  function hasRequiredFacts(record) {
    const facts = record?.facts;
    return Boolean(facts?.endedAt && Number.isFinite(facts.actualElapsedSeconds) && Array.isArray(facts.completedSteps) && Number.isFinite(facts.routineUpdatesQueued) && Array.isArray(facts.pendingGaps) && Number.isFinite(facts.urgentAlertsRaised) && Array.isArray(facts.contactActionsOpened));
  }

  function completeCaregiver(checkIn) {
    return Boolean(checkIn && checkIn.restHappened && checkIn.phoneChecks && checkIn.nonurgentInterrupted && Number.isInteger(checkIn.confidence) && typeof checkIn.feltUnsafe === "boolean" && checkIn.choice);
  }

  function completeSubstitute(checkIn) {
    return Boolean(checkIn && checkIn.ableToHandle && checkIn.uncertainStep.trim() && checkIn.contactedCaregiver && typeof checkIn.feltUnsafe === "boolean" && checkIn.choice);
  }

  function recommendation(records, context = {}) {
    const sessions = (Array.isArray(records) ? records : []).map(normalizeSession).filter(Boolean).sort((a, b) => String(a.startSnapshot?.startedAt || "").localeCompare(String(b.startSnapshot?.startedAt || "")));
    const latestMeasured = [...sessions].reverse().find((item) => item.status !== "legacy");
    if (!latestMeasured) return { stage: "observe", decision: "measure", reasons: [sessions.length ? "较早完成没有详细结果，请进行一次新的可测量彩排" : "还没有实际彩排记录"], sourceSessionId: null, canExtend: false };
    const stage = latestMeasured.startSnapshot?.stage || "observe";
    const stale = !currentAuthorization(latestMeasured, context);
    let result;
    if (stale) {
      result = { stage: "observe", decision: "hold", reasons: ["同意或指导范围已变化，旧建议已失效", "历史事实仍保留，但需要在当前授权下重新彩排"], sourceSessionId: latestMeasured.id, canExtend: false };
    } else {
      const caregiver = latestMeasured.checkIns.caregiver;
      const substitute = latestMeasured.checkIns.substitute;
      const medicalHold = latestMeasured.facts?.pendingGaps?.some((gap) => gap.status !== "resolved" && gap.risk === "medical") || Number(latestMeasured.facts?.urgentAlertsRaised || 0) > 0;
      const stepBack = caregiver?.choice === "step-back" || substitute?.choice === "step-back";
      const bothExtend = caregiver?.choice === "extend" && substitute?.choice === "extend";
      const unsafe = caregiver?.feltUnsafe === true || substitute?.feltUnsafe === true;
      if (stepBack) result = { stage: previousStage(stage), decision: "step-back", reasons: ["至少一位参与者明确选择退回一级", "历史不会删除"], sourceSessionId: latestMeasured.id, canExtend: false };
      else if (latestMeasured.status !== "completed") result = { stage, decision: "hold", reasons: [`本次记录为“${STATUS_LABELS[latestMeasured.status] || latestMeasured.status}”，没有按完成计算`], sourceSessionId: latestMeasured.id, canExtend: false };
      else if (medicalHold) result = { stage, decision: "medical-hold", reasons: ["本次仍有未解决的医疗/高风险事件", "保持本级并使用直接联系或专业参考处理"], sourceSessionId: latestMeasured.id, canExtend: false };
      else if (!hasRequiredFacts(latestMeasured)) result = { stage, decision: "hold", reasons: ["应用记录的结束事实不完整，不能建议延长"], sourceSessionId: latestMeasured.id, canExtend: false };
      else if (!completeCaregiver(caregiver) || !completeSubstitute(substitute)) result = { stage, decision: "hold", reasons: ["照护者或替班者的关键回答尚未填写完整", "缺失回答不会被推断为准备好"], sourceSessionId: latestMeasured.id, canExtend: false };
      else if (unsafe) result = { stage, decision: "hold", reasons: ["有人报告这次感到不安全，保持本级"], sourceSessionId: latestMeasured.id, canExtend: false };
      else if (!bothExtend) result = { stage, decision: "repeat", reasons: ["双方没有都明确选择延长，建议重复本级"], sourceSessionId: latestMeasured.id, canExtend: false };
      else result = { stage: nextStage(stage), decision: nextStage(stage) === stage ? "repeat" : "extend", reasons: ["本次在当前授权下完成", "照护者与替班者都明确选择延长", "未记录未解决的紧急/医疗事件或不安全感受"], sourceSessionId: latestMeasured.id, canExtend: nextStage(stage) !== stage };
    }
    if (context.overrideStage && STAGES.includes(context.overrideStage) && stageIndex(context.overrideStage) < stageIndex(result.stage)) {
      return { ...result, stage: context.overrideStage, decision: "user-override", reasons: ["照护者选择了更保守的下一档", ...result.reasons], canExtend: false };
    }
    return result;
  }

  function metrics(records) {
    const sessions = (Array.isArray(records) ? records : []).map(normalizeSession).filter((item) => item && item.status !== "legacy" && item.facts);
    const completed = sessions.filter((item) => item.status === "completed");
    return {
      protectedMinutes: Math.floor(completed.filter((item) => item.startSnapshot.stage !== "observe").reduce((sum, item) => sum + Number(item.facts.actualElapsedSeconds || 0), 0) / 60),
      independentHandoffs: completed.filter((item) => item.startSnapshot.stage !== "observe" && item.facts.completedSteps.length > 0 && item.facts.completedSteps.every(Boolean)).length,
      routineUpdatesDeferred: sessions.reduce((sum, item) => sum + Number(item.facts.routineUpdatesQueued || 0), 0),
      urgentEvents: sessions.reduce((sum, item) => sum + Number(item.facts.urgentAlertsRaised || 0), 0),
      actualRecords: sessions.length,
      lastCaregiverConfidence: [...sessions].reverse().find((item) => item.checkIns.caregiver?.confidence)?.checkIns.caregiver.confidence || null,
      lastChoice: [...sessions].reverse().find((item) => item.checkIns.caregiver?.choice)?.checkIns.caregiver.choice || null,
    };
  }

  function redactSession(record, revokedGuideIds = []) {
    const normalized = normalizeSession(record);
    if (!normalized) return null;
    const revoked = new Set(revokedGuideIds.map(String));
    const staleGuides = (normalized.startSnapshot?.guideScope || []).filter((guide) => revoked.has(String(guide.id)));
    if (!normalized.redacted && !staleGuides.length) return normalized;
    const facts = normalized.facts ? {
      sourceType: "application-record",
      recordedAt: normalized.facts.recordedAt,
      endedAt: normalized.facts.endedAt,
      actualElapsedSeconds: normalized.facts.actualElapsedSeconds,
      completedSteps: normalized.facts.completedSteps,
      routineUpdatesQueued: normalized.facts.routineUpdatesQueued,
      pendingGaps: normalized.facts.pendingGaps.map((gap) => ({ risk: gap.risk, status: gap.status })),
      urgentAlertsRaised: normalized.facts.urgentAlertsRaised,
      contactActionsOpened: normalized.facts.contactActionsOpened.map((item) => ({ at: item.at, target: item.target, label: item.label })),
    } : null;
    return {
      ...normalized,
      redacted: true,
      startSnapshot: normalized.startSnapshot ? {
        schemaVersion: VERSION,
        stage: normalized.startSnapshot.stage,
        plannedDurationMinutes: normalized.startSnapshot.plannedDurationMinutes || null,
        consentRevision: normalized.startSnapshot.consentRevision || null,
        guideScope: (normalized.startSnapshot.guideScope || []).filter((guide) => !revoked.has(String(guide.id))).map((guide) => ({ id: guide.id, version: guide.version, source: "已撤销内容" })),
        redLines: [],
        participants: {},
        mode: normalized.startSnapshot.mode || null,
        startedAt: normalized.startSnapshot.startedAt || null,
        safetyRevision: null,
        policyVersion: normalized.startSnapshot.policyVersion,
      } : null,
      facts,
      checkIns: { caregiver: null, substitute: null, careRecipient: null },
    };
  }

  return Object.freeze({ VERSION, STAGES, CHOICES, TERMINAL_STATUSES, STAGE_LABELS, STATUS_LABELS, stableId, stageIndex, previousStage, nextStage, createSession, normalizeSession, normalizeFacts, normalizeCheckIn, endSession, withCheckIn, hasRequiredFacts, recommendation, metrics, redactSession });
});
