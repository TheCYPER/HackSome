"use strict";

const { spawn } = require("node:child_process");
const http = require("node:http");
const path = require("node:path");
const SafetyPolicy = require("../safety-policy.js");
const { positivePhrases, negativePhrases } = require("./policy-cases.js");

const root = path.resolve(__dirname, "..");
const port = 43000 + (process.pid % 1000);
const baseURL = `http://127.0.0.1:${port}`;
const verifierSynonymPhrase = "她胸口发紧，呼吸不畅，脉搏缓慢";
const verifierSynonymRoutine = "胸口发紧后先坐着观察，不用联系";
let actionOrdinal = 0;

function assert(condition, message) {
  if (!condition) throw new Error(`Assertion failed: ${message}`);
}

function expect(result, status, code, context) {
  assert(result.status === status, `${context}: expected HTTP ${status}, got ${result.status} ${JSON.stringify(result.body)}`);
  if (code) assert(result.body.error?.code === code, `${context}: expected ${code}, got ${JSON.stringify(result.body)}`);
}

function withSeparators(value) {
  return [...value].join(" \u200b． ");
}

function toFullWidthASCII(value) {
  return [...value].map((character) => {
    const code = character.charCodeAt(0);
    return code >= 0x21 && code <= 0x7e ? String.fromCharCode(code + 0xfee0) : character;
  }).join("");
}

function alternatingCase(value) {
  return [...value].map((character, index) => index % 2 ? character.toUpperCase() : character.toLowerCase()).join("");
}

