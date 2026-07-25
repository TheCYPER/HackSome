"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const SafetyPolicy = require("./safety-policy.js");

const ROOT = __dirname;
const PORT = Number(process.env.PORT || 4173);
const HOST = process.env.HOST || "0.0.0.0";
const MAX_BODY_BYTES = 64 * 1024;
const ROOM_RETENTION_MS = 5 * 60 * 1000;
const rooms = new Map();

const MIME = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".webmanifest": "application/manifest+json; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
};

const PHRASE_LEFT = ["青松", "月光", "海风", "麦穗", "山茶", "云朵", "竹影", "星河"];
const PHRASE_RIGHT = ["小桥", "白帆", "暖灯", "清泉", "归鸟", "晨露", "纸鹤", "晚霞"];
const ACTION_CONTEXT = ["type", "expectedRevision", "actionId", "sessionId", "participantId", "consentRevision", "guideVersion", "safetyRevision"];
const OUTCOME_VERSION = 1;

function configuredPublicOrigin() {
  const value = String(process.env.PUBLIC_ORIGIN || "").trim();
  if (!value) return null;
  let parsed;
  try { parsed = new URL(value); } catch { throw new Error("PUBLIC_ORIGIN must be an absolute http(s) origin"); }
  if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password || parsed.pathname !== "/" || parsed.search || parsed.hash) {
    throw new Error("PUBLIC_ORIGIN must contain only an http(s) scheme and host");
  }
  return parsed.origin;
}

const PUBLIC_ORIGIN = configuredPublicOrigin();

function isPrivateInviteHostname(hostname) {
  const host = String(hostname || "").replace(/^\[|\]$/g, "").toLowerCase();
  if (host === "localhost" || host === "::1" || host.endsWith(".local")) return true;
  if (/^127\./.test(host) || /^10\./.test(host) || /^192\.168\./.test(host) || /^172\.(1[6-9]|2\d|3[01])\./.test(host)) return true;
  return /^(fc|fd|fe[89ab])/i.test(host);
}

function invitationOrigin(request) {
  if (PUBLIC_ORIGIN) return PUBLIC_ORIGIN;
  const rawHost = String(request.headers.host || "").trim();
  let parsed;
  try { parsed = new URL(`http://${rawHost}`); } catch { throw apiError(400, "untrusted_host", "request host cannot be used for an invitation"); }
  if (!rawHost || parsed.username || parsed.password || !isPrivateInviteHostname(parsed.hostname)) {
    throw apiError(400, "untrusted_host", "set PUBLIC_ORIGIN for non-local invitation URLs");
  }
  return parsed.origin;
}

function normalizedQuery(value) {
  return SafetyPolicy.canonicalizeText(value);
}

function matchScopedGuide(room, query) {
  const text = String(query || "").trim();
  const key = normalizedQuery(text);
  const risky = SafetyPolicy.classifyText(text).highRisk;
  const aliases = {
    meal: ["不饿", "午饭", "吃饭", "拒绝吃", "饭菜"],
    walk: ["散步", "出门", "走廊"],
    tea: ["喝水", "加餐", "杯"],
    mood: ["一个人", "独处", "门口"],
    fall: ["跌倒", "摔倒", "滑倒", "跌落"],
  };
  return room.searchGuides.find((guide) => {
    const safeForRisk = !risky || SafetyPolicy.isImmediateReference(guide);
    if (!safeForRisk) return false;
    if ((aliases[guide.id] || []).some((term) => text.includes(term))) return true;
    const guideKey = normalizedQuery(guide.title).replace(/[她他时的了·]/g, "");
    const queryKey = key.replace(/[她他时的了·]/g, "");
    return guideKey.length >= (risky ? 2 : 4) && (queryKey.includes(guideKey) || (risky && guideKey.includes(queryKey)));
  }) || null;
}

function randomToken(bytes = 24) {
  return crypto.randomBytes(bytes).toString("base64url");
}

function tokenHash(token) {
  return crypto.createHash("sha256").update(String(token || "")).digest();
}

function tokenMatches(expected, supplied) {
  if (!expected || typeof supplied !== "string" || !supplied) return false;
  const actual = tokenHash(supplied);
  return actual.length === expected.length && crypto.timingSafeEqual(actual, expected);
}

function phrase() {
  const left = PHRASE_LEFT[crypto.randomInt(PHRASE_LEFT.length)];
  const right = PHRASE_RIGHT[crypto.randomInt(PHRASE_RIGHT.length)];
  return `${left} · ${right}`;
}

function cleanText(value, maximum, label, { required = true } = {}) {
  if (typeof value !== "string") {
    if (!required && value == null) return "";
    throw apiError(400, "invalid_field", `${label} must be text`);
  }
  const result = value.trim();
  if ((required && !result) || result.length > maximum) {
    throw apiError(400, "invalid_field", `${label} is invalid`);
  }
  return result;
}

function positiveInteger(value, label, minimum, maximum) {
  const result = Number(value);
  if (!Number.isInteger(result) || result < minimum || result > maximum) {
    throw apiError(400, "invalid_field", `${label} is invalid`);
  }
  return result;
}

function exactKeys(value, allowed, required = []) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw apiError(400, "invalid_body", "JSON object required");
  }
  const keys = Object.keys(value);
  const extra = keys.filter((key) => !allowed.includes(key));
  const missing = required.filter((key) => !keys.includes(key));
  if (extra.length || missing.length) {
    throw apiError(
      400,
      "invalid_body",
      extra.length ? `unknown fields: ${extra.join(", ")}` : `missing fields: ${missing.join(", ")}`,
    );
  }
}

function apiError(status, code, message) {
  const error = new Error(message);
  error.status = status;
  error.code = code;
  return error;
}

function requirePolicyVersion(request) {
  const provided = request.headers[SafetyPolicy.HEADER];
  if (provided !== SafetyPolicy.VERSION) {
    const error = apiError(409, "policy_update_required", "Safety policy changed; refresh or update before using live-room features");
    error.details = { expectedPolicyVersion: SafetyPolicy.VERSION, providedPolicyVersion: String(provided || "") };
    throw error;
  }
}

function actorType(actorId) {
  return {
    caregiver: "caregiver",
    recipient: "careRecipient",
    relay: "relay",
    [SafetyPolicy.PROFESSIONAL_SOURCE_ID]: "professional",
  }[actorId] || "unverified";
}

const LEVEL_RULES = Object.freeze({ here: "现场可处理", later: "稍后告知", now: SafetyPolicy.IMMEDIATE_RULE });

