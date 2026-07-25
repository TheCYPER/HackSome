"use strict";

const assert = require("node:assert/strict");
const { firefox } = require("/usr/local/lib/python3.12/dist-packages/playwright/driver/package");
const { server } = require("../server");

const FIREFOX_PATH = "/home/kasm-user/.cache/ms-playwright/firefox-1509/firefox/firefox";
const STORAGE_KEY = "relay-rehearsal-demo-v1";
const AUTHORITY_KEY = "relay-rehearsal-consent-authority-v1";
const COMPANION_KEY = "relay-rehearsal-companion-v1";
const COMPANION_REVOCATION_KEY = "relay-rehearsal-companion-revocation-v1";
const PASSPHRASE = "household backup password";

async function listen() {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return `http://127.0.0.1:${server.address().port}`;
}

async function seedRealHousehold(page, { caregiverName = "备份前照护者", authorityStatus = "granted", authorityRevision = 4, withSession = true, withActive = false } = {}) {
  await page.evaluate(([stateKey, authorityKey, values]) => {
    const state = JSON.parse(localStorage.getItem(stateKey));
    state.mode = "real";
    state.meta = { updatedAt: Date.now() };
    state.onboarding = { status: "complete", step: 6, consentDecision: values.authorityStatus, redLinesReviewedAt: new Date().toISOString() };
    state.family = {
      caregiverName: values.caregiverName,
      caregiverPhone: "13800138000",
      recipientName: "林禾",
      recipientConsented: values.authorityStatus === "granted",
      relayName: "周宁",
      emergencyContactName: "陈平",
      emergencyContactPhone: "13900139000",
      emergencyService: "999",
      redLines: ["无法唤醒"],
      restGoal: { title: "独自散步", date: "周六下午", duration: 20 },
      inviteToken: "nested-invite-capability",
      nestedRemote: { caregiverToken: "nested-caregiver-capability", note: "保留普通家庭备注" },
    };
    state.recipientConsent = {
      status: values.authorityStatus,
      revision: values.authorityRevision,
      grantedAt: values.authorityStatus === "granted" ? new Date().toISOString() : null,
      withdrawnAt: values.authorityStatus === "withdrawn" ? new Date().toISOString() : null,
    };
    state.confirmations = [{
      id: "recovery-guide-confirmation",
      type: "guide",
      status: "current",
      actorId: "caregiver-fixed-v1",
      guideId: "recovery-ordinary-guide",
      confirmedAt: "2026-07-24T07:55:00.000Z",
    }];
    state.guides = [{
      id: "recovery-ordinary-guide",
      version: 1,
      status: "usable",
      confirmationId: "recovery-guide-confirmation",
      provenance: { actorId: "caregiver", actorType: "caregiver", labelAtConfirmation: values.caregiverName },
      title: "想暂停整理照片",
      summary: "先停下来，把照片放回桌上。",
      source: values.caregiverName,
      level: "here",
      rule: "现场可处理",
      category: "daily",
      highRisk: false,
    }];
    state.sessions = [];
    state.activeRest = null;
    state.activeRehearsal = null;
    if (values.withSession) {
      const measured = window.RelayOutcomeModel.createSession({
        id: "recovery-existing-session",
        stage: "observe",
        plannedDurationMinutes: 5,
        consentRevision: values.authorityRevision,
        guideScope: [{ id: "recovery-ordinary-guide", version: 1 }],
        redLines: [],
        participants: {},
        mode: "single-device",
        startedAt: "2026-07-24T08:00:00.000Z",
        safetyRevision: null,
        policyVersion: window.RelaySafetyPolicy.VERSION,
      });
      state.sessions.push(window.RelayOutcomeModel.endSession(measured, {
        status: "interrupted",
        endedAt: "2026-07-24T08:04:00.000Z",
        actualElapsedSeconds: 240,
        completedSteps: [true, false, false],
        routineUpdatesQueued: 0,
        pendingGaps: [],
        urgentAlertsRaised: 0,
        contactActionsOpened: [],
      }));
    }
    if (values.withActive) {
      state.confirmations.push({
        id: "recovery-session-confirmation",
        type: "rehearsal",
        status: "current",
        actorId: "caregiver-fixed-v1",
        consentRevision: values.authorityRevision,
        confirmedAt: new Date().toISOString(),
      });
      state.sessions.push(window.RelayOutcomeModel.createSession({
        id: "recovery-active-session",
        stage: "observe",
        plannedDurationMinutes: 5,
        consentRevision: values.authorityRevision,
        guideScope: [{ id: "recovery-ordinary-guide", version: 1 }],
        redLines: [],
        participants: {},
        mode: "single-device",
        startedAt: new Date(Date.now() - 30_000).toISOString(),
        safetyRevision: null,
        policyVersion: window.RelaySafetyPolicy.VERSION,
      }));
      state.activeRehearsal = {
        sessionRecordId: "recovery-active-session",
        stage: "observe",
        guideId: "recovery-ordinary-guide",
        guideVersion: 1,
        consentRevision: values.authorityRevision,
        confirmationId: "recovery-session-confirmation",
        tasks: [true, false, false],
        pendingGapIds: [],
        urgentAlertsRaised: 0,
      };
    }
    state.activity = [];
    state.gaps = [];
    state.debriefs = [];
    state.revokedGuideIds = [];
    localStorage.setItem(stateKey, JSON.stringify(state));
    const changedAt = new Date().toISOString();
    localStorage.setItem(authorityKey, JSON.stringify({
      schemaVersion: 1,
      status: values.authorityStatus,
      revision: values.authorityRevision,
      changedAt,
      grantedAt: values.authorityStatus === "granted" ? changedAt : null,
      withdrawnAt: values.authorityStatus === "withdrawn" ? changedAt : null,
    }));
  }, [STORAGE_KEY, AUTHORITY_KEY, { caregiverName, authorityStatus, authorityRevision, withSession, withActive }]);
  await page.reload({ waitUntil: "networkidle" });
  await page.locator(".top-avatar").waitFor();
}