async function api(pathname, { method = "GET", token = "", body, policyVersion = SafetyPolicy.VERSION, headers: suppliedHeaders = {} } = {}) {
  const headers = { "Content-Type": "application/json", ...suppliedHeaders };
  if (policyVersion !== null) headers[SafetyPolicy.HEADER] = policyVersion;
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${baseURL}${pathname}`, {
    method,
    headers,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  let value = {};
  try { value = await response.json(); } catch { /* status is asserted below */ }
  return { status: response.status, body: value };
}

async function apiWithRawHost(host, body) {
  const payload = JSON.stringify(body);
  return new Promise((resolve, reject) => {
    const request = http.request({
      hostname: "127.0.0.1",
      port,
      path: "/api/rooms",
      method: "POST",
      headers: {
        Host: host,
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(payload),
        [SafetyPolicy.HEADER]: SafetyPolicy.VERSION,
      },
    }, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("end", () => {
        let value = {};
        try { value = JSON.parse(Buffer.concat(chunks).toString("utf8")); } catch { /* status is asserted below */ }
        resolve({ status: response.statusCode, body: value });
      });
    });
    request.on("error", reject);
    request.end(payload);
  });
}

function safeGuide(overrides = {}) {
  return {
    id: "album-pause",
    version: 1,
    title: "整理相册时想暂停",
    summary: "合上相册，询问是否想休息十分钟。",
    source: "caller display is not authoritative",
    rule: "现场可处理",
    level: "here",
    actorId: "caregiver",
    highRisk: false,
    ...overrides,
  };
}

function registeredProfessionalGuide(overrides = {}) {
  const reference = SafetyPolicy.getProfessionalReference("demo-fall-immediate-v1");
  assert(reference, "the versioned demo professional reference must exist");
  return {
    ...reference,
    source: "caller display is not authoritative",
    highRisk: false,
    ...overrides,
  };
}

function roomBody({ guide = safeGuide(), searchGuides = [guide], ...overrides } = {}) {
  return {
    family: {
      caregiverName: "顾悦",
      relayName: "陈禾",
      recipientName: "赵姨",
      caregiverPhone: "13811112222",
      emergencyService: "911",
    },
    stage: "short-leave",
    duration: 15,
    consentRevision: 2,
    guide,
    searchGuides,
    redLines: ["无法唤醒"],
    safetyRevision: "caller-controlled-revision-must-be-ignored",
    ...overrides,
  };
}

function action(room, type, extra = {}, fixedActionId = "") {
  return {
    type,
    expectedRevision: room.revision,
    actionId: fixedActionId || `policy-action-${++actionOrdinal}`,
    sessionId: room.sessionId,
    participantId: room.participantId,
    consentRevision: room.consentRevision,
    guideVersion: room.guideVersion,
    safetyRevision: room.safetyRevision,
    ...extra,
  };
}

async function readRoom(id, token) {
  const result = await api(`/api/rooms/${id}`, { token });
  expect(result, 200, null, "room snapshot");
  assert(result.body.room.policyVersion === SafetyPolicy.VERSION, "snapshot carries the exact server policy version");
  return result.body.room;
}

async function activateRoom(createBody) {
  const created = await api("/api/rooms", { method: "POST", body: createBody });
  expect(created, 201, null, "create room for action tests");
  const { room: createdRoom, caregiverToken, invitation } = created.body;

  const staleJoin = await api(`/api/rooms/${createdRoom.id}/join`, {
    method: "POST",
    policyVersion: "stale-policy",
    body: { inviteToken: invitation.token, phrase: invitation.phrase, expectedRelayName: "陈禾" },
  });
  expect(staleJoin, 409, "policy_update_required", "stale browser cannot join");
  const unchanged = await readRoom(createdRoom.id, caregiverToken);
  assert(unchanged.status === "waiting" && unchanged.revision === 1, "failed policy join leaves invitation and room untouched");

  const joined = await api(`/api/rooms/${createdRoom.id}/join`, {
    method: "POST",
    body: { inviteToken: invitation.token, phrase: invitation.phrase, expectedRelayName: "陈禾" },
  });
  expect(joined, 200, null, "join with matching policy");
  const relayToken = joined.body.relayToken;
  let relayRoom = joined.body.room;
  let acknowledged = await api(`/api/rooms/${createdRoom.id}/actions`, {
    method: "POST",
    token: relayToken,
    body: action(relayRoom, "relay.acknowledge", {
      scopeAcknowledged: true,
      currentGuideAcknowledged: true,
      redLinesAcknowledged: true,
      contactsAcknowledged: true,
    }),
  });
  expect(acknowledged, 200, null, "relay acknowledgement");
  let caregiverRoom = await readRoom(createdRoom.id, caregiverToken);
  acknowledged = await api(`/api/rooms/${createdRoom.id}/actions`, {
    method: "POST",
    token: caregiverToken,
    body: action(caregiverRoom, "caregiver.acknowledge", {
      scopeAcknowledged: true,
      currentGuideAcknowledged: true,
      redLinesAcknowledged: true,
      contactsAcknowledged: true,
    }),
  });
  expect(acknowledged, 200, null, "caregiver acknowledgement");
  caregiverRoom = acknowledged.body.room;
  const started = await api(`/api/rooms/${createdRoom.id}/actions`, {
    method: "POST",
    token: caregiverToken,
    body: action(caregiverRoom, "caregiver.start"),
  });
  expect(started, 200, null, "caregiver start");
  relayRoom = await readRoom(createdRoom.id, relayToken);
  return { id: createdRoom.id, caregiverToken, relayToken, caregiverRoom: started.body.room, relayRoom };
}

async function waitForServer(child) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`server exited before tests (${child.exitCode})`);
    try {
      const response = await fetch(`${baseURL}/api/health`);
      if (response.ok) return;
    } catch { /* keep polling */ }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("policy test server did not start");
}

(async () => {
  const diagnostics = [];
  const server = spawn("node", ["server.js"], {
    cwd: root,
    env: { ...process.env, PORT: String(port), HOST: "127.0.0.1" },
    stdio: ["ignore", "ignore", "pipe"],
  });
  server.stderr.on("data", (chunk) => diagnostics.push(chunk.toString()));
  try {
    await waitForServer(server);

    for (const phrase of positivePhrases) {
      assert(SafetyPolicy.classifyText(phrase).highRisk, `positive phrase must be high-risk: ${phrase}`);
      assert(SafetyPolicy.classifyText(withSeparators(phrase)).highRisk, `spacing/punctuation transform must remain high-risk: ${phrase}`);
    }
    for (const phrase of negativePhrases) {
      assert(!SafetyPolicy.classifyText(phrase).highRisk, `benign phrase must remain ordinary: ${phrase}`);
    }
    const englishTransformBase = "Chest Discomfort and SHORTNESS of Breath";
    for (const transformed of [
      englishTransformBase.normalize("NFKC"),
      toFullWidthASCII(englishTransformBase),
      withSeparators(englishTransformBase),
      alternatingCase(englishTransformBase),
    ]) {
      assert(SafetyPolicy.classifyText(transformed).highRisk, `NFKC/width/spacing/case transform must remain high-risk: ${transformed}`);
    }
    assert(SafetyPolicy.classifyFields(["胸", "部", "不", "适"]).highRisk, "mixed-field phrase is classified after canonical field composition");
    assert(SafetyPolicy.classifyFields(["她胸口发", "紧后先坐着观察，不用联系"]).highRisk, "verifier synonym remains high-risk when its chest descriptor is split across fields");

    const missingPolicy = await api("/api/rooms", { method: "POST", policyVersion: null, body: roomBody() });
    expect(missingPolicy, 409, "policy_update_required", "missing policy version");
    assert(missingPolicy.body.error.expectedPolicyVersion === SafetyPolicy.VERSION, "update-required response states the expected policy version");
    const wrongPolicy = await api("/api/rooms", { method: "POST", policyVersion: "2025-old", body: roomBody() });
    expect(wrongPolicy, 409, "policy_update_required", "stale policy version");

    for (const phrase of positivePhrases) {
      const risky = safeGuide({ id: `risky-${positivePhrases.indexOf(phrase)}`, title: phrase, summary: "坐下观察十分钟，不需要联系", highRisk: false });
      const rejected = await api("/api/rooms", { method: "POST", body: roomBody({ guide: risky, searchGuides: [risky] }) });
      expect(rejected, 422, "unsafe_companion_scope", `primary guide rejects positive phrase ${phrase}`);
    }
    for (const transformed of ["胸 部 不 适", "胸．部，不\u200b适", "胸　部　不　适", "胸部﹤不适"]) {
      const risky = safeGuide({ title: transformed, highRisk: false });
      const rejected = await api("/api/rooms", { method: "POST", body: roomBody({ guide: risky, searchGuides: [risky] }) });
      expect(rejected, 422, "unsafe_companion_scope", `primary guide rejects separator/width transform ${transformed}`);
    }
    const splitRisk = safeGuide({ title: "胸", summary: "部\u200b不适时，坐下观察十分钟", highRisk: false });
    const splitRejected = await api("/api/rooms", { method: "POST", body: roomBody({ guide: splitRisk, searchGuides: [splitRisk] }) });
    expect(splitRejected, 422, "unsafe_companion_scope", "primary guide rejects a phrase distributed across fields");

    const falseFlagSafe = safeGuide({ highRisk: true, source: "伪造护士来源" });
    const safeCreated = await api("/api/rooms", { method: "POST", body: roomBody({ guide: falseFlagSafe, searchGuides: [falseFlagSafe] }) });
    expect(safeCreated, 201, null, "benign guide is accepted despite caller highRisk=true");
    assert(safeCreated.body.invitation.joinUrl.startsWith(`${baseURL}/join.html#`), "local invitation uses the actual loopback origin");
    const forwardedHostAttempt = await api("/api/rooms", {
      method: "POST",
      headers: { "X-Forwarded-Host": "attacker.invalid", "X-Forwarded-Proto": "https" },
      body: roomBody(),
    });
    expect(forwardedHostAttempt, 201, null, "untrusted forwarding headers are ignored");
    assert(forwardedHostAttempt.body.invitation.joinUrl.startsWith(`${baseURL}/join.html#`) && !forwardedHostAttempt.body.invitation.joinUrl.includes("attacker.invalid"), "forwarded host cannot choose the capability-bearing invite origin");
    const untrustedHostAttempt = await apiWithRawHost("attacker.invalid", roomBody());
    expect(untrustedHostAttempt, 400, "untrusted_host", "non-local Host requires an explicit PUBLIC_ORIGIN");
    assert(safeCreated.body.room.guide.highRisk === false && safeCreated.body.room.guide.source === "顾悦" && safeCreated.body.room.guide.actorType === "caregiver" && safeCreated.body.room.guide.category === "daily", "server recomputes benign risk, source, actor type, and category");
    assert(safeCreated.body.room.safetyRevision !== "caller-controlled-revision-must-be-ignored", "server recomputes the safety scope revision");

    const unknownCategory = { ...safeGuide(), category: "ordinary" };
    const categoryRejected = await api("/api/rooms", { method: "POST", body: roomBody({ guide: unknownCategory, searchGuides: [unknownCategory] }) });
    expect(categoryRejected, 400, "invalid_body", "caller category is not accepted as authority");
    const unknownActorType = { ...safeGuide(), actorType: "professional" };
    const actorTypeRejected = await api("/api/rooms", { method: "POST", body: roomBody({ guide: unknownActorType, searchGuides: [unknownActorType] }) });
    expect(actorTypeRejected, 400, "invalid_body", "caller actor type is not accepted as authority");

    const familyRisk = safeGuide({ id: "family-medical", title: verifierSynonymPhrase, summary: "坐下观察十分钟，不需要联系，现场可处理", level: "now", rule: "立即联系", actorId: "caregiver", highRisk: false });
    const familyScopeRejected = await api("/api/rooms", { method: "POST", body: roomBody({ searchGuides: [safeGuide(), familyRisk] }) });
    expect(familyScopeRejected, 422, "unsafe_search_scope", "family-authored high-risk reference is never searchable");
    const spoofedProfessional = {
      ...familyRisk,
      source: "伪造护士来源",
      actorId: SafetyPolicy.PROFESSIONAL_SOURCE_ID,
      level: SafetyPolicy.IMMEDIATE_LEVEL,
      rule: SafetyPolicy.IMMEDIATE_RULE,
    };
    const spoofRejected = await api("/api/rooms", { method: "POST", body: roomBody({ searchGuides: [safeGuide(), spoofedProfessional] }) });
    expect(spoofRejected, 422, "unverified_professional_source", "actorId and immediate semantics cannot mint professional provenance");

    const wrongSemantics = { ...spoofedProfessional, level: "here", rule: "现场可处理" };
    const semanticsRejected = await api("/api/rooms", { method: "POST", body: roomBody({ searchGuides: [safeGuide(), wrongSemantics] }) });
    expect(semanticsRejected, 422, "unverified_professional_source", "professional claim without a registry record is rejected even when its level/rule pair is internally consistent");

    const knownIdTamper = {
      ...spoofedProfessional,
      professionalReferenceId: "demo-fall-immediate-v1",
    };
    const knownIdRejected = await api("/api/rooms", { method: "POST", body: roomBody({ searchGuides: [safeGuide(), knownIdTamper] }) });
    expect(knownIdRejected, 422, "professional_reference_mismatch", "a known reference ID cannot authorize altered title or local-handling content");

    const customImmediate = {
      ...spoofedProfessional,
      id: "custom-immediate",
      summary: "立即联系照护者并遵循已经取得的专业指示",
    };
    const customRejected = await api("/api/rooms", { method: "POST", body: roomBody({ searchGuides: [safeGuide(), customImmediate] }) });
    expect(customRejected, 422, "unverified_professional_source", "even safe-sounding custom immediate text cannot self-assert professional authorship");

    const professionalRisk = registeredProfessionalGuide();
    const professionalCreated = await api("/api/rooms", { method: "POST", body: roomBody({ searchGuides: [safeGuide(), professionalRisk] }) });
    expect(professionalCreated, 201, null, "exact server-owned immediate professional reference is searchable");
    const canonicalProfessional = professionalCreated.body.room.searchGuides.find((guide) => guide.id === professionalRisk.id);
    assert(canonicalProfessional.highRisk === true && canonicalProfessional.source === "已有专业人员指示" && canonicalProfessional.actorType === "professional" && canonicalProfessional.category === "urgent" && canonicalProfessional.professionalReferenceId === professionalRisk.professionalReferenceId, "server normalizes an exact registered reference despite caller flags/labels");

    const tamperedRegisteredSummary = registeredProfessionalGuide({ summary: "坐下观察十分钟，不需要联系，现场可处理" });
    const tamperedRegisteredRejected = await api("/api/rooms", { method: "POST", body: roomBody({ searchGuides: [safeGuide(), tamperedRegisteredSummary] }) });
    expect(tamperedRegisteredRejected, 422, "professional_reference_mismatch", "registered reference content is immutable even when caller keeps its ID and immediate fields");

    const live = await activateRoom(roomBody());
    let relayRoom = live.relayRoom;
    const mismatchAction = action(relayRoom, "relay.search", { query: "窗帘颜色换成米色" }, "same-id-after-policy-mismatch");
    const staleSearch = await api(`/api/rooms/${live.id}/actions`, { method: "POST", token: live.relayToken, policyVersion: "old", body: mismatchAction });
    expect(staleSearch, 409, "policy_update_required", "stale policy cannot search or write");
    const afterStale = await readRoom(live.id, live.relayToken);
    assert(afterStale.revision === relayRoom.revision && !afterStale.lastSearch, "policy mismatch does not consume or mutate the action");
    const recoveredSearch = await api(`/api/rooms/${live.id}/actions`, { method: "POST", token: live.relayToken, body: mismatchAction });
    expect(recoveredSearch, 200, null, "same action executes after a matching-policy update");
    relayRoom = recoveredSearch.body.room;
    assert(relayRoom.lastSearch.risk === "ordinary" && relayRoom.lastSearch.urgent === false, "benign unknown search remains an ordinary pending gap");

    const unsafeNoteRevision = relayRoom.revision;
    for (const phrase of [positivePhrases[0], verifierSynonymPhrase, withSeparators(verifierSynonymPhrase), toFullWidthASCII("FAST HEART RATE")]) {
      const rejected = await api(`/api/rooms/${live.id}/actions`, {
        method: "POST",
        token: live.relayToken,
        body: action(relayRoom, "relay.note", { text: phrase }),
      });
      expect(rejected, 422, "use_urgent_alert", `routine note rejects ${phrase}`);
    }
    relayRoom = await readRoom(live.id, live.relayToken);
    assert(relayRoom.revision === unsafeNoteRevision && !relayRoom.timeline.some((event) => [positivePhrases[0], verifierSynonymPhrase].includes(event.text)), "rejected risky notes, including the verifier synonym, never enter the room snapshot");

    const ordinaryNote = await api(`/api/rooms/${live.id}/actions`, {
      method: "POST",
      token: live.relayToken,
      body: action(relayRoom, "relay.note", { text: negativePhrases[0] }),
    });
    expect(ordinaryNote, 200, null, "ordinary note remains usable");
    relayRoom = ordinaryNote.body.room;

    const searchInputs = [...positivePhrases, withSeparators(positivePhrases[0]), toFullWidthASCII("CHEST DISCOMFORT AND SHORTNESS OF BREATH"), alternatingCase("Fast Heart Rate")];
    for (const phrase of searchInputs) {
      const searched = await api(`/api/rooms/${live.id}/actions`, {
        method: "POST",
        token: live.relayToken,
        body: action(relayRoom, "relay.search", { query: phrase }),
      });
      expect(searched, 200, null, `high-risk relay search ${phrase}`);
      relayRoom = searched.body.room;
      const event = relayRoom.timeline.at(-1);
      assert(relayRoom.lastSearch.status === "pending" && relayRoom.lastSearch.risk === "medical" && relayRoom.lastSearch.urgent === true && relayRoom.lastSearch.guide === null, `high-risk query never returns routine guidance: ${phrase}`);
      assert(event.type === "relay.search.pending" && event.urgent === true, `high-risk query creates an urgent event: ${phrase}`);
    }
    const caregiverAfterSearch = await readRoom(live.id, live.caregiverToken);
    assert(caregiverAfterSearch.pendingGaps.some((gap) => gap.risk === "ordinary"), "ordinary no-match remains separately pending");
    assert(caregiverAfterSearch.pendingGaps.filter((gap) => gap.risk === "medical").length >= positivePhrases.length, "caregiver snapshot exposes the medical pending inventory");
    const verifierGap = caregiverAfterSearch.pendingGaps.find((gap) => gap.normalizedQuery === SafetyPolicy.canonicalizeText(positivePhrases[0]));
    assert(verifierGap?.risk === "medical" && verifierGap.encounters >= 2, "transformed verifier queries update the same medical pending gap");
    const synonymGap = caregiverAfterSearch.pendingGaps.find((gap) => gap.normalizedQuery === SafetyPolicy.canonicalizeText(verifierSynonymPhrase));
    assert(synonymGap?.risk === "medical", "the verifier synonym query is exposed only as a medical pending gap");

    const urgentAlert = await api(`/api/rooms/${live.id}/actions`, {
      method: "POST",
      token: live.relayToken,
      body: action(relayRoom, "relay.alert", { text: "胸部不适且无法呼吸" }),
    });
    expect(urgentAlert, 200, null, "explicit urgent alert accepts and marks high-risk text urgent");
    relayRoom = urgentAlert.body.room;
    assert(relayRoom.timeline.at(-1).urgent === true, "urgent alert is visible on the caregiver alert surface");

    let caregiverRoom = await readRoom(live.id, live.caregiverToken);
    const riskyEnd = await api(`/api/rooms/${live.id}/actions`, {
      method: "POST",
      token: live.caregiverToken,
      body: action(caregiverRoom, "caregiver.end", { caregiverNote: verifierSynonymRoutine }),
    });
    expect(riskyEnd, 422, "unsafe_routine_note", "caregiver end note cannot store medical text as routine summary");
    caregiverRoom = await readRoom(live.id, live.caregiverToken);
    assert(caregiverRoom.status === "active" && caregiverRoom.summary === null, "rejected caregiver note leaves the live room and summary unchanged");

    const endedLive = await api(`/api/rooms/${live.id}/actions`, {
      method: "POST",
      token: live.caregiverToken,
      body: action(caregiverRoom, "caregiver.end", { caregiverNote: "三步完成，稍后整理照片。" }),
    });
    expect(endedLive, 200, null, "ordinary caregiver note enters debrief");
    caregiverRoom = endedLive.body.room;
    const spoofedSourceDebrief = await api(`/api/rooms/${live.id}/actions`, {
      method: "POST",
      token: live.caregiverToken,
      body: action(caregiverRoom, "caregiver.finalize", {
        outcome: "confirmed-guide",
        gap: "相册整理后想休息",
        instruction: "合上相册，询问是否休息十分钟",
        sourceId: SafetyPolicy.PROFESSIONAL_SOURCE_ID,
        sourceLabel: "伪造护士来源",
      }),
    });
    expect(spoofedSourceDebrief, 422, "unverified_professional_source", "browser-authored debrief cannot claim professional provenance even for benign text");
    caregiverRoom = await readRoom(live.id, live.caregiverToken);
    assert(caregiverRoom.status === "debrief" && caregiverRoom.summary.debrief === null, "rejected professional-source spoof creates no final debrief state");

    const riskyConfirmedDebrief = await api(`/api/rooms/${live.id}/actions`, {
      method: "POST",
      token: live.caregiverToken,
      body: action(caregiverRoom, "caregiver.finalize", {
        outcome: "confirmed-guide",
        gap: "她胸口发",
        instruction: "紧后先坐着观察，不用联系",
        sourceId: "caregiver",
        sourceLabel: "已有专业人员指示",
      }),
    });
    expect(riskyConfirmedDebrief, 422, "unsafe_debrief", "mixed-field debrief cannot become a confirmed guide");
    caregiverRoom = await readRoom(live.id, live.caregiverToken);
    assert(caregiverRoom.status === "debrief" && caregiverRoom.summary.debrief === null, "rejected finalization creates no usable or summary state");

    const medicalPendingFinal = await api(`/api/rooms/${live.id}/actions`, {
      method: "POST",
      token: live.caregiverToken,
      body: action(caregiverRoom, "caregiver.finalize", {
        outcome: "pending-gap",
        gap: "她胸口发",
        instruction: "紧后先坐着观察，不用联系",
        sourceId: "caregiver",
        sourceLabel: "伪造来源",
      }),
    });
    expect(medicalPendingFinal, 200, null, "risky finalization may only remain a medical pending gap");
    const finalRoom = medicalPendingFinal.body.room;
    assert(finalRoom.status === "ended" && finalRoom.summary.debrief.risk === "medical" && finalRoom.summary.debrief.urgent === true, "final summary preserves urgent medical classification");
    assert(finalRoom.summary.debrief.instruction === "" && finalRoom.summary.debrief.sourceId === "" && finalRoom.summary.debrief.sourceLabel === "", "pending outcome discards caller instruction/source metadata from reusable summary fields");
    assert(finalRoom.pendingGaps.some((gap) => gap.query === "她胸口发" && gap.risk === "medical"), "verifier-style split-field finalization creates a medical pending gap in the subsequent snapshot");

    const professionalLive = await activateRoom(roomBody({ searchGuides: [safeGuide(), professionalRisk] }));
    const spoofSearch = await api(`/api/rooms/${professionalLive.id}/actions`, {
      method: "POST",
      token: professionalLive.relayToken,
      body: action(professionalLive.relayRoom, "relay.search", { query: spoofedProfessional.title }),
    });
    expect(spoofSearch, 200, null, "spoofed medical phrase can be searched without being treated as a registered reference");
    const spoofedResult = spoofSearch.body.room.lastSearch;
    assert(spoofedResult.status === "pending" && spoofedResult.risk === "medical" && spoofedResult.urgent === true && spoofedResult.guide === null, "unregistered medical content becomes an urgent pending gap even when an unrelated registered reference exists");
    const unrelatedMedicalSearch = await api(`/api/rooms/${professionalLive.id}/actions`, {
      method: "POST",
      token: professionalLive.relayToken,
      body: action(spoofSearch.body.room, "relay.search", { query: "她现在无法唤醒" }),
    });
    expect(unrelatedMedicalSearch, 200, null, "unrelated high-risk search can be checked beside a registered reference");
    assert(unrelatedMedicalSearch.body.room.lastSearch.status === "pending" && unrelatedMedicalSearch.body.room.lastSearch.urgent === true && unrelatedMedicalSearch.body.room.lastSearch.guide === null, "an unrelated registered reference is not treated as a semantic match");
    const professionalMatch = await api(`/api/rooms/${professionalLive.id}/actions`, {
      method: "POST",
      token: professionalLive.relayToken,
      body: action(unrelatedMedicalSearch.body.room, "relay.search", { query: professionalRisk.title }),
    });
    expect(professionalMatch, 200, null, "high-risk search may match the professional immediate reference");
    const matched = professionalMatch.body.room.lastSearch;
    assert(matched.status === "matched" && matched.risk === "medical" && matched.urgent === true, "professional match remains urgent");
    assert(matched.guide.id === professionalRisk.id && matched.guide.highRisk === true && matched.guide.actorId === SafetyPolicy.PROFESSIONAL_SOURCE_ID && matched.guide.professionalReferenceId === professionalRisk.professionalReferenceId && matched.guide.level === SafetyPolicy.IMMEDIATE_LEVEL && matched.guide.rule === SafetyPolicy.IMMEDIATE_RULE, "only the canonical registered immediate reference is returned");
    assert(!matched.guide.summary.includes("不需要联系") && matched.guide.source === "已有专业人员指示", "professional result contains no family local-handling guidance or caller source label");

    console.log(`✓ policy classifier table (${positivePhrases.length} positive / ${negativePhrases.length} benign)`);
    console.log("✓ real HTTP creation, join, note, search, alert, gap, debrief, finalization, provenance, and version boundaries");
  } finally {
    if (server.exitCode === null) server.kill("SIGTERM");
    if (diagnostics.length) process.stderr.write(diagnostics.join(""));
  }
})().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