function canonicalGuide(raw, indexLabel, family) {
  exactKeys(raw, ["id", "version", "title", "summary", "source", "rule", "level", "actorId", "highRisk", "professionalReferenceId"], ["id", "version", "title", "summary", "source", "rule", "level", "actorId", "highRisk"]);
  const id = cleanText(raw.id, 80, `${indexLabel}.id`);
  const version = positiveInteger(raw.version, `${indexLabel}.version`, 1, 1000000);
  const actorId = cleanText(raw.actorId, 80, `${indexLabel}.actorId`);
  if (!SafetyPolicy.isRecognizedActorId(actorId)) throw apiError(400, "invalid_source", `${indexLabel}.actorId is not a recognized source identity`);
  const requestedLevel = cleanText(raw.level, 20, `${indexLabel}.level`);
  const requestedRule = cleanText(raw.rule, 80, `${indexLabel}.rule`);
  if (!LEVEL_RULES[requestedLevel] || requestedRule !== LEVEL_RULES[requestedLevel]) {
    throw apiError(422, "invalid_escalation_semantics", `${indexLabel} escalation level and rule must use the exact supported semantics`);
  }
  // Read untrusted display/flag fields only for schema and size validation. The
  // canonical projection below never copies them.
  cleanText(raw.source, 80, `${indexLabel}.source`);
  const title = cleanText(raw.title, 80, `${indexLabel}.title`);
  const summary = cleanText(raw.summary, 500, `${indexLabel}.summary`);
  const professionalReferenceId = raw.professionalReferenceId == null
    ? ""
    : cleanText(raw.professionalReferenceId, 100, `${indexLabel}.professionalReferenceId`);

  // A caller cannot mint professional provenance by selecting an actor ID,
  // source label, risk flag, or escalation wording. The only accepted
  // professional material is an immutable record shipped with this policy
  // version, and every identity/content field must match that record exactly.
  if (actorId === SafetyPolicy.PROFESSIONAL_SOURCE_ID || professionalReferenceId) {
    const reference = SafetyPolicy.getProfessionalReference(professionalReferenceId);
    if (!reference) {
      throw apiError(422, "unverified_professional_source", `${indexLabel} does not identify a server-owned professional reference`);
    }
    if (!SafetyPolicy.matchesProfessionalReference({
      professionalReferenceId,
      id,
      version,
      title,
      summary,
      actorId,
      level: requestedLevel,
      rule: requestedRule,
    })) {
      throw apiError(422, "professional_reference_mismatch", `${indexLabel} differs from the immutable server-owned professional reference`);
    }
    const classification = SafetyPolicy.classifyFields([reference.title, reference.summary]);
    if (!classification.highRisk || !SafetyPolicy.isImmediateReference(reference)) {
      throw apiError(500, "invalid_policy_reference", "configured professional reference does not satisfy the active safety policy");
    }
    return {
      ...reference,
      source: SafetyPolicy.canonicalSourceLabel(reference.actorId, family),
      actorType: actorType(reference.actorId),
      highRisk: true,
      category: "urgent",
      policyVersion: SafetyPolicy.VERSION,
    };
  }

  const classification = SafetyPolicy.classifyFields([title, summary]);
  return {
    id,
    version,
    title,
    summary,
    source: SafetyPolicy.canonicalSourceLabel(actorId, family),
    rule: LEVEL_RULES[requestedLevel],
    level: requestedLevel,
    actorId,
    actorType: actorType(actorId),
    highRisk: classification.highRisk,
    category: requestedLevel === "now" ? "urgent" : "daily",
    policyVersion: SafetyPolicy.VERSION,
    professionalReferenceId: null,
  };
}

