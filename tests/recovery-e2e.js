"use strict";

const assert = require("node:assert/strict");
const { firefox } = require("/usr/local/lib/python3.12/dist-packages/playwright/driver/package");
const { server } = require("../server");

const FIREFOX_PATH = "/home/kasm-user/.cache/ms-playwright/firefox-1509/firefox/firefox";
const STORAGE_KEY = "relay-rehearsal-demo-v1";
const AUTHORITY_KEY = "relay-rehearsal-consent-authority-v1";
const PASSPHRASE = "household backup password";

async function listen() {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return `http://127.0.0.1:${server.address().port}`;
}

async function seedRealHousehold(page, { caregiverName = "备份前照护者", authorityStatus = "granted", authorityRevision = 4 } = {}) {
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
    };
    state.recipientConsent = {
      status: values.authorityStatus,
      revision: values.authorityRevision,
      grantedAt: values.authorityStatus === "granted" ? new Date().toISOString() : null,
      withdrawnAt: values.authorityStatus === "withdrawn" ? new Date().toISOString() : null,
    };
    state.confirmations = [];
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
    state.activity = [];
    state.gaps = [];
    state.debriefs = [];
    state.revokedGuideIds = [];
    state.activeRest = null;
    state.activeRehearsal = null;
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
  }, [STORAGE_KEY, AUTHORITY_KEY, { caregiverName, authorityStatus, authorityRevision }]);
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
    assert.equal(envelope.kdf.name, "PBKDF2", "browser backup declares PBKDF2");
    assert.equal(envelope.cipher.name, "AES-GCM", "browser backup declares AES-GCM");
    assert(!backup.toString("utf8").includes("备份前照护者") && !backup.toString("utf8").includes("13800138000"), "download contains no household plaintext");
    assert((await stored(page)).meta.lastBackupAt, "successful download records the backup reminder timestamp");
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
    assert(restored.meta.lastRecovery?.auditId?.startsWith("recovery-"), "restore writes a visible stable audit marker");
    assert.equal(restored.activeRest, null, "restore never resumes active rest");
    assert.equal(restored.activeRehearsal, null, "restore never resumes active rehearsal");
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
    assert(await cleanPage.getByText(/恢复审计标记/).isVisible(), "settings expose the restore audit marker");
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
      return window.RelayRecovery.createEncryptedBackup({
        state,
        authority: JSON.parse(localStorage.getItem(authorityKey)),
        passphrase: secret,
        appBuild: document.documentElement.dataset.build,
        now: new Date().toISOString(),
      });
    }, [STORAGE_KEY, AUTHORITY_KEY, PASSPHRASE]);
    const adversarialBackup = Buffer.from(adversarialBackupText, "utf8");
    await openRestore(policyPage, adversarialBackup);
    await policyPage.getByRole("heading", { name: /完整覆盖这台设备上的家庭/ }).waitFor({ timeout: 60_000 });
    assert(await policyPage.getByText(/原本可用的指导在当前策略/).isVisible(), "confirmation discloses current-policy guide downgrades before overwrite");
    await confirmRestore(policyPage);
    const policyState = await stored(policyPage);
    assert.equal(policyState.guides.find((guide) => guide.id === "unsafe-restored-guide")?.status, "needs-review", "restore reclassifies unsafe household guidance through the current policy");
    assert(!policyState.sessions.some((record) => record.id === "malicious-invalid-stage"), "restore drops outcome records that fail current outcome-model validation");
    await policy.close();

    const demo = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const demoPage = await demo.newPage();
    await demoPage.goto(origin, { waitUntil: "networkidle" });
    await demoPage.getByRole("button", { name: /体验演示家庭/ }).click();
    await demoPage.getByRole("button", { name: "家庭设置" }).click();
    assert.equal(await demoPage.getByRole("button", { name: /创建加密备份|恢复备份/ }).count(), 0, "demo settings expose no real-household backup or restore actions");
    await demo.close();

    console.log("Recovery E2E passed: encrypted download, round trip, wrong password, zero network, clean-device consent gate, stale withdrawal, atomic rollback, policy/outcome revalidation, audit marker, and demo isolation");
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
