"use strict";

const { firefox } = require("/usr/local/lib/python3.12/dist-packages/playwright/driver/package");
const { server, rooms } = require("../server");
const SafetyPolicy = require("../safety-policy.js");
const OutcomeModel = require("../outcome-model.js");

const STORAGE_KEY = "relay-rehearsal-demo-v1";
const FIREFOX_PATH = "/home/kasm-user/.cache/ms-playwright/firefox-1509/firefox/firefox";

function assert(condition, message) {
  if (!condition) throw new Error(`Outcome E2E assertion failed: ${message}`);
}

async function listen() {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return `http://127.0.0.1:${server.address().port}`;
}

async function api(baseURL, path, { method = "GET", token = "", body } = {}) {
  const response = await fetch(`${baseURL}${path}`, {
    method,
    headers: { "Content-Type": "application/json", [SafetyPolicy.HEADER]: SafetyPolicy.VERSION, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const value = await response.json();
  return { status: response.status, value };
}

function action(room, type, id, extra = {}) {
  return { type, expectedRevision: room.revision, actionId: id, sessionId: room.sessionId, participantId: room.participantId, consentRevision: room.consentRevision, guideVersion: room.guideVersion, safetyRevision: room.safetyRevision, ...extra };
}

(async () => {
  const baseURL = await listen();
  const browser = await firefox.launch({ headless: true, executablePath: FIREFOX_PATH });
  try {
    // Server-side two-role outcome ownership and factual quiet end.
    const guide = { id: "ordinary", version: 1, title: "整理照片", summary: "把照片放回盒子；不想继续就停下。", source: "顾悦", rule: "现场可处理", level: "here", actorId: "caregiver", highRisk: false };
    const created = await api(baseURL, "/api/rooms", { method: "POST", body: { family: { caregiverName: "顾悦", relayName: "陈禾", recipientName: "赵姨", caregiverPhone: "13811112222", emergencyService: "911" }, stage: "quiet-handoff", duration: 30, consentRevision: 3, guide, searchGuides: [guide], redLines: ["无法唤醒"], safetyRevision: "caller-value-is-not-authoritative" } });
    assert(created.status === 201, "quiet room is created");
    const roomId = created.value.room.id;
    const caregiverToken = created.value.caregiverToken;
    let caregiverRoom = created.value.room;
    const joined = await api(baseURL, `/api/rooms/${roomId}/join`, { method: "POST", body: { inviteToken: created.value.invitation.token, phrase: created.value.invitation.phrase, expectedRelayName: "陈禾" } });
    assert(joined.status === 200, "substitute joins with restricted capability");
    const relayToken = joined.value.relayToken;
    let relayRoom = joined.value.room;
    const ack = { scopeAcknowledged: true, currentGuideAcknowledged: true, redLinesAcknowledged: true, contactsAcknowledged: true };
    let response = await api(baseURL, `/api/rooms/${roomId}/actions`, { method: "POST", token: relayToken, body: action(relayRoom, "relay.acknowledge", "relay-ack", ack) });
    relayRoom = response.value.room;
    caregiverRoom = (await api(baseURL, `/api/rooms/${roomId}`, { token: caregiverToken })).value.room;
    response = await api(baseURL, `/api/rooms/${roomId}/actions`, { method: "POST", token: caregiverToken, body: action(caregiverRoom, "caregiver.acknowledge", "caregiver-ack", ack) });
    caregiverRoom = response.value.room;
    response = await api(baseURL, `/api/rooms/${roomId}/actions`, { method: "POST", token: caregiverToken, body: action(caregiverRoom, "caregiver.start", "start") });
    caregiverRoom = response.value.room;
    assert(caregiverRoom.startSnapshot?.schemaVersion === 1 && caregiverRoom.startSnapshot.stage === "quiet-handoff" && caregiverRoom.startSnapshot.guideScope[0].source === "顾悦" && caregiverRoom.startSnapshot.participants.substitute.label === "陈禾", "server freezes the full versioned start snapshot");
    relayRoom = (await api(baseURL, `/api/rooms/${roomId}`, { token: relayToken })).value.room;
    response = await api(baseURL, `/api/rooms/${roomId}/actions`, { method: "POST", token: relayToken, body: action(relayRoom, "relay.note", "quiet-note", { text: "她整理完后坐在窗边。" }) });
    relayRoom = response.value.room;
    const protectedRead = (await api(baseURL, `/api/rooms/${roomId}`, { token: caregiverToken })).value.room;
    assert(protectedRead.quietCount === 1 && !JSON.stringify(protectedRead).includes("坐在窗边"), "quiet routine text is hidden while active");
    response = await api(baseURL, `/api/rooms/${roomId}/actions`, { method: "POST", token: relayToken, body: action(relayRoom, "relay.contact-opened", "contact-open", { target: "caregiver" }) });
    relayRoom = response.value.room;
    for (let index = 0; index < 3; index += 1) {
      response = await api(baseURL, `/api/rooms/${roomId}/actions`, { method: "POST", token: relayToken, body: action(relayRoom, "relay.task", `task-${index}`, { index }) });
      relayRoom = response.value.room;
    }
    caregiverRoom = (await api(baseURL, `/api/rooms/${roomId}`, { token: caregiverToken })).value.room;
    const internal = rooms.get(roomId);
    internal.relayLastSeenAt = Date.now() - 10_000;
    const endBody = action(caregiverRoom, "caregiver.end", "end-once", { caregiverNote: "" });
    const ended = await api(baseURL, `/api/rooms/${roomId}/actions`, { method: "POST", token: caregiverToken, body: endBody });
    assert(ended.status === 200 && ended.value.room.summary.status === "disconnected", "a stale relay connection is represented as disconnected, not completed");
    assert(ended.value.room.summary.facts.contactActionsOpened[0].label.includes("不代表通话接通"), "opened contact is never called proof of connection");
    assert(JSON.stringify(ended.value.room).includes("坐在窗边"), "quiet text is released for review only after end");
    const replayedEnd = await api(baseURL, `/api/rooms/${roomId}/actions`, { method: "POST", token: caregiverToken, body: endBody });
    assert(replayedEnd.status === 409 && replayedEnd.value.error.code === "replayed_action", "replayed factual completion is rejected");

    relayRoom = (await api(baseURL, `/api/rooms/${roomId}`, { token: relayToken })).value.room;
    const relayWritesCaregiver = await api(baseURL, `/api/rooms/${roomId}/actions`, { method: "POST", token: relayToken, body: action(relayRoom, "caregiver.checkin", "wrong-role-caregiver", { response: { partial: true } }) });
    assert(relayWritesCaregiver.status === 403, "relay capability cannot write caregiver answers");
    const relayCheckIn = await api(baseURL, `/api/rooms/${roomId}/actions`, { method: "POST", token: relayToken, body: action(relayRoom, "relay.checkin", "relay-checkin", { response: { ableToHandle: "partly", uncertainStep: "断线后如何收尾", contactedCaregiver: "yes", feltUnsafe: false, choice: "repeat", notes: "", partial: false } }) });
    assert(relayCheckIn.status === 200 && relayCheckIn.value.room.checkIns.substitute.respondentId.startsWith("relay-") && relayCheckIn.value.room.checkIns.caregiver === null, "server attributes substitute self-report separately");
    caregiverRoom = (await api(baseURL, `/api/rooms/${roomId}`, { token: caregiverToken })).value.room;
    const caregiverWritesRelay = await api(baseURL, `/api/rooms/${roomId}/actions`, { method: "POST", token: caregiverToken, body: action(caregiverRoom, "relay.checkin", "wrong-role-relay", { response: { partial: true } }) });
    assert(caregiverWritesRelay.status === 403, "caregiver capability cannot write substitute answers");
    const caregiverCheckIn = await api(baseURL, `/api/rooms/${roomId}/actions`, { method: "POST", token: caregiverToken, body: action(caregiverRoom, "caregiver.checkin", "caregiver-checkin", { response: { restHappened: "partly", phoneChecks: "3-5", nonurgentInterrupted: "yes", confidence: 2, feltUnsafe: false, choice: "repeat", notes: "", partial: false } }) });
    assert(caregiverCheckIn.status === 200 && caregiverCheckIn.value.room.checkIns.caregiver.respondentId.startsWith("caregiver-") && caregiverCheckIn.value.room.checkIns.substitute.respondentId.startsWith("relay-"), "server snapshot keeps both attributions distinct");

    // A delayed poll response must never roll the substitute UI back from the
    // shared final state to an older debrief revision.
    const raceContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await raceContext.addInitScript(({ raceRoomId, token, participantId, sessionId }) => {
      window.__relayRevisionTrace = [];
      const originalSetItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function setItemWithRevisionTrace(key, value) {
        if (key === `relay-companion-safe-snapshot:${raceRoomId}`) {
          try {
            const snapshot = JSON.parse(value);
            window.__relayRevisionTrace.push({ revision: Number(snapshot.revision), status: snapshot.status });
          } catch { /* Production storage validation remains authoritative. */ }
        }
        return originalSetItem.call(this, key, value);
      };
      localStorage.setItem(`relay-companion-credential:${raceRoomId}`, JSON.stringify({
        token,
        participantId,
        sessionId,
        policyVersion: window.RelaySafetyPolicy?.VERSION,
      }));
    }, {
      raceRoomId: roomId,
      token: relayToken,
      participantId: joined.value.participantId,
      sessionId: joined.value.sessionId,
    });
    const racePage = await raceContext.newPage();
    await racePage.goto(`${baseURL}/join.html?room=${encodeURIComponent(roomId)}`, { waitUntil: "networkidle" });
    await racePage.getByRole("heading", { name: /现场事实已同步/ }).waitFor();
    let staleCapturedResolve;
    let releaseStaleResolve;
    const staleCaptured = new Promise((resolve) => { staleCapturedResolve = resolve; });
    const releaseStale = new Promise((resolve) => { releaseStaleResolve = resolve; });
    await racePage.route(`**/api/rooms/${roomId}`, async (route) => {
      const response = await route.fetch();
      staleCapturedResolve();
      await releaseStale;
      await route.fulfill({ response });
    }, { times: 1 });
    await staleCaptured;
    caregiverRoom = (await api(baseURL, `/api/rooms/${roomId}`, { token: caregiverToken })).value.room;
    const finalizedRace = await api(baseURL, `/api/rooms/${roomId}/actions`, {
      method: "POST",
      token: caregiverToken,
      body: action(caregiverRoom, "caregiver.finalize", "finalize-poll-race", {
        outcome: "confirmed-guide",
        gap: "整理完成后想安静坐一会儿",
        instruction: "把盒子放回桌边，询问是否想安静休息十分钟。",
        sourceId: "caregiver",
        sourceLabel: "untrusted caller label",
      }),
    });
    assert(finalizedRace.status === 200 && finalizedRace.value.room.status === "ended", "race fixture reaches the shared final state");
    await racePage.waitForTimeout(1100);
    releaseStaleResolve();
    await racePage.waitForTimeout(250);
    await racePage.getByRole("heading", { name: /双机彩排已结束/ }).waitFor({ timeout: 5000 });
    const revisionTrace = await racePage.evaluate(() => window.__relayRevisionTrace);
    assert(
      revisionTrace.length >= 2
        && revisionTrace.at(-1).status === "ended"
        && revisionTrace.every((entry, index) => index === 0 || entry.revision >= revisionTrace[index - 1].revision),
      `delayed poll snapshots never roll substitute state backward (${JSON.stringify(revisionTrace)})`,
    );
    await raceContext.close();

    // A medical gap first disclosed after the factual end must be attached to
    // that same durable session and block otherwise unanimous extension.
    const medicalCreated = await api(baseURL, "/api/rooms", {
      method: "POST",
      body: {
        family: { caregiverName: "顾悦", relayName: "陈禾", recipientName: "赵姨", caregiverPhone: "13811112222", emergencyService: "911" },
        stage: "short-leave",
        duration: 20,
        consentRevision: 7,
        guide,
        searchGuides: [guide],
        redLines: ["无法唤醒"],
        safetyRevision: "medical-debrief-scope-v1",
      },
    });
    assert(medicalCreated.status === 201, "medical-debrief short-leave room is created");
    const medicalRoomId = medicalCreated.value.room.id;
    const medicalCaregiverToken = medicalCreated.value.caregiverToken;
    let medicalCaregiverRoom = medicalCreated.value.room;
    const medicalJoined = await api(baseURL, `/api/rooms/${medicalRoomId}/join`, {
      method: "POST",
      body: {
        inviteToken: medicalCreated.value.invitation.token,
        phrase: medicalCreated.value.invitation.phrase,
        expectedRelayName: "陈禾",
      },
    });
    const medicalRelayToken = medicalJoined.value.relayToken;
    let medicalRelayRoom = medicalJoined.value.room;
    response = await api(baseURL, `/api/rooms/${medicalRoomId}/actions`, {
      method: "POST",
      token: medicalRelayToken,
      body: action(medicalRelayRoom, "relay.acknowledge", "medical-relay-ack", ack),
    });
    medicalRelayRoom = response.value.room;
    medicalCaregiverRoom = (await api(baseURL, `/api/rooms/${medicalRoomId}`, { token: medicalCaregiverToken })).value.room;
    response = await api(baseURL, `/api/rooms/${medicalRoomId}/actions`, {
      method: "POST",
      token: medicalCaregiverToken,
      body: action(medicalCaregiverRoom, "caregiver.acknowledge", "medical-caregiver-ack", ack),
    });
    medicalCaregiverRoom = response.value.room;
    response = await api(baseURL, `/api/rooms/${medicalRoomId}/actions`, {
      method: "POST",
      token: medicalCaregiverToken,
      body: action(medicalCaregiverRoom, "caregiver.start", "medical-start"),
    });
    medicalCaregiverRoom = response.value.room;
    medicalRelayRoom = (await api(baseURL, `/api/rooms/${medicalRoomId}`, { token: medicalRelayToken })).value.room;
    for (let index = 0; index < 3; index += 1) {
      response = await api(baseURL, `/api/rooms/${medicalRoomId}/actions`, {
        method: "POST",
        token: medicalRelayToken,
        body: action(medicalRelayRoom, "relay.task", `medical-task-${index}`, { index }),
      });
      medicalRelayRoom = response.value.room;
    }
    medicalCaregiverRoom = (await api(baseURL, `/api/rooms/${medicalRoomId}`, { token: medicalCaregiverToken })).value.room;
    response = await api(baseURL, `/api/rooms/${medicalRoomId}/actions`, {
      method: "POST",
      token: medicalCaregiverToken,
      body: action(medicalCaregiverRoom, "caregiver.end", "medical-end", { caregiverNote: "" }),
    });
    assert(response.status === 200 && response.value.room.summary.status === "completed" && response.value.room.summary.facts.pendingGaps.length === 0, "short-leave completes before the post-end medical disclosure");
    medicalCaregiverRoom = response.value.room;
    response = await api(baseURL, `/api/rooms/${medicalRoomId}/actions`, {
      method: "POST",
      token: medicalCaregiverToken,
      body: action(medicalCaregiverRoom, "caregiver.checkin", "medical-caregiver-checkin", {
        response: { restHappened: "yes", phoneChecks: "0", nonurgentInterrupted: "no", confidence: 4, feltUnsafe: false, choice: "extend", notes: "", partial: false },
      }),
    });
    medicalCaregiverRoom = response.value.room;
    medicalRelayRoom = (await api(baseURL, `/api/rooms/${medicalRoomId}`, { token: medicalRelayToken })).value.room;
    response = await api(baseURL, `/api/rooms/${medicalRoomId}/actions`, {
      method: "POST",
      token: medicalRelayToken,
      body: action(medicalRelayRoom, "relay.checkin", "medical-relay-checkin", {
        response: { ableToHandle: "yes", uncertainStep: "没有", contactedCaregiver: "no", feltUnsafe: false, choice: "extend", notes: "", partial: false },
      }),
    });
    medicalCaregiverRoom = (await api(baseURL, `/api/rooms/${medicalRoomId}`, { token: medicalCaregiverToken })).value.room;
    const medicalFinalized = await api(baseURL, `/api/rooms/${medicalRoomId}/actions`, {
      method: "POST",
      token: medicalCaregiverToken,
      body: action(medicalCaregiverRoom, "caregiver.finalize", "medical-finalize", {
        outcome: "pending-gap",
        gap: "她刚才胸口发紧",
        instruction: "",
        sourceId: "",
        sourceLabel: "",
      }),
    });
    const medicalFinalRoom = medicalFinalized.value.room;
    assert(
      medicalFinalized.status === 200
        && medicalFinalRoom.pendingGaps[0]?.risk === "medical"
        && medicalFinalRoom.summary.debrief?.risk === "medical"
        && medicalFinalRoom.summary.facts.pendingGaps.some((gap) => gap.risk === "medical" && gap.status === "pending"),
      "post-end medical debrief is copied into the immutable session facts",
    );
    const medicalSession = OutcomeModel.createSession({
      id: medicalFinalRoom.sessionId,
      stage: medicalFinalRoom.startSnapshot.stage,
      plannedDurationMinutes: medicalFinalRoom.startSnapshot.plannedDurationMinutes,
      consentRevision: medicalFinalRoom.startSnapshot.consentRevision,
      guideScope: medicalFinalRoom.startSnapshot.guideScope,
      redLines: medicalFinalRoom.startSnapshot.redLines,
      participants: medicalFinalRoom.startSnapshot.participants,
      mode: "two-device",
      startedAt: medicalFinalRoom.startSnapshot.startedAt,
      safetyRevision: medicalFinalRoom.startSnapshot.safetyRevision,
      policyVersion: medicalFinalRoom.startSnapshot.policyVersion,
      status: medicalFinalRoom.summary.status,
      facts: medicalFinalRoom.summary.facts,
      checkIns: medicalFinalRoom.checkIns,
    });
    const medicalRecommendation = OutcomeModel.recommendation([medicalSession], {
      consentRevision: medicalFinalRoom.consentRevision,
      guides: medicalFinalRoom.startSnapshot.guideScope.map((item) => ({ id: item.id, version: item.version })),
    });
    assert(
      medicalRecommendation.decision === "medical-hold"
        && medicalRecommendation.stage === "short-leave"
        && medicalRecommendation.canExtend === false,
      "post-end medical debrief blocks unanimous extension to quiet handoff",
    );

    // Visible demo evidence, source-separated history, mobile check-in, and sanitized report.
    const context = await browser.newContext({ viewport: { width: 1365, height: 900 } });
    const page = await context.newPage();
    await page.goto(baseURL, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: /体验演示家庭/ }).click();
    const home = await page.locator("#app").innerText();
    assert(home.includes("实际完成的离班分钟") && home.includes("完成全部步骤的独立交接") && home.includes("建议下一次") && !/72%|82%|准备度/.test(home), "home uses truthful household metrics and reasons without readiness percentages");
    await page.getByRole("button", { name: "查看全部记录" }).click();
    assert(await page.locator(".outcome-history-list > button").count() >= 4 && (await page.locator("#modal-root").innerText()).includes("应用记录") && (await page.locator("#modal-root").innerText()).includes("参与者自报"), "demo exposes several explicitly sourced outcome records");
    await page.locator("#modal-root .modal").screenshot({ path: "artifacts/outcome-history-desktop.png" });
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.locator(".outcome-history-list > button").first().isVisible() && await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), "history remains readable without narrow overflow");
    await page.waitForTimeout(3000);
    await page.screenshot({ path: "artifacts/outcome-history-mobile.png", fullPage: false });
    await page.setViewportSize({ width: 1365, height: 900 });
    await page.locator(".outcome-history-list > button").first().click();
    assert(await page.locator(".app-record-detail").isVisible() && await page.locator(".self-report-detail").count() === 3, "session detail separates app facts from all self-report roles");
    await page.getByRole("button", { name: /照护者补充/ }).click();
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.locator("#outcome-rest").isVisible() && await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), "fatigued-user check-in remains completable without narrow overflow");
    await page.waitForTimeout(3000);
    await page.screenshot({ path: "artifacts/outcome-checkin-mobile.png", fullPage: false });
    await page.getByRole("button", { name: "稍后再填" }).click();
    await page.setViewportSize({ width: 1365, height: 900 });
    await page.evaluate((key) => {
      const state = JSON.parse(localStorage.getItem(key));
      state.family.emergencyService = "RAW-EMERGENCY-98765";
      state.sessions.at(-1).checkIns.caregiver.notes = "SENSITIVE-NOTE-MUST-BE-OPT-IN";
      localStorage.setItem("relay-rehearsal-companion-v1", JSON.stringify({ invitation: { token: "SECRET-INVITE-CAPABILITY" } }));
      localStorage.setItem(key, JSON.stringify(state));
    }, STORAGE_KEY);
    await page.reload({ waitUntil: "networkidle" });
    await page.getByRole("button", { name: "导出 / 打印" }).click();
    let preview = await page.locator("#family-report-preview").innerText();
    assert(!preview.includes("RAW-EMERGENCY-98765") && !preview.includes("SECRET-INVITE-CAPABILITY") && !preview.includes("SENSITIVE-NOTE-MUST-BE-OPT-IN") && preview.includes("照护者自报"), "default report excludes raw emergency number, capabilities, and sensitive notes while labeling self-report");
    await page.locator("#include-sensitive-notes").check();
    preview = await page.locator("#family-report-preview").innerText();
    assert(preview.includes("SENSITIVE-NOTE-MUST-BE-OPT-IN"), "caregiver can explicitly include sensitive session notes");
    await page.screenshot({ path: "artifacts/family-review-desktop.png", fullPage: false });
    await context.close();

    // Legacy booleans become a prompt for a new measurement, never metrics.
    const legacyContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await legacyContext.addInitScript((key) => localStorage.setItem(key, JSON.stringify({ schemaVersion: 6, mode: "real", stageOneCompleted: true, rehearsalCompleted: true, family: { caregiverName: "旧照护者", caregiverPhone: "1", recipientName: "旧本人", recipientConsented: true, relayName: "旧替班者", emergencyContactName: "联系人", emergencyContactPhone: "2", emergencyService: "3", redLines: [], restGoal: { title: "休息", date: "以后", duration: 20 } }, recipientConsent: { status: "granted", revision: 1 }, guides: [], activity: [{ title: "旧完成", note: "无需处理", score: "82%" }] })), STORAGE_KEY);
    const legacyPage = await legacyContext.newPage();
    await legacyPage.goto(baseURL, { waitUntil: "networkidle" });
    const legacyState = await legacyPage.evaluate((key) => JSON.parse(localStorage.getItem(key)), STORAGE_KEY);
    assert(legacyState.schemaVersion === 7 && legacyState.sessions.length === 2 && legacyState.sessions.every((record) => record.status === "legacy" && record.facts === null) && !legacyState.stageOneCompleted && !legacyState.rehearsalCompleted, "legacy completion migrates without fabricated outcomes or progression");
    assert(legacyState.activity.every((item) => item.note.includes("详细结果未记录") && !item.note.includes("无需处理")), "legacy activity claims are relabeled instead of becoming metrics");
    await legacyContext.close();

    console.log("Outcome E2E passed: two-role factual end, monotonic delayed-poll sync, post-end medical progression hold, quiet protection, disconnect/replay, role attribution, evidence UI, responsive history/check-in, sanitized report, and honest migration");
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
})().catch((error) => {
  try { server.closeAllConnections?.(); } catch { /* best effort */ }
  try { server.close(); } catch { /* may already be closed */ }
  console.error(error.stack || error);
  process.exit(1);
});