function safetyScopeRevision({ family, redLines, searchGuides }) {
  const material = JSON.stringify({
    policyVersion: SafetyPolicy.VERSION,
    redLines,
    caregiverPhone: family.caregiverPhone,
    emergencyService: family.emergencyService,
    guides: searchGuides.map((guide) => ({
      id: guide.id,
      version: guide.version,
      title: guide.title,
      summary: guide.summary,
      actorId: guide.actorId,
      professionalReferenceId: guide.professionalReferenceId,
      level: guide.level,
      rule: guide.rule,
      highRisk: guide.highRisk,
    })).sort((left, right) => String(left.id).localeCompare(String(right.id))),
  });
  let hash = 2166136261;
  for (let index = 0; index < material.length; index += 1) {
    hash ^= material.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `scope-${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

function sendJSON(response, status, value) {
  const body = JSON.stringify(value);
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  response.end(body);
}

async function readJSON(request) {
  const chunks = [];
  let total = 0;
  for await (const chunk of request) {
    total += chunk.length;
    if (total > MAX_BODY_BYTES) throw apiError(413, "body_too_large", "request body too large");
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw apiError(400, "invalid_json", "valid JSON required");
  }
}

function bearer(request) {
  const value = request.headers.authorization || "";
  const match = /^Bearer ([A-Za-z0-9_-]+)$/.exec(value);
  return match ? match[1] : "";
}

function expireIfNeeded(room) {
  const now = Date.now();
  const deadline = room.status === "waiting" ? room.inviteExpiresAt : room.sessionExpiresAt;
  if (!["ended", "revoked", "expired", "invalidated"].includes(room.status) && now > deadline) {
    if (room.startedAt && !room.endedAt) {
      room.endedAt = new Date(now).toISOString();
      const status = room.relayLastSeenAt && now - room.relayLastSeenAt >= 6000 ? "disconnected" : "expired";
      room.summary = room.summary || {
        outcomeVersion: OUTCOME_VERSION,
        sessionId: room.sessionId,
        status,
        startSnapshot: room.startSnapshot || buildStartSnapshot(room),
        facts: observableFacts(room, status, room.endedAt),
        tasks: [...room.tasks],
        completedTasks: room.tasks.filter(Boolean).length,
        notes: room.timeline.filter((event) => event.type === "relay.note").length,
        alerts: room.timeline.filter((event) => event.type === "relay.alert").length,
        caregiverNote: "",
        durationSeconds: Math.max(0, Math.floor((now - new Date(room.startedAt).getTime()) / 1000)),
        debrief: null,
      };
    }
    room.status = "expired";
    room.terminalAt = now;
    room.inviteTokenHash = null;
    room.relayTokenHash = null;
    room.revision += 1;
    room.timeline.push({
      id: `event-${room.revision}`,
      revision: room.revision,
      type: "room.expired",
      actor: "server",
      text: "连接已到期",
      at: new Date().toISOString(),
    });
  }
}

function purgeRooms(now = Date.now()) {
  for (const [roomId, room] of rooms) {
    expireIfNeeded(room);
    if (room.terminalAt && now - room.terminalAt > ROOM_RETENTION_MS) rooms.delete(roomId);
  }
}

const purgeHandle = setInterval(purgeRooms, 30 * 1000);
purgeHandle.unref();

function roomRole(room, token) {
  if (tokenMatches(room.caregiverTokenHash, token)) return "caregiver";
  if (tokenMatches(room.relayTokenHash, token)) return "relay";
  return null;
}

function requireRoom(roomId) {
  const room = rooms.get(roomId);
  if (!room) throw apiError(404, "room_not_found", "room not found");
  expireIfNeeded(room);
  return room;
}

function requireRole(request, room, allowed) {
  const role = roomRole(room, bearer(request));
  if (!role) throw apiError(401, "invalid_capability", "capability is invalid, expired, or revoked");
  if (!allowed.includes(role)) throw apiError(403, "role_forbidden", "this capability cannot perform that action");
  if (role === "relay") room.relayLastSeenAt = Date.now();
  return role;
}

function participantIdFor(room, role) {
  return role === "caregiver" ? room.caregiverParticipantId : room.relayParticipantId;
}

function buildStartSnapshot(room) {
  return {
    schemaVersion: OUTCOME_VERSION,
    stage: room.stage,
    plannedDurationMinutes: room.duration,
    consentRevision: room.consentRevision,
    guideScope: room.searchGuides.map((guide) => ({ id: guide.id, version: guide.version, title: guide.title, source: guide.source, actorId: guide.actorId, level: guide.level, rule: guide.rule })),
    redLines: [...room.redLines],
    participants: {
      caregiver: { id: room.caregiverParticipantId, label: room.family.caregiverName },
      substitute: { id: room.relayParticipantId, label: room.family.relayName },
      careRecipient: { id: "care-recipient", label: room.family.recipientName },
    },
    mode: "two-device",
    startedAt: room.startedAt,
    safetyRevision: room.safetyRevision,
    policyVersion: room.policyVersion,
  };
}

function observableFacts(room, status, endedAt = new Date().toISOString()) {
  return {
    sourceType: "application-record",
    recordedAt: endedAt,
    endedAt,
    actualElapsedSeconds: room.startedAt ? Math.max(0, Math.floor((new Date(endedAt).getTime() - new Date(room.startedAt).getTime()) / 1000)) : null,
    completedSteps: [...room.tasks],
    routineUpdatesQueued: room.timeline.filter((event) => event.type === "relay.note").length,
    pendingGaps: room.pendingGaps.map((gap) => ({ id: gap.id, risk: gap.risk, status: gap.status })),
    urgentAlertsRaised: room.timeline.filter((event) => event.type === "relay.alert" || (event.type === "relay.search.pending" && event.urgent)).length,
    contactActionsOpened: room.timeline.filter((event) => event.type.endsWith(".contact-opened")).map((event) => ({ at: event.at, target: event.target, label: "已打开联系操作（不代表通话接通）" })),
    completionStatus: status,
  };
}

function roleCheckIn(response, role, participantId) {
  if (role === "caregiver") {
    exactKeys(response, ["restHappened", "phoneChecks", "nonurgentInterrupted", "confidence", "feltUnsafe", "choice", "notes", "partial"]);
    const allowed = (value, values) => value == null || value === "" ? null : values.includes(value) ? value : (() => { throw apiError(400, "invalid_checkin", "caregiver check-in choice is invalid"); })();
    const confidence = response.confidence == null || response.confidence === "" ? null : positiveInteger(response.confidence, "response.confidence", 1, 5);
    if (response.feltUnsafe != null && typeof response.feltUnsafe !== "boolean") throw apiError(400, "invalid_checkin", "feltUnsafe must be true, false, or null");
    return { schemaVersion: OUTCOME_VERSION, role, sourceType: "self-report", respondentId: participantId, submittedAt: new Date().toISOString(), partial: response.partial !== false, restHappened: allowed(response.restHappened, ["yes", "partly", "no", "not-planned", "unsure"]), phoneChecks: allowed(response.phoneChecks, ["0", "1-2", "3-5", "6+", "unsure"]), nonurgentInterrupted: allowed(response.nonurgentInterrupted, ["yes", "no", "unsure"]), confidence, feltUnsafe: response.feltUnsafe ?? null, choice: allowed(response.choice, ["extend", "repeat", "step-back"]), notes: cleanText(response.notes || "", 500, "response.notes", { required: false }) };
  }
  exactKeys(response, ["ableToHandle", "uncertainStep", "contactedCaregiver", "feltUnsafe", "choice", "notes", "partial"]);
  const allowed = (value, values) => value == null || value === "" ? null : values.includes(value) ? value : (() => { throw apiError(400, "invalid_checkin", "substitute check-in choice is invalid"); })();
  if (response.feltUnsafe != null && typeof response.feltUnsafe !== "boolean") throw apiError(400, "invalid_checkin", "feltUnsafe must be true, false, or null");
  return { schemaVersion: OUTCOME_VERSION, role: "substitute", sourceType: "self-report", respondentId: participantId, submittedAt: new Date().toISOString(), partial: response.partial !== false, ableToHandle: allowed(response.ableToHandle, ["yes", "partly", "no", "unsure"]), uncertainStep: cleanText(response.uncertainStep || "", 500, "response.uncertainStep", { required: false }), contactedCaregiver: allowed(response.contactedCaregiver, ["yes", "no", "unsure"]), feltUnsafe: response.feltUnsafe ?? null, choice: allowed(response.choice, ["extend", "repeat", "step-back"]), notes: cleanText(response.notes || "", 500, "response.notes", { required: false }) };
}

function projectedTimeline(room, role) {
  let quietOrdinal = 0;
  return room.timeline.slice(-30).map((item) => {
    if (room.stage === "quiet-handoff" && room.status === "active" && role === "caregiver" && item.type === "relay.note") {
      quietOrdinal += 1;
      return {
        id: item.id,
        revision: item.revision,
        type: item.type,
        actor: item.actor,
        text: `普通记录 ${quietOrdinal} 已进入安静队列`,
        queued: true,
        at: item.at,
      };
    }
    if (item.type === "relay.search.pending" && room.stage === "quiet-handoff" && room.status === "active" && role === "caregiver" && !item.urgent) {
      return { ...item, text: "一个未知日常问题已进入待确认队列", queued: true };
    }
    return { ...item };
  });
}

function roomProjection(room, role) {
  expireIfNeeded(room);
  const online = Boolean(room.relayLastSeenAt && Date.now() - room.relayLastSeenAt < 6000);
  const protectedQuietWindow = room.stage === "quiet-handoff" && room.status === "active";
  return {
    id: room.id,
    sessionId: room.sessionId,
    participantId: participantIdFor(room, role),
    role,
    status: room.status,
    revision: room.revision,
    createdAt: room.createdAt,
    inviteExpiresAt: room.inviteExpiresAt,
    sessionExpiresAt: room.sessionExpiresAt,
    pairedAt: room.pairedAt,
    startedAt: room.startedAt,
    endedAt: room.endedAt,
    relayOnline: online,
    stage: room.stage,
    duration: room.duration,
    consentRevision: room.consentRevision,
    guideVersion: room.guide.version,
    safetyRevision: room.safetyRevision,
    policyVersion: room.policyVersion,
    family: {
      caregiverName: room.family.caregiverName,
      relayName: room.family.relayName,
      recipientName: room.family.recipientName,
      caregiverPhone: room.family.caregiverPhone,
      emergencyService: room.family.emergencyService,
    },
    guide: { ...room.guide },
    // This is the exact server-searchable scope. Both roles review the same
    // version/source snapshot before acknowledging it; later search can never
    // return a guide that was absent from this list.
    searchGuides: room.searchGuides.map((guide) => ({ ...guide })),
    redLines: [...room.redLines],
    tasks: [...room.tasks],
    timeline: projectedTimeline(room, role),
    quietCount: room.timeline.filter((item) => item.type === "relay.note").length,
    pendingGapCount: room.pendingGaps.length,
    // During an off-duty window the caregiver receives only the count. Routine
    // queue text is released after the live window, while urgent events remain
    // visible immediately through the separately projected timeline.
    pendingGaps: role === "caregiver" && !protectedQuietWindow ? room.pendingGaps.map((gap) => ({ ...gap })) : [],
    lastSearch: role === "relay" && room.lastSearch ? { ...room.lastSearch, guide: room.lastSearch.guide ? { ...room.lastSearch.guide } : null } : null,
    confirmations: {
      caregiver: Boolean(room.acknowledgements.caregiver),
      relay: Boolean(room.acknowledgements.relay),
    },
    summary: room.summary ? {
      ...room.summary,
      tasks: [...room.summary.tasks],
      debrief: room.summary.debrief ? { ...room.summary.debrief } : null,
    } : null,
    startSnapshot: room.startSnapshot ? { ...room.startSnapshot, guideScope: room.startSnapshot.guideScope.map((guide) => ({ ...guide })), redLines: [...room.startSnapshot.redLines], participants: { ...room.startSnapshot.participants } } : null,
    checkIns: {
      caregiver: room.checkIns.caregiver ? { ...room.checkIns.caregiver } : null,
      substitute: room.checkIns.substitute ? { ...room.checkIns.substitute } : null,
    },
    ...(role === "caregiver" ? {
      pairing: {
        status: room.status === "waiting" ? "waiting" : room.pairedAt ? "paired" : room.status,
        relayOnline: online,
        failedPhraseAttempts: room.failedPhraseAttempts,
      },
    } : {}),
  };
}

function createRoom(body, request) {
  exactKeys(
    body,
    ["family", "stage", "duration", "consentRevision", "guide", "searchGuides", "redLines", "safetyRevision", "ttlSeconds"],
    ["family", "stage", "duration", "consentRevision", "guide", "searchGuides", "redLines", "safetyRevision"],
  );
  exactKeys(
    body.family,
    ["caregiverName", "relayName", "recipientName", "caregiverPhone", "emergencyService"],
    ["caregiverName", "relayName", "recipientName", "caregiverPhone", "emergencyService"],
  );
  if (!Array.isArray(body.redLines) || body.redLines.length > 8) {
    throw apiError(400, "invalid_field", "redLines is invalid");
  }
  if (!Array.isArray(body.searchGuides) || body.searchGuides.length > 30) {
    throw apiError(400, "invalid_field", "searchGuides is invalid");
  }
  if (!["observe", "short-leave", "quiet-handoff"].includes(body.stage)) {
    throw apiError(400, "invalid_field", "stage is invalid");
  }
  // Capability-bearing links never derive their origin from forwarding
  // headers. Local use is limited to loopback/private LAN hosts; a managed
  // deployment must set one explicit PUBLIC_ORIGIN.
  const publicOrigin = invitationOrigin(request);

  const family = {
    caregiverName: cleanText(body.family.caregiverName, 60, "family.caregiverName"),
    relayName: cleanText(body.family.relayName, 60, "family.relayName"),
    recipientName: cleanText(body.family.recipientName, 60, "family.recipientName"),
    caregiverPhone: cleanText(body.family.caregiverPhone, 40, "family.caregiverPhone"),
    emergencyService: cleanText(body.family.emergencyService, 40, "family.emergencyService"),
  };
  const guide = canonicalGuide(body.guide, "guide", family);
  if (guide.highRisk || guide.level === SafetyPolicy.IMMEDIATE_LEVEL) {
    throw apiError(422, "unsafe_companion_scope", "high-risk content cannot be placed in a companion rehearsal");
  }

  const now = Date.now();
  const ttlSeconds = body.ttlSeconds == null ? 15 * 60 : positiveInteger(body.ttlSeconds, "ttlSeconds", 2, 15 * 60);
  const caregiverToken = randomToken();
  const inviteToken = randomToken();
  const caregiverParticipantId = `caregiver-${randomToken(9)}`;
  const sessionId = `session-${randomToken(12)}`;
  const searchGuides = body.searchGuides.map((raw, index) => {
    const item = canonicalGuide(raw, `searchGuides[${index}]`, family);
    if (item.highRisk && !SafetyPolicy.isImmediateReference(item)) {
      throw apiError(422, "unsafe_search_scope", "high-risk search guides require an immediate professional source");
    }
    return item;
  });
  const guideIds = new Set(searchGuides.map((item) => item.id));
  if (guideIds.size !== searchGuides.length) {
    throw apiError(400, "invalid_field", "searchGuides contains duplicate ids");
  }
  const searchablePrimary = searchGuides.find((item) => item.id === guide.id);
  const guideFields = ["version", "title", "summary", "source", "rule", "level", "actorId", "actorType", "highRisk", "category", "policyVersion", "professionalReferenceId"];
  if (!searchablePrimary || guideFields.some((field) => searchablePrimary[field] !== guide[field])) {
    throw apiError(422, "guide_scope_mismatch", "the primary guide must exactly match its reviewed searchable snapshot");
  }
  const room = {
    id: randomToken(12),
    sessionId,
    caregiverParticipantId,
    relayParticipantId: null,
    caregiverTokenHash: tokenHash(caregiverToken),
    relayTokenHash: null,
    inviteTokenHash: tokenHash(inviteToken),
    usedInviteTokenHashes: [],
    humanPhrase: phrase(),
    failedPhraseAttempts: 0,
    status: "waiting",
    terminalAt: null,
    revision: 1,
    createdAt: new Date(now).toISOString(),
    inviteExpiresAt: now + ttlSeconds * 1000,
    sessionExpiresAt: now + 2 * 60 * 60 * 1000,
    pairedAt: null,
    relayLastSeenAt: null,
    startedAt: null,
    endedAt: null,
    stage: body.stage,
    duration: positiveInteger(body.duration, "duration", 1, 180),
    consentRevision: positiveInteger(body.consentRevision, "consentRevision", 1, 1000000),
    safetyRevision: "",
    policyVersion: SafetyPolicy.VERSION,
    family,
    guide,
    searchGuides,
    redLines: body.redLines.map((item) => cleanText(item, 80, "redLine")).filter(Boolean),
    tasks: [false, false, false],
    acknowledgements: { caregiver: null, relay: null },
    pendingGaps: [],
    lastSearch: null,
    actionIds: new Set(),
    timeline: [{
      id: "event-1",
      revision: 1,
      type: "room.created",
      actor: "caregiver",
      text: "照护者创建了双机彩排邀请",
      at: new Date(now).toISOString(),
    }],
    summary: null,
    startSnapshot: null,
    checkIns: { caregiver: null, substitute: null },
  };
  // safetyRevision is derived from canonical server-owned scope. The caller's
  // field is accepted for wire compatibility but never becomes authoritative.
  cleanText(body.safetyRevision, 100, "safetyRevision");
  room.safetyRevision = safetyScopeRevision(room);
  rooms.set(room.id, room);
  return {
    room: roomProjection(room, "caregiver"),
    caregiverToken,
      invitation: {
      token: inviteToken,
      phrase: room.humanPhrase,
      expiresAt: room.inviteExpiresAt,
      joinUrl: `${publicOrigin}/join.html#room=${encodeURIComponent(room.id)}&invite=${encodeURIComponent(inviteToken)}`,
      },
  };
}