async function stored(page) {
  return page.evaluate((key) => JSON.parse(localStorage.getItem(key)), STORAGE_KEY);
}

async function authority(page) {
  return page.evaluate((key) => JSON.parse(localStorage.getItem(key)), AUTHORITY_KEY);
}

async function openCreateBackup(page) {
  await page.locator(".top-avatar").click();
  await page.getByRole("button", { name: /创建加密备份/ }).click();
  await page.locator("#backup-form").waitFor();
}

async function createBackup(page) {
  await openCreateBackup(page);
  const backupSecret = page.locator("#backup-passphrase");
  assert.equal(await backupSecret.getAttribute("type"), "password", "backup passphrase starts hidden");
  await page.getByRole("button", { name: "显示" }).first().click();
  assert.equal(await backupSecret.getAttribute("type"), "text", "backup passphrase offers an explicit show control");
  await page.getByRole("button", { name: "隐藏" }).first().click();
  await page.locator("#backup-passphrase").fill(PASSPHRASE);
  await page.locator("#backup-passphrase-confirm").fill(PASSPHRASE);
  await page.locator("#backup-form input[name='understands']").check();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "加密并下载" }).click(),
  ]);
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  return Buffer.concat(chunks);
}

async function openRestore(page, backup, password = PASSPHRASE) {
  if (await page.locator("#modal-root .modal").count()) await page.getByRole("button", { name: "关闭" }).click();
  if ((await stored(page)).mode === null) {
    await page.getByRole("button", { name: /恢复加密备份/ }).click();
  } else {
    await page.locator(".top-avatar").click();
    await page.getByRole("button", { name: /恢复备份/ }).click();
  }
  await page.locator("#recovery-file").setInputFiles({
    name: "family.relaybackup.json",
    mimeType: "application/json",
    buffer: backup,
  });
  const restoreSecret = page.locator("#recovery-passphrase");
  assert.equal(await restoreSecret.getAttribute("type"), "password", "restore passphrase starts hidden");
  await page.getByRole("button", { name: "显示" }).click();
  assert.equal(await restoreSecret.getAttribute("type"), "text", "restore passphrase offers an explicit show control");
  await page.getByRole("button", { name: "隐藏" }).click();
  await page.locator("#recovery-passphrase").fill(password);
  await page.locator("#restore-form input[name='overwriteUnderstood']").check();
  await page.getByRole("button", { name: "本地解密并检查" }).click();
}

async function confirmRestore(page) {
  await page.getByRole("heading", { name: /完整覆盖这台设备上的家庭/ }).waitFor();
  await page.locator("#final-recovery-confirm").check();
  await page.getByRole("button", { name: "确认覆盖并恢复" }).click();
}