function checkMutation(room, body, role, type) {
  if (body.type !== type) throw apiError(400, "invalid_action", `expected ${type}`);
  const actionId = cleanText(body.actionId, 100, "actionId");
  if (room.actionIds.has(actionId)) throw apiError(409, "replayed_action", "actionId has already been used");
  if (cleanText(body.sessionId, 100, "sessionId") !== room.sessionId) {
    throw apiError(409, "stale_session", "sessionId does not match the current room session");
  }
  if (cleanText(body.participantId, 100, "participantId") !== participantIdFor(room, role)) {
    throw apiError(403, "participant_mismatch", "participantId does not belong to this capability");
  }
  if (positiveInteger(body.consentRevision, "consentRevision", 1, 1000000) !== room.consentRevision) {
    throw apiError(409, "stale_consent", "consent revision changed; room must be resynchronized");
  }
  if (positiveInteger(body.guideVersion, "guideVersion", 1, 1000000) !== room.guide.version) {
    throw apiError(409, "stale_guide", "guide version changed; room must be resynchronized");
  }
  if (cleanText(body.safetyRevision, 100, "safetyRevision") !== room.safetyRevision) {
    throw apiError(409, "stale_safety_scope", "red-line or contact scope changed; room must be resynchronized");
  }
  const expected = positiveInteger(body.expectedRevision, "expectedRevision", 1, 100000000);
  if (expected !== room.revision) {
    throw apiError(409, "stale_revision", `expected revision ${room.revision}`);
  }
  room.actionIds.add(actionId);
  if (role === "relay") room.relayLastSeenAt = Date.now();
}

function addEvent(room, type, actor, text, extra = {}) {
  room.revision += 1;
  const event = {
    id: `event-${room.revision}`,
    revision: room.revision,
    type,
    actor,
    text,
    at: new Date().toISOString(),
    ...extra,
  };
  room.timeline.push(event);
  return event;
}

function invitationFor(room, request) {
  const publicOrigin = invitationOrigin(request);
  const inviteToken = randomToken();
  room.inviteTokenHash = tokenHash(inviteToken);
  room.humanPhrase = phrase();
  room.inviteExpiresAt = Date.now() + 15 * 60 * 1000;
  room.sessionExpiresAt = Date.now() + 2 * 60 * 60 * 1000;
  room.relayTokenHash = null;
  room.relayLastSeenAt = null;
  room.pairedAt = null;
  room.startedAt = null;
  room.endedAt = null;
  room.sessionId = `session-${randomToken(12)}`;
  room.relayParticipantId = null;
  room.status = "waiting";
  room.terminalAt = null;
  room.failedPhraseAttempts = 0;
  room.tasks = [false, false, false];
  room.acknowledgements = { caregiver: null, relay: null };
  room.pendingGaps = [];
  room.lastSearch = null;
  room.summary = null;
  room.startSnapshot = null;
  room.checkIns = { caregiver: null, substitute: null };
  room.actionIds = new Set();
  return {
    token: inviteToken,
    phrase: room.humanPhrase,
    expiresAt: room.inviteExpiresAt,
    joinUrl: `${publicOrigin}/join.html#room=${encodeURIComponent(room.id)}&invite=${encodeURIComponent(inviteToken)}`,
  };
}