(async () => {
  const origin = await listen();
  const browser = await firefox.launch({ headless: true, executablePath: FIREFOX_PATH });
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, acceptDownloads: true });
    const page = await context.newPage();
    await page.goto(origin, { waitUntil: "networkidle" });
    await seedRealHousehold(page);
    assert(await page.getByText("还没有为这个真实家庭创建加密备份").isVisible(), "real households receive a visible backup reminder");
    await seedRealHousehold(page, { withActive: true });
    assert.equal((await authority(page)).status, "granted", "active-backup fixture retains granted authority");
    assert.equal((await stored(page)).recipientConsent.status, "granted", "active-backup fixture retains granted state consent");
    assert.equal((await stored(page)).sessions.find((record) => record.id === "recovery-active-session")?.status, "active", "active-backup fixture starts with an active record");
    assert.deepEqual((await stored(page)).revokedGuideIds, [], "active-backup fixture starts without revoked guides");
    await page.evaluate(() => {
      const original = window.fetch.bind(window);
      window.__recoveryFetches = [];
      window.fetch = (...args) => {
        window.__recoveryFetches.push(String(args[0]));
        return original(...args);
      };
    });

    const backup = await createBackup(page);
    const envelope = JSON.parse(backup.toString("utf8"));
    assert.equal(envelope.format, "relay-rehearsal-encrypted-backup", "download is a dedicated versioned recovery envelope");
    assert.equal(envelope.version, 2, "browser backup uses the metadata-minimal v2 envelope");
    assert.equal(envelope.appBuild, undefined, "clear browser envelope contains no deployment metadata");
    assert.equal(envelope.kdf.name, "PBKDF2", "browser backup declares PBKDF2");
    assert.equal(envelope.cipher.name, "AES-GCM", "browser backup declares AES-GCM");
    assert(!backup.toString("utf8").includes("备份前照护者") && !backup.toString("utf8").includes("13800138000"), "download contains no household plaintext");
    assert((await stored(page)).meta.lastBackupAt, "successful download records the backup reminder timestamp");
    assert.equal((await authority(page)).status, "granted", "backup does not change the authority record");
    assert.equal((await stored(page)).recipientConsent.status, "granted", "backup does not change state consent");
    assert.deepEqual((await stored(page)).revokedGuideIds, [], "backup does not revoke guide scope");
    assert.equal((await stored(page)).activeRehearsal, null, "successful backup closes the live active rehearsal");
    assert.equal((await stored(page)).sessions.find((record) => record.id === "recovery-active-session")?.status, "interrupted", "successful backup conservatively persists the live session as interrupted");
    assert.equal(await page.getByText("还没有为这个真实家庭创建加密备份").count(), 0, "fresh backup clears the reminder");
    assert.deepEqual(await page.evaluate(() => window.__recoveryFetches), [], "backup makes zero window network requests");

    await page.evaluate((key) => {
      const state = JSON.parse(localStorage.getItem(key));
      state.family.caregiverName = "恢复前临时名字";
      state.meta.updatedAt = Date.now();
      localStorage.setItem(key, JSON.stringify(state));
    }, STORAGE_KEY);
    await page.reload({ waitUntil: "networkidle" });
    await page.evaluate(() => {
      const original = window.fetch.bind(window);
      window.__recoveryFetches = [];
      window.fetch = (...args) => {
        window.__recoveryFetches.push(String(args[0]));
        return original(...args);
      };
    });
    await openRestore(page, backup, "definitely wrong password");
    await page.getByText("密码错误，或备份已被篡改").waitFor();
    assert.equal((await stored(page)).family.caregiverName, "恢复前临时名字", "wrong password leaves the current household untouched");

    await page.locator("#recovery-file").setInputFiles({
      name: "human-review.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify({ schemaVersion: 1, reportType: "接班彩排家庭复盘（本地生成）", metrics: {}, recommendation: {} })),
    });
    await page.locator("#recovery-passphrase").fill(PASSPHRASE);
    await page.getByRole("button", { name: "本地解密并检查" }).click();
    await page.getByText("这是家庭复盘，不是加密恢复备份").waitFor();
    assert.equal((await stored(page)).family.caregiverName, "恢复前临时名字", "review export rejection leaves the current household untouched");

    await page.evaluate(([companionKey, revocationKey]) => {
      localStorage.setItem(companionKey, JSON.stringify({ roomId: "old-room", caregiverToken: "old-capability" }));
      localStorage.setItem(revocationKey, JSON.stringify({ roomId: "old-room", caregiverToken: "revocation-capability" }));
    }, [COMPANION_KEY, COMPANION_REVOCATION_KEY]);
    await page.locator("#recovery-file").setInputFiles({
      name: "family.relaybackup.json",
      mimeType: "application/json",
      buffer: backup,
    });
    await page.locator("#recovery-passphrase").fill(PASSPHRASE);
    await page.getByRole("button", { name: "本地解密并检查" }).click();
    await confirmRestore(page);
    const restored = await stored(page);
    assert.equal(restored.family.caregiverName, "备份前照护者", "correct password restores the encrypted household");
    assert.deepEqual(Object.keys(restored.meta.lastRecovery).sort(), ["date", "result", "version"], "restore audit persists only version/date/result");
    assert.equal(restored.meta.lastRecovery.result, "restored", "restore writes a minimal successful audit marker");
    assert.equal(restored.activeRest, null, "restore never resumes active rest");
    assert.equal(restored.activeRehearsal, null, "restore never resumes active rehearsal");
    assert.equal(restored.family.inviteToken, undefined, "restored household contains no nested invite token");
    assert.equal(restored.family.nestedRemote.caregiverToken, undefined, "restored household contains no nested caregiver capability");
    assert.equal(restored.family.nestedRemote.note, "保留普通家庭备注", "recursive credential stripping preserves ordinary nested household content");
    assert.equal(await page.evaluate((key) => localStorage.getItem(key), COMPANION_KEY), null, "restore clears the current companion capability");
    assert.equal(await page.evaluate((key) => localStorage.getItem(key), COMPANION_REVOCATION_KEY), null, "restore clears the companion revocation capability");
    assert.deepEqual(await page.evaluate(() => window.__recoveryFetches), [], "backup and recovery make zero window network requests");
    await context.close();

    const clean = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const cleanPage = await clean.newPage();
    await cleanPage.goto(origin, { waitUntil: "networkidle" });
    await openRestore(cleanPage, backup);
    await confirmRestore(cleanPage);
    const cleanState = await stored(cleanPage);
    const cleanAuthority = await authority(cleanPage);
    assert.equal(cleanAuthority.status, "withdrawn", "clean-device restore does not revive backed-up consent");
    assert.equal(cleanState.family.recipientConsented, false, "clean-device restore keeps recipient participation gated");
    await cleanPage.locator(".top-avatar").click();
    assert(await cleanPage.getByRole("button", { name: "请本人当面确认" }).isVisible(), "clean-device recovery exposes the in-person re-consent gate");
    assert(await cleanPage.getByText(/恢复审计/).isVisible(), "settings expose the minimal restore audit marker");
    await clean.close();

    const stale = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const stalePage = await stale.newPage();
    await stalePage.goto(origin, { waitUntil: "networkidle" });
    await seedRealHousehold(stalePage, { caregiverName: "当前撤回家庭", authorityStatus: "withdrawn", authorityRevision: 20 });
    await openRestore(stalePage, backup);
    await confirmRestore(stalePage);
    const staleAuthority = await authority(stalePage);
    assert.equal(staleAuthority.status, "withdrawn", "a backup grant cannot overwrite a current withdrawal");
    assert(staleAuthority.revision >= 20, "stale-withdrawal protection is monotonic");
    await stale.close();

    const atomic = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const atomicPage = await atomic.newPage();
    await atomicPage.goto(origin, { waitUntil: "networkidle" });
    await seedRealHousehold(atomicPage, { caregiverName: "必须原样保留" });
    await openRestore(atomicPage, backup);
    await atomicPage.getByRole("heading", { name: /完整覆盖这台设备上的家庭/ }).waitFor();
    await atomicPage.locator("#final-recovery-confirm").check();
    await atomicPage.evaluate((authorityKey) => {
      const original = Storage.prototype.setItem;
      window.__originalStorageSetItem = original;
      let failed = false;
      Storage.prototype.setItem = function patchedSetItem(key, value) {
        if (!failed && key === authorityKey) {
          failed = true;
          throw new DOMException("simulated quota failure", "QuotaExceededError");
        }
        return original.call(this, key, value);
      };
    }, AUTHORITY_KEY);
    await atomicPage.getByRole("button", { name: "确认覆盖并恢复" }).click();
    await atomicPage.getByText("浏览器未能完整写入；已保留恢复前的家庭").waitFor();
    await atomicPage.evaluate(() => { Storage.prototype.setItem = window.__originalStorageSetItem; });
    assert.equal((await stored(atomicPage)).family.caregiverName, "必须原样保留", "failed multi-key commit rolls back the complete household");
    assert.equal((await stored(atomicPage)).meta.lastRecovery, undefined, "failed commit writes no restore audit marker");
    await atomic.close();

    const policy = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const policyPage = await policy.newPage();
    await policyPage.goto(origin, { waitUntil: "networkidle" });
    await seedRealHousehold(policyPage, { caregiverName: "策略复核家庭" });
    const adversarialBackupText = await policyPage.evaluate(async ([stateKey, authorityKey, secret]) => {
      const state = JSON.parse(localStorage.getItem(stateKey));
      state.guides.push({
        id: "unsafe-restored-guide",
        version: 1,
        status: "usable",
        confirmationId: "unsafe-confirmation",
        provenance: { actorId: "caregiver", actorType: "caregiver", labelAtConfirmation: "策略复核家庭" },
        title: "胸口发紧",
        summary: "先在家等一会儿",
        source: "策略复核家庭",
        level: "here",
        rule: "现场可处理",
      });
      state.confirmations.push({ id: "unsafe-confirmation", type: "guide", status: "current", actorId: "caregiver", guideId: "unsafe-restored-guide" });
      state.sessions.push({
        id: "malicious-invalid-stage",
        status: "completed",
        startSnapshot: { stage: "invented-stage", consentRevision: 4 },
        facts: {},
        checkIns: {},
      });
      state.gaps.push({
        id: "forged-chest-gap",
        query: "她突然胸痛，应该怎么办",
        normalizedQuery: "她突然胸痛应该怎么办",
        status: "resolved",
        risk: "ordinary",
        encounters: 1,
        createdAt: Date.now() - 2_000,
        lastSeenAt: Date.now() - 1_000,
      });
      state.sessions.push(window.RelayOutcomeModel.createSession({
        id: "forged-obsolete-policy-session",
        stage: "observe",
        plannedDurationMinutes: 5,
        consentRevision: 4,
        guideScope: [{ id: "recovery-ordinary-guide", version: 1 }],
        redLines: [],
        participants: {},
        mode: "single-device",
        startedAt: "2026-07-25T08:00:00.000Z",
        safetyRevision: null,
        policyVersion: "obsolete-policy",
        status: "completed",
        facts: {
          recordedAt: "2026-07-25T08:05:00.000Z",
          endedAt: "2026-07-25T08:05:00.000Z",
          actualElapsedSeconds: 300,
          completedSteps: [true, true, true],
          routineUpdatesQueued: 0,
          pendingGaps: [{ id: "forged-chest-gap", risk: "ordinary", status: "resolved" }],
          urgentAlertsRaised: 0,
          contactActionsOpened: [],
        },
        checkIns: {
          caregiver: { submittedAt: "2026-07-25T08:06:00.000Z", restHappened: "yes", phoneChecks: "0", nonurgentInterrupted: "no", confidence: 4, feltUnsafe: false, choice: "extend", partial: false },
          substitute: { submittedAt: "2026-07-25T08:06:30.000Z", ableToHandle: "yes", uncertainStep: "没有", contactedCaregiver: "no", feltUnsafe: false, choice: "extend", partial: false },
          careRecipient: { submittedAt: "2026-07-25T08:07:00.000Z", response: "not-asked", partial: true },
        },
      }));
      return window.RelayRecovery.createEncryptedBackup({
        state,
        authority: JSON.parse(localStorage.getItem(authorityKey)),
        passphrase: secret,
        now: new Date().toISOString(),
      });
    }, [STORAGE_KEY, AUTHORITY_KEY, PASSPHRASE]);
    const adversarialBackup = Buffer.from(adversarialBackupText, "utf8");
    await policyPage.setViewportSize({ width: 320, height: 720 });
    await openRestore(policyPage, adversarialBackup);
    await policyPage.getByRole("heading", { name: /完整覆盖这台设备上的家庭/ }).waitFor({ timeout: 60_000 });
    assert(await policyPage.getByText(/原本可用的指导在当前策略/).isVisible(), "confirmation discloses current-policy guide downgrades before overwrite");
    assert(await policyPage.getByText("来源格式").isVisible() && await policyPage.getByText(/加密恢复 · v2/).isVisible(), "preview identifies the source recovery format");
    assert(await policyPage.getByText("备份日期").isVisible(), "preview identifies the backup date");
    assert(await policyPage.getByText("最近一次历史").isVisible(), "preview identifies the latest restored session date");
    assert(await policyPage.getByText("覆盖时会保守重置").isVisible(), "preview explains the reset summary");
    assert(await policyPage.getByRole("button", { name: "先备份当前家庭" }).isVisible(), "preview offers a fresh backup of the current household before overwrite");
    const previewOverflow = await policyPage.evaluate(() => {
      const modal = document.querySelector(".recovery-modal");
      const rect = modal.getBoundingClientRect();
      return {
        documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        modalLeft: rect.left,
        modalRight: rect.right - innerWidth,
        modalScrollOverflow: modal.scrollWidth - modal.clientWidth,
      };
    });
    assert(previewOverflow.documentOverflow <= 0 && previewOverflow.modalLeft >= 0 && previewOverflow.modalRight <= 0 && previewOverflow.modalScrollOverflow <= 0, `320px recovery preview has no horizontal overflow: ${JSON.stringify(previewOverflow)}`);
    await confirmRestore(policyPage);
    const policyState = await stored(policyPage);
    assert.equal(policyState.guides.find((guide) => guide.id === "unsafe-restored-guide")?.status, "needs-review", "restore reclassifies unsafe household guidance through the current policy");
    assert(!policyState.sessions.some((record) => record.id === "malicious-invalid-stage"), "restore drops outcome records that fail current outcome-model validation");
    assert.equal(policyState.gaps.find((gap) => gap.id === "forged-chest-gap")?.risk, "medical", "restore reclassifies a forged chest-pain gap with the current policy");
    assert.equal(policyState.gaps.find((gap) => gap.id === "forged-chest-gap")?.status, "pending", "current medical classification reopens a forged resolved gap");
    assert(policyState.sessions.find((record) => record.id === "forged-obsolete-policy-session")?.facts.pendingGaps.some((gap) => gap.id === "forged-chest-gap" && gap.risk === "medical" && gap.status === "pending"), "restored session facts reconcile to the current gap classification");
    const restoredDecision = await policyPage.evaluate(([stateKey, policyVersion]) => {
      const restored = JSON.parse(localStorage.getItem(stateKey));
      return window.RelayOutcomeModel.recommendation(restored.sessions, {
        consentRevision: restored.recipientConsent.revision,
        guides: restored.guides.filter((guide) => guide.status === "usable").map((guide) => ({ id: guide.id, version: guide.version })),
        policyVersion,
      }).decision;
    }, [STORAGE_KEY, await policyPage.evaluate(() => window.RelaySafetyPolicy.VERSION)]);
    assert.notEqual(restoredDecision, "extend", "obsolete session policy plus current medical gap can never extend the restored recommendation");
    await policy.close();

    const zero = await browser.newContext({ viewport: { width: 320, height: 720 } });
    const zeroPage = await zero.newPage();
    await zeroPage.goto(origin, { waitUntil: "networkidle" });
    await seedRealHousehold(zeroPage, { caregiverName: "零记录家庭", withSession: false });
    assert.equal(await zeroPage.locator(".backup-reminder").count(), 0, "a zero-session real household is not nagged immediately");
    await zeroPage.locator(".top-avatar").click();
    assert(await zeroPage.getByRole("button", { name: /创建加密备份/ }).isVisible(), "zero-session household can still choose backup from settings");
    await zero.close();

    const snooze = await browser.newContext({ viewport: { width: 320, height: 720 } });
    const snoozePage = await snooze.newPage();
    await snoozePage.goto(origin, { waitUntil: "networkidle" });
    await seedRealHousehold(snoozePage, { caregiverName: "提醒稍后家庭" });
    assert(await snoozePage.locator(".backup-reminder").isVisible(), "household with history receives the backup reminder");
    await snoozePage.getByRole("button", { name: "7 天后提醒" }).click();
    assert.equal(await snoozePage.locator(".backup-reminder").count(), 0, "backup reminder can be snoozed");
    assert(new Date((await stored(snoozePage)).meta.backupReminderSnoozedUntil).getTime() > Date.now(), "snooze persists a future local reminder date");
    await snooze.close();

    const demo = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const demoPage = await demo.newPage();
    await demoPage.goto(origin, { waitUntil: "networkidle" });
    await demoPage.getByRole("button", { name: /体验演示家庭/ }).click();
    await demoPage.getByRole("button", { name: "家庭设置" }).click();
    assert.equal(await demoPage.getByRole("button", { name: /创建加密备份|恢复备份/ }).count(), 0, "demo settings expose no real-household backup or restore actions");
    await demo.close();

    console.log("Recovery E2E passed: v2 metadata minimization, active closure, round trip, zero network, credentials, consent, atomic rollback, policy/gap recommendation revalidation, minimal audit, 320px preview, reminder snooze, and demo isolation");
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