async function handleAPI(request, response, url) {
  if (url.pathname === "/api/health" && request.method === "GET") {
    sendJSON(response, 200, { ok: true, service: "relay-companion", rooms: rooms.size, policyVersion: SafetyPolicy.VERSION });
    return;
  }
  // One version handshake protects this router, including endpoints added in
  // the future. Live-room reads and writes never execute under an unknown or
  // stale browser policy.
  requirePolicyVersion(request);
  if (url.pathname === "/api/rooms") {
    if (request.method !== "POST") throw apiError(405, "method_not_allowed", "use POST to create a room");
    const result = createRoom(await readJSON(request), request);
    sendJSON(response, 201, result);
    return;
  }

  const match = /^\/api\/rooms\/([A-Za-z0-9_-]+)(?:\/(join|actions|reissue|revoke|snapshot))?$/.exec(url.pathname);
  if (!match) throw apiError(404, "api_not_found", "API route not found");
  const room = requireRoom(match[1]);
  const operation = match[2] || "";

  if (!operation && request.method === "GET") {
    const role = requireRole(request, room, ["caregiver", "relay"]);
    sendJSON(response, 200, { room: roomProjection(room, role) });
    return;
  }

  if (operation === "join" && request.method === "POST") {
    const body = await readJSON(request);
    exactKeys(body, ["inviteToken", "phrase", "expectedRelayName"], ["inviteToken", "phrase", "expectedRelayName"]);
    const suppliedHash = tokenHash(body.inviteToken);
    if (room.usedInviteTokenHashes.some((used) => crypto.timingSafeEqual(used, suppliedHash))) {
      throw apiError(409, "invite_replayed", "this invitation has already been used");
    }
    if (room.status !== "waiting") throw apiError(409, "room_not_waiting", "room is not accepting joins");
    if (!tokenMatches(room.inviteTokenHash, body.inviteToken)) {
      throw apiError(401, "invalid_invitation", "invitation is invalid or was reissued");
    }
    const normalizePhrase = (value) => String(value).replace(/[\s·•._-]/g, "");
    const suppliedPhrase = normalizePhrase(cleanText(body.phrase, 40, "phrase"));
    if (suppliedPhrase !== normalizePhrase(room.humanPhrase)) {
      room.failedPhraseAttempts += 1;
      if (room.failedPhraseAttempts >= 5) {
        room.inviteTokenHash = null;
        room.status = "revoked";
        addEvent(room, "invite.locked", "server", "核对短语连续错误，邀请已锁定");
      }
      throw apiError(403, "phrase_mismatch", "human-check phrase does not match");
    }
    const expectedRelayName = cleanText(body.expectedRelayName, 60, "expectedRelayName");
    if (expectedRelayName.normalize("NFKC").replace(/\s/g, "").toLocaleLowerCase("zh-CN") !== room.family.relayName.normalize("NFKC").replace(/\s/g, "").toLocaleLowerCase("zh-CN")) {
      throw apiError(403, "relay_name_mismatch", "substitute name does not match the caregiver's expected participant");
    }
    const relayToken = randomToken();
    room.usedInviteTokenHashes.push(room.inviteTokenHash);
    room.inviteTokenHash = null;
    room.relayTokenHash = tokenHash(relayToken);
    room.relayParticipantId = `relay-${randomToken(9)}`;
    room.status = "paired";
    room.pairedAt = new Date().toISOString();
    room.relayLastSeenAt = Date.now();
    addEvent(room, "relay.paired", "relay", `${room.family.relayName}已通过核对短语配对`);
    sendJSON(response, 200, {
      relayToken,
      sessionId: room.sessionId,
      participantId: room.relayParticipantId,
      room: roomProjection(room, "relay"),
    });
    return;
  }

  if (operation === "reissue" && request.method === "POST") {
    requireRole(request, room, ["caregiver"]);
    const body = await readJSON(request);
    const endpointContext = ACTION_CONTEXT.filter((key) => key !== "type");
    exactKeys(body, endpointContext, endpointContext);
    checkMutation(room, { ...body, type: "caregiver.reissue" }, "caregiver", "caregiver.reissue");
    if (["active", "debrief"].includes(room.status)) throw apiError(409, "room_active", "finish or revoke the current rehearsal first");
    const invitation = invitationFor(room, request);
    addEvent(room, "invite.reissued", "caregiver", "旧邀请和替班者凭证已失效，新邀请已签发");
    sendJSON(response, 200, { invitation, room: roomProjection(room, "caregiver") });
    return;
  }

  if (operation === "revoke" && request.method === "POST") {
    requireRole(request, room, ["caregiver"]);
    const body = await readJSON(request);
    const endpointContext = ACTION_CONTEXT.filter((key) => key !== "type");
    exactKeys(body, endpointContext, endpointContext);
    checkMutation(room, { ...body, type: "caregiver.revoke" }, "caregiver", "caregiver.revoke");
    if (room.startedAt && !room.summary) {
      room.endedAt = new Date().toISOString();
      room.summary = {
        outcomeVersion: OUTCOME_VERSION,
        sessionId: room.sessionId,
        status: "revoked",
        startSnapshot: room.startSnapshot || buildStartSnapshot(room),
        facts: observableFacts(room, "revoked", room.endedAt),
        tasks: [...room.tasks], completedTasks: room.tasks.filter(Boolean).length,
        notes: room.timeline.filter((event) => event.type === "relay.note").length,
        alerts: room.timeline.filter((event) => event.type === "relay.alert").length,
        caregiverNote: "", durationSeconds: Math.max(0, Math.floor((Date.now() - new Date(room.startedAt).getTime()) / 1000)), debrief: null,
      };
    }
    room.inviteTokenHash = null;
    room.relayTokenHash = null;
    room.status = "revoked";
    room.terminalAt = Date.now();
    addEvent(room, "room.revoked", "caregiver", "照护者已撤销本次双机连接");
    sendJSON(response, 200, { room: roomProjection(room, "caregiver") });
    return;
  }

  if (operation === "snapshot" && request.method === "POST") {
    requireRole(request, room, ["caregiver"]);
    const body = await readJSON(request);
    const endpointContext = ACTION_CONTEXT.filter((key) => key !== "type");
    exactKeys(body, [...endpointContext, "current"], [...endpointContext, "current"]);
    exactKeys(body.current, ["valid", "consentRevision", "guideVersion", "safetyRevision"], ["valid", "consentRevision", "guideVersion", "safetyRevision"]);
    checkMutation(room, { ...body, type: "caregiver.snapshot" }, "caregiver", "caregiver.snapshot");
    const currentConsent = positiveInteger(body.current.consentRevision, "current.consentRevision", 1, 1000000);
    const currentGuideVersion = positiveInteger(body.current.guideVersion, "current.guideVersion", 1, 1000000);
    const currentSafety = cleanText(body.current.safetyRevision, 100, "current.safetyRevision");
    const changed = body.current.valid !== true || currentConsent !== room.consentRevision || currentGuideVersion !== room.guide.version || currentSafety !== room.safetyRevision;
    if (changed) {
      if (room.startedAt && !room.summary) {
        room.endedAt = new Date().toISOString();
        room.summary = {
          outcomeVersion: OUTCOME_VERSION,
          sessionId: room.sessionId,
          status: "revoked",
          startSnapshot: room.startSnapshot || buildStartSnapshot(room),
          facts: observableFacts(room, "revoked", room.endedAt),
          tasks: [...room.tasks], completedTasks: room.tasks.filter(Boolean).length,
          notes: room.timeline.filter((event) => event.type === "relay.note").length,
          alerts: room.timeline.filter((event) => event.type === "relay.alert").length,
          caregiverNote: "", durationSeconds: Math.max(0, Math.floor((Date.now() - new Date(room.startedAt).getTime()) / 1000)), debrief: null,
        };
      }
      room.status = "invalidated";
      room.terminalAt = Date.now();
      room.inviteTokenHash = null;
      room.acknowledgements = { caregiver: null, relay: null };
      addEvent(room, "room.invalidated", "caregiver", "同意、指导、红线或联系电话已变化，本次房间已失效");
    }
    sendJSON(response, 200, { changed, room: roomProjection(room, "caregiver") });
    return;
  }

  if (operation === "actions" && request.method === "POST") {
    const role = requireRole(request, room, ["caregiver", "relay"]);
    const body = await readJSON(request);
    const common = ACTION_CONTEXT;
    const action = body.type;
    if (action === "caregiver.acknowledge" || action === "relay.acknowledge") {
      const acknowledgementFields = ["scopeAcknowledged", "currentGuideAcknowledged", "redLinesAcknowledged", "contactsAcknowledged"];
      exactKeys(body, [...common, ...acknowledgementFields], [...common, ...acknowledgementFields]);
      const expectedRole = action.startsWith("caregiver.") ? "caregiver" : "relay";
      if (role !== expectedRole) throw apiError(403, "role_forbidden", `only the ${expectedRole} can acknowledge this role`);
      checkMutation(room, body, role, action);
      if (room.status !== "paired") throw apiError(409, "not_paired", "both participants can acknowledge only after pairing");
      if (!acknowledgementFields.every((field) => body[field] === true)) {
        throw apiError(400, "incomplete_acknowledgement", "scope, guide, red lines, and contacts must all be explicitly acknowledged");
      }
      room.acknowledgements[role] = {
        at: new Date().toISOString(),
        participantId: participantIdFor(room, role),
        consentRevision: room.consentRevision,
        guideVersion: room.guide.version,
        safetyRevision: room.safetyRevision,
      };
      addEvent(room, action, role, role === "caregiver" ? "照护者已确认本次范围、指导、红线和联系路径" : "替班者已确认本次范围、指导、红线和联系路径");
    } else if (action === "caregiver.start") {
      exactKeys(body, common, common);
      if (role !== "caregiver") throw apiError(403, "role_forbidden", "only the caregiver can start");
      checkMutation(room, body, role, action);
      if (room.status !== "paired") throw apiError(409, "not_paired", "the substitute must pair first");
      if (!room.acknowledgements.caregiver || !room.acknowledgements.relay) {
        throw apiError(409, "confirmations_incomplete", "both roles must acknowledge scope, guide, red lines, and contacts before start");
      }
      room.status = "active";
      room.startedAt = new Date().toISOString();
      room.startSnapshot = buildStartSnapshot(room);
      addEvent(room, action, role, "照护者已开始双机彩排");
    } else if (action === "caregiver.end") {
      exactKeys(body, [...common, "caregiverNote"], common);
      if (role !== "caregiver") throw apiError(403, "role_forbidden", "only the caregiver can end");
      checkMutation(room, body, role, action);
      if (room.status !== "active") throw apiError(409, "not_active", "the rehearsal is not active");
      const note = cleanText(body.caregiverNote || "", 240, "caregiverNote", { required: false });
      if (SafetyPolicy.classifyText(note).highRisk) {
        throw apiError(422, "unsafe_routine_note", "medical/high-risk text cannot be stored as a routine caregiver note");
      }
      room.status = "debrief";
      room.endedAt = new Date().toISOString();
      const notes = room.timeline.filter((event) => event.type === "relay.note").length;
      const alerts = room.timeline.filter((event) => event.type === "relay.alert").length;
      const relayConnected = Boolean(room.relayLastSeenAt && Date.now() - room.relayLastSeenAt < 6000);
      const completionStatus = !relayConnected ? "disconnected" : room.tasks.every(Boolean) ? "completed" : "interrupted";
      room.summary = {
        outcomeVersion: OUTCOME_VERSION,
        sessionId: room.sessionId,
        status: completionStatus,
        startSnapshot: room.startSnapshot,
        facts: observableFacts(room, completionStatus, room.endedAt),
        tasks: [...room.tasks],
        completedTasks: room.tasks.filter(Boolean).length,
        notes,
        alerts,
        caregiverNote: note,
        durationSeconds: Math.max(0, Math.floor((Date.now() - new Date(room.startedAt).getTime()) / 1000)),
        debrief: null,
      };
      addEvent(room, action, role, completionStatus === "completed" ? "现场事实已同步，等待双方分别填写简短回看" : `现场以“${completionStatus}”结束，没有按完成计算`);
    } else if (action === "caregiver.checkin" || action === "relay.checkin") {
      exactKeys(body, [...common, "response"], [...common, "response"]);
      const expectedRole = action.startsWith("caregiver.") ? "caregiver" : "relay";
      if (role !== expectedRole) throw apiError(403, "role_forbidden", `only the ${expectedRole} can write this role's check-in`);
      checkMutation(room, body, role, action);
      if (!["debrief", "ended"].includes(room.status)) throw apiError(409, "checkin_not_open", "check-in is available only after the factual session end");
      room.checkIns[role === "relay" ? "substitute" : "caregiver"] = roleCheckIn(body.response, role, participantIdFor(room, role));
      addEvent(room, action, role, role === "caregiver" ? "照护者已保存自己的回看（可稍后补充）" : "替班者已保存自己的回看（可稍后补充）");
    } else if (action === "caregiver.contact-opened" || action === "relay.contact-opened") {
      exactKeys(body, [...common, "target"], [...common, "target"]);
      const expectedRole = action.startsWith("caregiver.") ? "caregiver" : "relay";
      if (role !== expectedRole) throw apiError(403, "role_forbidden", `only the ${expectedRole} can record its own contact action`);
      checkMutation(room, body, role, action);
      if (room.status !== "active") throw apiError(409, "not_active", "contact actions are recorded only during the live session");
      const target = cleanText(body.target, 40, "target");
      if (!["caregiver", "emergency-service"].includes(target)) throw apiError(400, "invalid_field", "target is invalid");
      addEvent(room, action, role, "已打开联系操作（不代表通话接通）", { target });
    } else if (action === "caregiver.finalize") {
      exactKeys(body, [...common, "outcome", "gap", "instruction", "sourceId", "sourceLabel"], [...common, "outcome", "gap", "instruction", "sourceId", "sourceLabel"]);
      if (role !== "caregiver") throw apiError(403, "role_forbidden", "only the caregiver can finalize the debrief");
      checkMutation(room, body, role, action);
      if (room.status !== "debrief") throw apiError(409, "not_in_debrief", "the room is not awaiting a debrief");
      const outcome = cleanText(body.outcome, 30, "outcome");
      if (!["confirmed-guide", "pending-gap"].includes(outcome)) throw apiError(400, "invalid_outcome", "debrief outcome is invalid");
      const gap = cleanText(body.gap, 160, "gap");
      const instruction = cleanText(body.instruction, 500, "instruction", { required: outcome === "confirmed-guide" });
      const sourceId = cleanText(body.sourceId, 80, "sourceId", { required: outcome === "confirmed-guide" });
      cleanText(body.sourceLabel, 80, "sourceLabel", { required: outcome === "confirmed-guide" });
      const classification = SafetyPolicy.classifyFields([gap, instruction]);
      const risky = classification.highRisk;
      if (outcome === "confirmed-guide" && risky) {
        throw apiError(422, "unsafe_debrief", "high-risk debriefs must remain pending for a professional reference");
      }
      if (outcome === "confirmed-guide" && !SafetyPolicy.isRecognizedActorId(sourceId)) {
        throw apiError(400, "invalid_source", "debrief source is invalid");
      }
      if (outcome === "confirmed-guide" && sourceId === SafetyPolicy.PROFESSIONAL_SOURCE_ID) {
        throw apiError(422, "unverified_professional_source", "browser-authored debrief text cannot claim professional provenance");
      }
      if (outcome === "pending-gap") {
        const key = normalizedQuery(gap);
        const existing = room.pendingGaps.find((item) => item.normalizedQuery === key && item.status === "pending");
        if (existing) {
          existing.encounters += 1;
          if (risky) existing.risk = "medical";
        }
        else room.pendingGaps.push({
          id: `gap-${randomToken(8)}`,
          query: gap,
          normalizedQuery: key,
          risk: risky ? "medical" : "ordinary",
          status: "pending",
          encounters: 1,
          createdAt: Date.now(),
        });
      }
      // The factual end is created before provenance review, so any gap first
      // disclosed during that review must be copied into the same immutable
      // session facts used by progression. Room-level pending state alone is
      // not sufficient: durable clients and OutcomeModel consume summary.facts.
      room.summary.facts = {
        ...room.summary.facts,
        pendingGaps: room.pendingGaps.map((item) => ({
          id: item.id,
          risk: item.risk === "medical" ? "medical" : "ordinary",
          status: item.status === "resolved" ? "resolved" : "pending",
        })),
      };
      room.summary.debrief = {
        outcome,
        gap,
        instruction: outcome === "confirmed-guide" ? instruction : "",
        sourceId: outcome === "confirmed-guide" ? sourceId : "",
        sourceLabel: outcome === "confirmed-guide" ? SafetyPolicy.canonicalSourceLabel(sourceId, room.family) : "",
        risk: risky ? "medical" : "ordinary",
        urgent: risky,
        policyVersion: SafetyPolicy.VERSION,
        confirmedAt: new Date().toISOString(),
      };
      room.status = "ended";
      room.terminalAt = Date.now();
      addEvent(room, action, role, outcome === "confirmed-guide" ? "照护者已确认复盘来源，共享总结完成" : "复盘问题已进入待确认缺口，共享总结完成");
    } else if (action === "relay.task") {
      exactKeys(body, [...common, "index"], [...common, "index"]);
      if (role !== "relay") throw apiError(403, "role_forbidden", "only the substitute can update tasks");
      checkMutation(room, body, role, action);
      if (room.status !== "active") throw apiError(409, "not_active", "the rehearsal is not active");
      const index = positiveInteger(body.index, "index", 0, 2);
      if (room.tasks[index]) throw apiError(409, "already_completed", "task is already complete");
      room.tasks[index] = true;
      addEvent(room, action, role, `替班者完成了第 ${index + 1} 步`, { taskIndex: index });
    } else if (action === "relay.note") {
      exactKeys(body, [...common, "text"], [...common, "text"]);
      if (role !== "relay") throw apiError(403, "role_forbidden", "only the substitute can add a note");
      checkMutation(room, body, role, action);
      if (room.status !== "active") throw apiError(409, "not_active", "the rehearsal is not active");
      const note = cleanText(body.text, 240, "text");
      if (SafetyPolicy.classifyText(note).highRisk) throw apiError(422, "use_urgent_alert", "high-risk text must use the urgent contact path");
      addEvent(room, action, role, note);
    } else if (action === "relay.search") {
      exactKeys(body, [...common, "query"], [...common, "query"]);
      if (role !== "relay") throw apiError(403, "role_forbidden", "only the substitute can search the authorized room scope");
      checkMutation(room, body, role, action);
      if (room.status !== "active") throw apiError(409, "not_active", "the rehearsal is not active");
      const query = cleanText(body.query, 240, "query");
      const risky = SafetyPolicy.classifyText(query).highRisk;
      const matched = matchScopedGuide(room, query);
      if (matched) {
        room.lastSearch = { status: "matched", query, risk: risky ? "medical" : "ordinary", urgent: risky, guide: { ...matched } };
        addEvent(room, "relay.search.matched", role, risky ? `医疗或高风险问题只匹配到专业立即联系指示：${matched.title}` : `替班者查到已确认指导：${matched.title}`, { urgent: risky });
      } else {
        const key = normalizedQuery(query);
        let gap = room.pendingGaps.find((item) => item.normalizedQuery === key && item.status === "pending");
        if (gap) {
          gap.encounters += 1;
          if (risky) gap.risk = "medical";
        }
        else {
          gap = {
            id: `gap-${randomToken(8)}`,
            query,
            normalizedQuery: key,
            risk: risky ? "medical" : "ordinary",
            status: "pending",
            encounters: 1,
            createdAt: Date.now(),
          };
          room.pendingGaps.push(gap);
        }
        room.lastSearch = { status: "pending", query, risk: gap.risk, urgent: risky, gapId: gap.id, guide: null };
        addEvent(room, "relay.search.pending", role, risky ? "医疗或高风险问题没有当前专业匹配，已进入待确认并应立即联系" : query, { urgent: risky });
      }
    } else if (action === "relay.alert") {
      exactKeys(body, [...common, "text"], [...common, "text"]);
      if (role !== "relay") throw apiError(403, "role_forbidden", "only the substitute can raise an alert");
      checkMutation(room, body, role, action);
      if (room.status !== "active") throw apiError(409, "not_active", "the rehearsal is not active");
      const alert = cleanText(body.text, 120, "text");
      addEvent(room, action, role, alert, { urgent: true });
    } else if (action === "relay.ready") {
      exactKeys(body, common, common);
      if (role !== "relay") throw apiError(403, "role_forbidden", "only the substitute can mark ready");
      checkMutation(room, body, role, action);
      if (room.status !== "active") throw apiError(409, "not_active", "the rehearsal is not active");
      addEvent(room, action, role, "替班者已完成现场步骤，等待照护者结束");
    } else {
      throw apiError(400, "invalid_action", "unsupported action");
    }
    sendJSON(response, 200, { room: roomProjection(room, role) });
    return;
  }

  throw apiError(405, "method_not_allowed", "method not allowed");
}

function serveStatic(request, response, url) {
  let pathname = decodeURIComponent(url.pathname);
  if (pathname === "/") pathname = "/index.html";
  const candidate = path.resolve(ROOT, `.${pathname}`);
  if (!candidate.startsWith(`${ROOT}${path.sep}`)) {
    sendJSON(response, 403, { error: { code: "forbidden", message: "forbidden" } });
    return;
  }
  fs.stat(candidate, (statError, stat) => {
    if (statError || !stat.isFile()) {
      sendJSON(response, 404, { error: { code: "not_found", message: "not found" } });
      return;
    }
    const headers = {
      "Content-Type": MIME[path.extname(candidate)] || "application/octet-stream",
      "Content-Length": stat.size,
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
      "Content-Security-Policy": "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; media-src 'self'; manifest-src 'self'; worker-src 'self'",
      "Permissions-Policy": "camera=(), geolocation=(), microphone=(self)",
      "Cache-Control": pathname.endsWith(".html") ? "no-store" : "public, max-age=60",
    };
    response.writeHead(200, headers);
    if (request.method === "HEAD") response.end();
    else fs.createReadStream(candidate).pipe(response);
  });
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, `http://${request.headers.host || "localhost"}`);
  try {
    if (url.pathname.startsWith("/api/")) await handleAPI(request, response, url);
    else if (["GET", "HEAD"].includes(request.method)) serveStatic(request, response, url);
    else throw apiError(405, "method_not_allowed", "method not allowed");
  } catch (error) {
    sendJSON(response, error.status || 500, {
      error: {
        code: error.code || "internal_error",
        message: error.status ? error.message : "internal server error",
        ...(error.details || {}),
      },
    });
  }
});

if (require.main === module) {
  server.listen(PORT, HOST, () => {
    const address = server.address();
    const listeningPort = address && typeof address === "object" ? address.port : PORT;
    console.log(`接班彩排与双机服务已启动：http://${HOST}:${listeningPort}`);
  });
}

module.exports = { server, rooms };
