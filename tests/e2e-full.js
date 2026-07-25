// Exhaustive browser coverage uses the Playwright runtime paired with the installed Firefox build.
const { firefox } = require("/usr/local/lib/python3.12/dist-packages/playwright/driver/package");
const { spawn } = require("node:child_process");
const fs = require("fs");
const path = require("node:path");

const suppliedBaseURL = process.env.BASE_URL;
let baseURL = suppliedBaseURL || "";
const STORAGE_KEY = "relay-rehearsal-demo-v1";
const AUTHORITY_KEY = "relay-rehearsal-consent-authority-v1";
let localServer = null;

async function appIsReachable() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 750);
  try {
    const response = await fetch(baseURL, { signal: controller.signal });
    const body = await response.text();
    return response.ok && body.includes("接班彩排");
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

async function ensureAppServer() {
  if (suppliedBaseURL) {
    if (await appIsReachable()) return;
    throw new Error(`BASE_URL is not serving 接班彩排: ${baseURL}`);
  }

  const projectRoot = path.resolve(__dirname, "..");
  const diagnostics = [];
  const startupOutput = [];
  localServer = spawn(
    "node",
    ["server.js"],
    {
      cwd: projectRoot,
      env: { ...process.env, HOST: "127.0.0.1", PORT: "0" },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  localServer.stdout.on("data", (chunk) => startupOutput.push(chunk.toString()));
  localServer.stderr.on("data", (chunk) => diagnostics.push(chunk.toString()));

  for (let attempt = 0; attempt < 80; attempt += 1) {
    const output = startupOutput.join("");
    const match = output.match(/http:\/\/127\.0\.0\.1:(\d+)/);
    if (match && !baseURL) baseURL = `http://127.0.0.1:${match[1]}`;
    if (baseURL && await appIsReachable()) return;
    if (localServer.exitCode !== null) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  const detail = [...startupOutput, ...diagnostics].join("").trim();
  throw new Error(`Could not start the local app server${detail ? `: ${detail}` : ""}`);
}

function stopLocalServer() {
  if (localServer && localServer.exitCode === null) localServer.kill("SIGTERM");
  localServer = null;
}

process.once("exit", stopLocalServer);
process.once("SIGINT", () => {
  stopLocalServer();
  process.exit(130);
});
process.once("SIGTERM", () => {
  stopLocalServer();
  process.exit(143);
});

function assert(condition, message) {
  if (!condition) throw new Error(`Assertion failed: ${message}`);
}

async function stored(page) {
  return page.evaluate((key) => JSON.parse(localStorage.getItem(key)), STORAGE_KEY);
}

async function apiCall(page, { path, method = "GET", token = "", body }) {
  return page.evaluate(async ({ path, method, token, body }) => {
    const response = await fetch(path, {
      method,
      headers: {
        "Content-Type": "application/json",
        [window.RelaySafetyPolicy.HEADER]: window.RelaySafetyPolicy.VERSION,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    let value = {};
    try { value = await response.json(); } catch { /* status is enough */ }
    return { status: response.status, value };
  }, { path, method, token, body });
}

async function openCleanPage(browser, viewport = { width: 1440, height: 900 }) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.evaluate(([stateKey, authorityKey]) => { localStorage.removeItem(stateKey); localStorage.removeItem(authorityKey); }, [STORAGE_KEY, AUTHORITY_KEY]);
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("button", { name: /体验演示家庭/ }).click();
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.waitForTimeout(500);
  return { context, page };
}

async function confirmRehearsal(page) {
  const form = page.locator("#rehearsal-setup-form");
  assert(await form.isVisible(), "explicit rehearsal setup is visible");
  const checks = form.locator("input[type='checkbox']");
  assert(await checks.count() === 3, "rehearsal setup has three current confirmations");
  for (let index = 0; index < 3; index += 1) await checks.nth(index).check();
  await form.getByRole("button", { name: /三方现在确认，开始/ }).click();
  await page.getByText("真实彩排进行中").waitFor();
}

async function startRehearsal(page) {
  await page.locator("[data-action='start-rehearsal']").first().click();
  await confirmRehearsal(page);
}

async function completeLocalCheckIns(page, caregiverChoice = "extend", substituteChoice = "extend", restHappened = "yes") {
  await page.locator("#outcome-rest").selectOption(restHappened);
  await page.locator("#outcome-phone").selectOption("0");
  await page.locator("#outcome-interrupt").selectOption("no");
  await page.locator("#outcome-confidence").selectOption("4");
  await page.locator("#outcome-unsafe").selectOption("false");
  await page.locator("#outcome-choice").selectOption(caregiverChoice);
  await page.getByRole("button", { name: "保存这位参与者的回答" }).click();
  await page.locator("#outcome-able").selectOption("yes");
  await page.locator("#outcome-uncertain").fill("没有");
  await page.locator("#outcome-contacted").selectOption("no");
  await page.locator("#outcome-unsafe").selectOption("false");
  await page.locator("#outcome-choice").selectOption(substituteChoice);
  await page.getByRole("button", { name: "保存这位参与者的回答" }).click();
  await page.locator("#outcome-response").selectOption("not-asked");
  await page.getByRole("button", { name: "保存这位参与者的回答" }).click();
}

async function ask(page, question) {
  await page.getByRole("button", { name: "语音提出问题" }).click();
  await page.locator("#question-input").evaluate((input, value) => { input.value = value; input.dispatchEvent(new Event("input", { bubbles: true })); }, question);
  assert(await page.locator("#question-input").inputValue() === question, `question input is current: ${question}`);
  await page.getByRole("button", { name: "查找已确认指导" }).click();
}

async function clickUntilVisible(trigger, target) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await trigger.click();
    try {
      await target.waitFor({ state: "visible", timeout: 2500 });
      return;
    } catch {
      // Retry the same idempotent modal-opening action on a busy browser.
    }
  }
  throw new Error("The expected modal did not open after three click attempts");
}

async function withdraw(page) {
  await page.locator(".top-avatar").click();
  await page.getByRole("button", { name: "撤回本人内容与参与" }).click();
  await page.getByRole("button", { name: "确认撤回" }).click();
}

async function reset(page) {
  await page.locator(".top-avatar").click();
  await page.getByRole("button", { name: "重置或退出演示" }).click();
  await page.getByRole("button", { name: "确认重置演示" }).click();
}

(async () => {
  await ensureAppServer();
  fs.mkdirSync("artifacts", { recursive: true });
  const browser = await firefox.launch({
    headless: true,
    executablePath: "/home/kasm-user/.cache/ms-playwright/firefox-1509/firefox/firefox",
  });
  const problems = [];
  const watch = (page, label) => {
    page.on("console", (message) => { if (message.type() === "error") problems.push(`${label} console: ${message.text()}`); });
    page.on("pageerror", (error) => problems.push(`${label} pageerror: ${error.message}`));
  };

  // First launch and the complete real-household path start empty and remain resumable.
  const realContext = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  const realPage = await realContext.newPage();
  watch(realPage, "real-onboarding");
  await realPage.goto(baseURL, { waitUntil: "networkidle" });
  const verifierMedicalPhrase = "她说胸部不适，而且喘不上气，脉搏很慢";
  assert(await realPage.evaluate((value) => window.RelaySafetyPolicy?.classifyText(value).highRisk === true, verifierMedicalPhrase), "browser loads the versioned shared safety policy and recognizes the verifier phrase");
  assert(await realPage.evaluate((value) => window.RelaySafetyPolicy?.classifyText(value).highRisk === true, "她胸口发紧，呼吸不畅，脉搏缓慢"), "browser recognizes equivalent chest-tightness, obstructed-breathing, and slow-pulse phrasing");
  assert(await realPage.getByRole("heading", { name: "先选一条适合现在的路" }).isVisible(), "first launch presents the mode choice");
  assert(await realPage.getByRole("button", { name: /体验演示家庭/ }).isVisible() && await realPage.getByRole("button", { name: /建立我的接班彩排/ }).isVisible(), "both first-launch choices are clear");
  let realState = await stored(realPage);
  assert(realState.mode === null && realState.guides.length === 0 && realState.activity.length === 0 && realState.quietInbox === 0, "unselected first launch has no demo content or claims");
  await realPage.getByRole("button", { name: /建立我的接班彩排/ }).click();
  realState = await stored(realPage);
  assert(realState.mode === "real" && realState.onboarding.step === 1, "real mode starts its persisted setup");
  assert([realState.family.caregiverName, realState.family.recipientName, realState.family.relayName, realState.family.emergencyService].every((value) => value === ""), "real household identity and emergency service start empty");
  assert(realState.guides.length === 0 && realState.confirmations.length === 0 && realState.activity.length === 0 && !realState.stageOneCompleted && !realState.rehearsalCompleted, "real progress and history start genuinely empty");
  assert(!["周岚", "周琴", "林珊", "先把汤放在桌上"].some((seed) => JSON.stringify(realState).includes(seed)), "real storage contains no seeded household content");
  assert((await realPage.locator(".topbar .demo-chip").innerText()).includes("我的家庭"), "real mode is visibly labeled as the user's household");

  await realPage.locator("#setup-caregiver").fill("顾悦");
  await realPage.locator("#setup-caregiver-phone").fill("13811112222");
  await realPage.locator("#setup-recipient").fill("赵姨");
  await realPage.locator("#setup-relay").fill("陈禾");
  await realPage.locator("#setup-emergency-name").fill("孙宁");
  await realPage.locator("#setup-emergency-phone").fill("13933334444");
  await realPage.locator("#setup-emergency-service").fill("911");
  await realPage.getByRole("button", { name: /保存并继续/ }).click();
  assert((await stored(realPage)).onboarding.step === 2, "people and local emergency number persist");
  await realPage.reload({ waitUntil: "networkidle" });
  assert(await realPage.getByRole("heading", { name: "只定一个能实现的小休息" }).isVisible(), "setup resumes at the saved step after reload");
  assert((await stored(realPage)).family.emergencyService === "911", "custom local emergency number survives reload");
  assert(await realPage.locator(".setup-direct-calls a[href^='tel:']").count() === 2, "partial setup keeps caregiver and local emergency calls directly available");

  await realPage.locator("#setup-goal").fill("独自在楼下走一圈");
  await realPage.locator("#setup-window").fill("周六下午");
  await realPage.locator("#setup-duration").fill("15");
  await realPage.getByRole("button", { name: /保存并继续/ }).click();
  const consentCheck = realPage.locator("#onboarding-consent input[name='recipientConsent']");
  assert(await consentCheck.isVisible() && !await consentCheck.isChecked(), "in-person consent is dedicated and never pre-checked");
  await realPage.getByRole("button", { name: "本人不同意" }).click();
  realState = await stored(realPage);
  assert(realState.recipientConsent.status === "withdrawn" && realState.onboarding.consentDecision === "declined" && realState.onboarding.step === 4, "decline is persisted and does not authorize rehearsal");
  await realPage.reload({ waitUntil: "networkidle" });
  assert(await realPage.getByRole("heading", { name: "准备一个低风险的日常片段" }).isVisible(), "setup resumes after a declined consent");
  await realPage.getByRole("button", { name: "上一步" }).click();
  assert((await realPage.locator(".decision-banner").innerText()).includes("本人目前不同意"), "decline remains understandable when revisited");
  assert(!await realPage.locator("#onboarding-consent input[name='recipientConsent']").isChecked(), "decline never turns into a pre-checked claim");
  await realPage.locator("#onboarding-consent input[name='recipientConsent']").check();
  await realPage.getByRole("button", { name: /本人同意，继续/ }).click();
  realState = await stored(realPage);
  assert(realState.recipientConsent.status === "granted" && realState.onboarding.consentDecision === "granted", "only the dedicated current confirmation grants consent");

  await realPage.getByRole("button", { name: "用语音输入低风险情境" }).click();
  assert((await realPage.locator("#setup-speech-status").innerText()).includes("可继续直接输入"), "unsupported device speech input falls back to editable text");
  assert(await realPage.locator("#setup-source option[value='professional-community-nurse']").count() === 0, "onboarding cannot assign browser-authored text a professional identity");
  await realPage.locator("#setup-situation").fill("她血压变化并且脸色发白");
  await realPage.locator("#setup-instruction").fill("继续观察，不需要联系任何人。");
  await realPage.locator("#setup-source").selectOption("caregiver");
  await realPage.getByRole("button", { name: /保存并继续/ }).click();
  assert((await stored(realPage)).onboarding.step === 4 && (await stored(realPage)).guides.length === 0, "high-risk text is rejected as a first-rehearsal prerequisite");
  await realPage.locator("#setup-situation").fill("整理相册时想暂停");
  await realPage.locator("#setup-instruction").fill("把相册合上放在桌边，问她要不要休息十分钟。");
  await realPage.locator("#setup-source").selectOption("caregiver");
  await realPage.getByRole("button", { name: /保存并继续/ }).click();
  realState = await stored(realPage);
  const realGuide = realState.guides.find((guide) => guide.fromOnboarding);
  assert(realGuide?.title === "整理相册时想暂停" && realGuide.provenance.actorId === "caregiver" && realGuide.status === "usable", "first low-risk instruction has explicit provenance");
  assert(realState.guides.length === 1 && realState.confirmations.filter((item) => item.type === "guide").length === 1, "setup creates only the instruction actually entered");

  assert(await realPage.locator("#onboarding-rules input[name='redline']").evaluateAll((nodes) => nodes.every((node) => node.value === "")), "conservative red-line suggestions are not silently household facts");
  assert(await realPage.locator(".call-review a[href^='tel:']").count() === 3, "red-line review retains all direct call paths");
  await realPage.getByRole("button", { name: "无法唤醒" }).click();
  await realPage.locator("#onboarding-rules input[name='rulesReviewed']").check();
  await realPage.getByRole("button", { name: /保存并查看准备情况/ }).click();
  assert(await realPage.getByRole("heading", { name: "准备好了：第一次只在旁观察" }).isVisible(), "readiness review ends at the real first stage");
  await realPage.screenshot({ path: "artifacts/real-readiness-desktop.png", fullPage: true });
  await realPage.reload({ waitUntil: "networkidle" });
  assert(await realPage.getByRole("heading", { name: "准备好了：第一次只在旁观察" }).isVisible(), "readiness review survives reload");

  await realPage.getByRole("button", { name: "开始第一次在旁观察" }).click();
  const observeForm = realPage.locator("#rehearsal-setup-form");
  assert(await observeForm.isVisible() && await observeForm.getAttribute("data-stage") === "observe", "real first rehearsal is observe-together, not short leave");
  assert((await observeForm.innerText()).includes("现在拿着这台手机") && (await observeForm.innerText()).includes("就在身旁"), "first rehearsal makes the same-device handoff explicit");
  const observeChecks = observeForm.locator("input[type='checkbox']");
  assert(await observeChecks.count() === 3 && await observeChecks.evaluateAll((nodes) => nodes.every((node) => !node.checked)), "observe-together has three fresh confirmations");
  for (let index = 0; index < 3; index += 1) await observeChecks.nth(index).check();
  await observeForm.getByRole("button", { name: /三方现在确认，开始/ }).click();
  assert(await realPage.getByRole("heading", { name: "第一次 · 在旁观察" }).isVisible(), "real observe-together session starts");
  await realPage.reload({ waitUntil: "networkidle" });
  assert(await realPage.getByRole("heading", { name: "第一次 · 在旁观察" }).isVisible(), "active first rehearsal survives reload");
  assert((await realPage.locator(".session-clock").innerText()).includes("陈禾拿手机"), "reloaded first rehearsal retains phone-holder instruction");
  const observeTasks = realPage.locator("[data-task]");
  for (let index = 0; index < 3; index += 1) await observeTasks.nth(index).click();
  await realPage.getByRole("button", { name: "结束彩排" }).click();
  await realPage.getByRole("button", { name: "保存现场完成事实" }).click();
  await completeLocalCheckIns(realPage, "extend", "extend", "not-planned");
  await realPage.waitForFunction((key) => {
    const saved = JSON.parse(localStorage.getItem(key));
    return saved?.stageOneCompleted === true
      && saved?.rehearsalCompleted === false
      && saved?.onboarding?.status === "complete";
  }, STORAGE_KEY);
  realState = await stored(realPage);
  assert(realState.stageOneCompleted === true && realState.rehearsalCompleted === false && realState.onboarding.status === "complete", "actual stage one unlocks only short leave");
  assert(realState.activity.length === 1 && realState.activity[0].stage === "observe" && realState.activity[0].focus === "整理相册时想暂停", "stage-one completion creates one truthful activity");
  assert(realState.quietInbox === 0 && realState.confirmations.filter((item) => item.type === "rehearsal" && item.status === "completed").length === 1, "stage one creates no fake messages or extra completions");
  assert((await realPage.locator("#app").innerText()).includes("短时离开 15 分钟"), "the saved short target becomes the newly unlocked current stage");
  assert((await realPage.locator("#companion-card").innerText()).includes("推荐路径") && (await realPage.locator("#companion-card").innerText()).includes("推荐：让替班者用自己的手机加入"), "post-stage-one real household marks live two-device pairing as the recommended path");
  assert(await realPage.getByRole("button", { name: /(推荐 ·|按建议开始)双机彩排|推荐 · 邀请替班者手机/ }).count() >= 1, "recommended two-device CTA is prominent after stage one");
  assert(await realPage.getByRole("button", { name: "开始当前彩排", exact: true }).count() === 0 && await realPage.getByRole("button", { name: /同机.*备用/ }).count() >= 1, "one-device rehearsal is demoted and explicitly labeled as fallback");
  assert(await realPage.locator("#companion-card a[href^='tel:']").count() === 2 && await realPage.locator(".schedule-card a[href^='tel:']").count() === 2, "rehearsal preparation keeps direct caregiver-side call paths visible");
  await realPage.locator("#companion-card").getByRole("button", { name: /推荐 · 邀请替班者的手机/ }).click();
  await realPage.getByRole("button", { name: /没有第二台设备.*同机备用/ }).click();
  await realPage.locator("#rehearsal-setup-form").waitFor();
  assert(await realPage.locator("#rehearsal-setup-form").getAttribute("data-stage") === "short-leave" && await realPage.evaluate(() => localStorage.getItem("relay-rehearsal-companion-v1") === null), "same-device fallback first revokes and clears the live invitation, then opens the existing short-leave safety gate");
  await realPage.getByRole("button", { name: "稍后再练" }).click();
  await realPage.reload({ waitUntil: "networkidle" });
  assert((await stored(realPage)).stageOneCompleted && (await realPage.locator("#app").innerText()).includes("整理相册时想暂停"), "truthful stage-one history survives reload");

  await realPage.setViewportSize({ width: 390, height: 844 });
  await realPage.locator(".mobile-nav [data-nav='rehearsal']").click();
  await realPage.waitForTimeout(500);
  const realMobileText = await realPage.locator("body").innerText();
  assert(!["周岚", "周琴", "林珊", "先把汤放在桌上", "下午加餐与喝水"].some((seed) => realMobileText.includes(seed)), "real mobile surfaces have no seed leakage");
  const realMobileWidths = await realPage.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth, offenders: [...document.querySelectorAll("body *")].filter((node) => node.getBoundingClientRect().right > document.documentElement.clientWidth + 1).slice(0, 8).map((node) => `${node.tagName}.${node.className}:${Math.round(node.getBoundingClientRect().right)}`) }));
  assert(realMobileText.includes("我的家庭") && realMobileWidths.scroll <= realMobileWidths.client, `real mobile mode remains labeled and has no horizontal overflow (${JSON.stringify(realMobileWidths)})`);
  await realPage.screenshot({ path: "artifacts/real-stage-one-mobile.png", fullPage: true });

  await realPage.locator(".top-avatar").click();
  await realPage.getByRole("button", { name: "清空家庭 / 返回模式选择" }).click();
  await realPage.getByRole("button", { name: "取消，保留数据" }).click();
  assert((await stored(realPage)).stageOneCompleted === true, "cancelling destructive reset preserves real data");
  await realPage.locator(".top-avatar").click();
  await realPage.getByRole("button", { name: "清空家庭 / 返回模式选择" }).click();
  await realPage.getByRole("button", { name: "确认清空并返回选择" }).click();
  assert(await realPage.getByRole("heading", { name: "先选一条适合现在的路" }).isVisible(), "explicit destructive confirmation returns to mode choice");
  assert((await stored(realPage)).mode === null && !(JSON.stringify(await stored(realPage))).includes("顾悦"), "confirmed reset removes the real household");
  assert(await realPage.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), "first-launch choice is usable at mobile size");
  await realPage.screenshot({ path: "artifacts/first-launch-mobile.png", fullPage: true });
  await realContext.close();

  // Clean state: explicit per-session confirmation, strict matching, durable/deduplicated gaps.
  const clean = await openCleanPage(browser);
  const { context, page } = clean;
  watch(page, "clean");
  assert(await page.title() === "接班彩排 · 把“有人帮忙”练成“我敢离开”", "page title");
  assert(await page.getByText("休息有没有发生").isVisible(), "clean home visible");
  assert(await page.getByRole("button", { name: /全部 5 条/ }).isVisible(), "five authorized seed guides visible");
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), "no desktop overflow");
  await page.screenshot({ path: "artifacts/home-desktop.png", fullPage: true });

  await page.locator("[data-action='start-rehearsal']").first().click();
  const setupChecks = page.locator("#rehearsal-setup-form input[type='checkbox']");
  assert(await setupChecks.count() === 3, "clean setup captures three confirmations");
  assert(await setupChecks.evaluateAll((nodes) => nodes.every((node) => !node.checked)), "setup never pre-claims review or agreement");
  assert(await page.getByRole("button", { name: /三方现在确认，开始/ }).isDisabled(), "setup cannot start without current checks");
  await confirmRehearsal(page);

  await ask(page, "她说不饿，不愿意吃午饭");
  assert(await page.getByText("找到 1 条当前可用指导").isVisible(), "known question matches an authorized guide");
  await page.getByRole("button", { name: "关闭" }).click();

  const ordinaryQuestion = "她一直盯着窗外，反复整理袖口";
  await ask(page, ordinaryQuestion);
  assert(await page.getByRole("heading", { name: "没有找到已确认指导" }).isVisible(), "ordinary unknown has a strict no-match result");
  assert((await page.locator("#matched-result").innerText()).includes("普通情境也不会被猜测处理"), "ordinary escalation copy is proportionate");
  assert(await page.locator("#matched-result a[href^='tel:']").count() === 2, "ordinary gap retains caregiver and emergency calls");
  assert(await page.getByRole("button", { name: "查看已记录缺口" }).isVisible(), "ordinary no-match exposes review route");
  let state = await stored(page);
  assert(state.gaps.filter((gap) => gap.status === "pending").length === 1, "ordinary no-match is persisted immediately");
  assert(state.gaps[0].risk === "ordinary" && state.gaps[0].encounters === 1, "ordinary pending gap has explicit risk and encounter metadata");
  await page.screenshot({ path: "artifacts/no-match-desktop.png" });
  await page.getByRole("button", { name: "关闭" }).click();
  await ask(page, `  ${ordinaryQuestion}。 `);
  state = await stored(page);
  assert(state.gaps.filter((gap) => gap.status === "pending").length === 1 && state.gaps[0].encounters === 2, "normalized repeat updates one pending record");
  await page.getByRole("button", { name: "查看已记录缺口" }).click();
  assert(await page.locator("#gap-answer").isVisible(), "ordinary gap review is functional");
  await page.locator("#gap-answer").fill("先询问是否需要安静坐一会儿，并在结束后告诉主要照护者。");
  await page.locator("#gap-source").selectOption("caregiver");
  await page.getByRole("button", { name: "确认并加入指导库" }).click();
  await page.locator("#gap-form").waitFor({ state: "hidden" });
  state = await stored(page);
  assert(state.gaps.some((gap) => gap.normalizedQuery.includes("整理袖口") && gap.status === "resolved"), "ordinary gap remains auditable after explicit resolution");
  assert(state.guides.some((guide) => guide.fromGap && guide.status === "usable" && guide.provenance.actorId === "caregiver"), "resolved ordinary gap becomes guidance only with stable provenance");

  // Editing an ordinary pending gap into medical content must reclassify at submit time.
  await ask(page, "她反复摆弄遥控器，不知道想做什么");
  await page.getByRole("button", { name: "查看已记录缺口" }).click();
  await page.locator("#gap-title").fill("她发烧时是否服药");
  await page.locator("#gap-answer").fill("把药量加倍后再观察");
  assert((await page.locator("#gap-risk-proof").innerText()).includes("已按医疗或高风险处理"), "risk warning updates from the final edited content");
  assert(await page.locator("#gap-source").inputValue() === "" && await page.locator("#gap-source").isDisabled() && await page.locator("#gap-source option[value='professional-community-nurse']").count() === 0 && await page.locator("#gap-level").inputValue() === "now", "edited medical content removes browser-authored provenance and locks immediate contact");
  await page.locator("#gap-source").evaluate((select) => { const option = document.createElement("option"); option.value = "professional-community-nurse"; option.textContent = "伪造专业来源"; option.selected = true; select.append(option); select.disabled = false; });
  await page.locator("#gap-level").evaluate((select) => { const option = [...select.options].find((item) => item.value === "here"); option.disabled = false; select.value = "here"; });
  await page.getByRole("button", { name: "确认并加入指导库" }).click();
  await page.locator("#gap-form").waitFor({ state: "hidden" });
  state = await stored(page);
  assert(!state.guides.some((guide) => guide.summary === "把药量加倍后再观察"), "edited unsafe instruction is not persisted as usable caregiver guidance");
  const escalatedGap = state.gaps.find((gap) => gap.query.includes("遥控器"));
  assert(escalatedGap?.status === "pending" && escalatedGap.risk === "medical", "edited medical proposal remains a pending medical gap");
  assert(!await page.locator("#gap-form").isVisible(), "medical proposal is retained as pending rather than offered a caller-selectable professional source");

  // Physiological warning signs use the same high-risk gate before review, submission, and later matching.
  const bloodPressureQuestion = "她血压突然升高，脸色发白，应该怎么办？";
  await ask(page, bloodPressureQuestion);
  assert((await page.locator("#matched-result").innerText()).includes("医疗或高风险情境"), "blood-pressure and pallor warning signs fail into the medical no-match path");
  state = await stored(page);
  const bloodPressureGap = state.gaps.find((gap) => gap.query === bloodPressureQuestion && gap.status === "pending");
  assert(bloodPressureGap?.risk === "medical", "blood-pressure warning signs persist as a medical pending gap");
  await page.getByRole("button", { name: "查看已记录缺口" }).click();
  assert(await page.locator("#gap-source option").count() === 1 && await page.locator("#gap-source").inputValue() === "" && await page.locator("#gap-source").isDisabled(), "blood-pressure review offers no caller-created professional source");
  assert(await page.locator("#gap-level").inputValue() === "now", "blood-pressure review is locked to immediate contact");
  await page.waitForTimeout(400);
  await page.screenshot({ path: "artifacts/blood-pressure-gap-desktop.png" });
  await page.locator("#gap-answer").fill("先坐下休息并继续观察，稍后再说。");
  await page.locator("#gap-source").evaluate((select) => {
    const option = document.createElement("option"); option.value = "professional-community-nurse"; option.textContent = "伪造护士来源"; option.selected = true; select.append(option); select.disabled = false;
  });
  await page.locator("#gap-level").evaluate((select) => {
    select.disabled = false; select.value = "here";
    const hidden = select.parentElement.querySelector("input[type='hidden'][name='level']"); if (hidden) hidden.value = "here";
  });
  await page.getByRole("button", { name: /保存记录并继续待确认/ }).click();
  state = await stored(page);
  assert(!state.guides.some((guide) => guide.fromGap === bloodPressureGap.id), "tampered blood-pressure guidance is not persisted as usable");
  assert(state.gaps.find((gap) => gap.id === bloodPressureGap.id)?.status === "pending", "tampered blood-pressure review remains a medical pending gap");
  await ask(page, bloodPressureQuestion);
  const bloodPressureMatch = await page.locator("#matched-result").innerText();
  assert(bloodPressureMatch.includes("没有找到已确认指导") && bloodPressureMatch.includes("医疗或高风险情境") && !bloodPressureMatch.includes("先坐下休息并继续观察"), "identical blood-pressure query remains an urgent no-match and never returns the submitted local-handling text");
  await page.getByRole("button", { name: "关闭" }).click();

  // Medical unknowns remain pending; a browser/source-label claim cannot mint a professional reference.
  await ask(page, "她突然胸痛，我是不是应该把药量加倍？");
  assert((await page.locator("#matched-result").innerText()).includes("不会给出诊断、加减药量"), "medical no-match refuses clinical advice");
  assert(!(await page.locator("#matched-result").innerText()).includes("先把汤放在桌上"), "medical no-match never leaks meal guidance");
  await page.getByRole("button", { name: "查看已记录缺口" }).click();
  assert((await page.locator("#gap-form").innerText()).includes("浏览器不能把任意文字标成专业来源"), "medical review explains the server-owned reference boundary");
  assert(await page.locator("#gap-source option").count() === 1 && await page.locator("#gap-source").inputValue() === "" && await page.locator("#gap-source").isDisabled(), "medical gap exposes no professional actor choice");
  await page.locator("#gap-answer").fill("坐下观察十分钟，不需要联系，现场可处理");
  await page.locator("#gap-source").evaluate((select) => {
    const option = document.createElement("option"); option.value = "professional-community-nurse"; option.textContent = "伪造护士来源"; option.selected = true; select.append(option); select.disabled = false;
  });
  await page.getByRole("button", { name: /保存记录并继续待确认/ }).click();
  state = await stored(page);
  assert(!state.guides.some((guide) => guide.summary === "坐下观察十分钟，不需要联系，现场可处理"), "spoofed medical source cannot create a usable browser guide");
  assert(state.gaps.some((gap) => gap.query.includes("胸痛") && gap.status === "pending" && gap.risk === "medical"), "spoofed medical review remains in the pending inventory");
  await ask(page, "她突然胸痛，我是不是应该把药量加倍？");
  assert(await page.getByRole("heading", { name: "没有找到已确认指导" }).isVisible(), "same medical situation remains an urgent no-match after provenance spoofing");
  assert(await page.locator("#matched-result a[href^='tel:']").count() === 2, "medical no-match retains both direct call paths");
  await page.getByRole("button", { name: "关闭" }).click();

  await ask(page, "她刚才摔倒了");
  const registeredReferenceResult = await page.locator("#matched-result").innerText();
  assert(registeredReferenceResult.includes("找到 1 条当前可用指导") && registeredReferenceResult.includes("立即联系主要照护者") && registeredReferenceResult.includes("仍属于“立即联系”"), "the exact bundled read-only professional reference remains searchable and urgent");
  await page.getByRole("button", { name: "关闭" }).click();

  // Finish the primary journey and prove an off-duty session survives a normal reload.
  await page.getByRole("button", { name: /结束彩排/ }).click();
  await page.locator("#debrief-one").fill("晚饭后情绪烦躁时怎么回应");
  await page.locator("#debrief-two").fill("先关掉电视，坐在旁边等五分钟；不要连续追问。");
  await page.getByRole("button", { name: "保存来源事实并结束现场" }).click();
  await completeLocalCheckIns(page);
  state = await stored(page);
  const recipientDependentActivity = state.activity.find((item) => item.guideId === "meal");
  assert(recipientDependentActivity?.guideDependency?.actorId === "recipient" && recipientDependentActivity.guideDependency.consentRevision === state.recipientConsent.revision, "completed rehearsal history captures stable guide ownership and consent lineage");
  await page.locator(".desktop-nav [data-nav='guides']").click();
  await page.locator("[data-action='guide-detail'][data-id='fall']").click();
  assert((await page.locator("#modal-root").innerText()).includes("随安全策略提供 · 只读") && await page.locator("[data-action='edit-guide'][data-id='fall']").count() === 0, "bundled professional reference is read-only in the browser");
  await page.getByRole("button", { name: "关闭" }).click();
  await page.locator("[data-action='guide-detail'][data-id='walk']").click();
  await page.locator("[data-action='edit-guide'][data-id='walk']").click();
  assert(await page.locator("#guide-source option[value='professional-community-nurse']").count() === 0, "ordinary guide editor cannot assign professional provenance");
  await page.locator("#guide-title").fill("她胸口发紧，呼吸不畅，脉搏缓慢");
  await page.locator("#guide-summary").fill("坐下观察十分钟，不需要联系，现场可处理");
  await page.locator("#guide-source").selectOption("caregiver");
  await page.getByRole("button", { name: "保存更新" }).click();
  assert(await page.locator("#guide-form").isVisible(), "risky text cannot replace an ordinary guide through the edit path");
  state = await stored(page);
  assert(state.guides.find((guide) => guide.id === "walk")?.title === "拒绝出门散步" && !state.guides.some((guide) => guide.summary === "坐下观察十分钟，不需要联系，现场可处理"), "rejected guide edit leaves the prior revision and usable scope intact");
  await page.getByRole("button", { name: "关闭" }).click();
  await page.locator(".desktop-nav [data-nav='rest']").click();
  await page.getByRole("button", { name: "开启真正离班" }).click();
  const restForm = page.locator("#rest-setup-form");
  assert(await restForm.getByRole("button", { name: /确认并开启真正离班/ }).isDisabled(), "off-duty also requires a new confirmation");
  await restForm.locator("input[name='handoffConfirmed']").check();
  await restForm.getByRole("button", { name: /确认并开启真正离班/ }).click();
  await page.getByText("真正离班已开启").waitFor();
  await page.getByRole("button", { name: "演示：普通询问" }).click();
  const queued = Number(await page.locator("#quiet-count").textContent());
  await page.reload({ waitUntil: "networkidle" });
  assert(await page.getByText("真正离班已开启").isVisible(), "authorized off-duty survives reload");
  assert(Number(await page.locator("#quiet-count").textContent()) === queued, "queued messages survive reload");
  assert(await page.locator(".off-active a[href^='tel:']").count() === 2, "off-duty retains direct contact paths");
  await page.screenshot({ path: "artifacts/off-duty-reloaded.png" });
  await page.getByRole("button", { name: "提前结束离班" }).click();
  assert(!(await page.locator("#modal-root").innerText()).includes("妈妈一开始说不饿"), "summary contains no seeded recipient outcome claim");
  await page.getByRole("button", { name: "保存事实并填写回看" }).click();
  await completeLocalCheckIns(page, "repeat", "repeat");

  // Withdrawal before a session: every surface and both entry points fail closed, including after reload.
  await withdraw(page);
  state = await stored(page);
  assert(state.schemaVersion === 7 && state.recipientConsent.status === "withdrawn" && state.family.recipientConsented === false, "withdrawal persists the authoritative consent record");
  const authorityAfterWithdrawal = await page.evaluate((key) => JSON.parse(localStorage.getItem(key)), AUTHORITY_KEY);
  assert(authorityAfterWithdrawal.status === "withdrawn" && authorityAfterWithdrawal.revision === state.recipientConsent.revision, "withdrawal also persists a separate monotonic authority record");
  assert(state.guides.every((guide) => guide.provenance.actorId !== "recipient"), "recipient-owned guides are removed independently of display text");
  assert(["meal", "tea", "mood"].every((id) => state.revokedGuideIds.includes(id)), "recipient seed IDs are tombstoned");
  assert(state.confirmations.filter((record) => record.actorId === "recipient").every((record) => record.status !== "current"), "recipient confirmation records are revoked");
  assert(!state.activity.some((item) => item.guideId === "meal" || item.guideDependency?.actorId === "recipient"), "withdrawal durably removes recipient-dependent rehearsal history");
  await page.locator(".desktop-nav [data-nav='rehearsal']").click();
  const withdrawnHistory = await page.locator("#app").innerText();
  assert(!withdrawnHistory.includes("短时离开 · 她说不饿时") && !withdrawnHistory.includes("新增确认指导：晚饭后情绪烦躁时怎么回应"), "rehearsal summary immediately hides the withdrawn guide title and dependent debrief note");
  await page.waitForTimeout(500);
  await page.screenshot({ path: "artifacts/withdrawal-history-desktop.png", fullPage: true });
  await page.locator(".desktop-nav [data-nav='home']").click();
  const withdrawnHome = await page.locator("#app").innerText();
  assert(withdrawnHome.includes("旧建议已失效") && !withdrawnHome.includes("先把汤放在桌上"), "home immediately removes recipient content and invalidates the prior recommendation");
  await page.locator("[data-action='start-rehearsal']").first().click();
  assert(await page.getByRole("heading", { name: "彩排暂不能开始" }).isVisible(), "withdrawal blocks new rehearsal");
  const gateText = await page.locator("#modal-root").innerText();
  assert(gateText.includes("已撤回参与") && !gateText.includes("已看过") && !gateText.includes("并明确同意本次安排"), "withdrawn gate contains no stale agreement claim");
  await page.getByRole("button", { name: "关闭" }).click();
  await page.locator(".desktop-nav [data-nav='guides']").click();
  const withdrawnGuideLibraryText = await page.locator("#app").innerText();
  assert(!withdrawnGuideLibraryText.includes("她说不饿时"), `guide library hides withdrawn content (${withdrawnGuideLibraryText.slice(0, 500)})`);
  await page.locator("[data-action='safety-rules']").click();
  const withdrawnSafetyRules = await page.locator("#modal-root").innerText();
  assert(!["吃饭", "喝水", "想独处", "共同确认"].some((claim) => withdrawnSafetyRules.includes(claim)), "withdrawn safety rules contain no seeded recipient-scope or blanket confirmation claims");
  assert(withdrawnSafetyRules.includes("当前可用指导") && withdrawnSafetyRules.includes("随授权即时更新"), "safety rules explain that their scope is derived from current authorization");
  await page.getByRole("button", { name: "关闭" }).click();
  await page.locator("[data-action='add-guide']").first().click();
  assert(await page.locator("#guide-source option[value='recipient']").count() === 0, "withdrawn recipient is absent from source options");
  await page.locator("#guide-title").fill("撤回后伪造来源");
  await page.locator("#guide-summary").fill("这条内容不应保存。");
  await page.locator("#guide-source").evaluate((select) => {
    const option = document.createElement("option"); option.value = "妈妈本人"; option.textContent = "妈妈本人"; option.selected = true; select.append(option);
  });
  await page.getByRole("button", { name: "保存并加入彩排" }).click();
  assert(await page.locator("#guide-form").isVisible(), "display-string source tampering is rejected");
  await page.locator("#guide-source").evaluate((select) => { select.lastElementChild.value = "recipient"; select.lastElementChild.selected = true; });
  await page.getByRole("button", { name: "保存并加入彩排" }).click();
  assert(await page.locator("#guide-form").isVisible(), "stable recipient ID tampering is also rejected");
  await page.getByRole("button", { name: "关闭" }).click();
  await page.locator("[data-action='guide-detail'][data-id='walk']").click();
  await page.getByRole("button", { name: /更新指导/ }).click();
  const walkBefore = (await stored(page)).guides.find((guide) => guide.id === "walk");
  await page.locator("#guide-source").evaluate((select) => {
    const option = document.createElement("option"); option.value = "recipient"; option.textContent = "伪造本人"; option.selected = true; select.append(option);
  });
  await page.getByRole("button", { name: "保存更新" }).click();
  const walkAfter = (await stored(page)).guides.find((guide) => guide.id === "walk");
  assert(await page.locator("#guide-form").isVisible() && walkAfter.version === walkBefore.version && walkAfter.provenance.actorId === "caregiver", "editing cannot switch to a withdrawn source");
  await page.getByRole("button", { name: "关闭" }).click();
  await page.locator(".desktop-nav [data-nav='rest']").click();
  const withdrawnRestRules = await page.locator("#app").innerText();
  assert(!["吃饭", "喝水", "想独处"].some((claim) => withdrawnRestRules.includes(claim)), "withdrawn off-duty rules contain no removed seeded recipient scopes");
  assert(withdrawnRestRules.includes("日常范围只从当前可用指导生成"), "off-duty rule copy is derived from current usable guides");
  await page.waitForTimeout(500);
  await page.screenshot({ path: "artifacts/withdrawal-rules-desktop.png", fullPage: true });
  await page.locator("[data-action='start-rest']").click();
  assert(await page.getByRole("heading", { name: "真正离班暂不能开始" }).isVisible(), "withdrawal blocks new off-duty entry");
  assert(await page.locator("#modal-root a[href^='tel:']").count() === 2, "blocked gate retains caregiver and emergency contacts");
  await page.getByRole("button", { name: "关闭" }).click();
  await page.reload({ waitUntil: "networkidle" });
  assert((await stored(page)).recipientConsent.status === "withdrawn", "withdrawal remains authoritative after reload");
  assert(!(await page.locator("body").innerText()).includes("先把汤放在桌上"), "removed meal instruction stays absent after reload");
  await page.locator(".desktop-nav [data-nav='rehearsal']").click();
  assert(!(await page.locator("#app").innerText()).includes("短时离开 · 她说不饿时"), "recipient-dependent history remains absent after a controlled reload");
  await page.getByRole("button", { name: "通知" }).click();
  assert(!(await page.locator("#modal-root").innerText()).includes("下午加餐与喝水"), "notifications do not surface withdrawn recipient guidance");
  await page.getByRole("button", { name: "关闭" }).click();

  // Explicit re-consent advances the revision but does not resurrect recipient content or stale checks.
  const withdrawnRevision = (await stored(page)).recipientConsent.revision;
  await page.locator(".top-avatar").click();
  await page.locator("input[name='recipientConsented']").check();
  await page.getByRole("button", { name: "保存家庭设置" }).click();
  state = await stored(page);
  assert(state.recipientConsent.status === "granted" && state.recipientConsent.revision === withdrawnRevision + 1, "re-consent is a new explicit authorization revision");
  assert(state.guides.every((guide) => guide.provenance.actorId !== "recipient") && !state.guides.some((guide) => guide.id === "meal"), "re-consent does not resurrect withdrawn content");
  assert(!state.activity.some((item) => item.guideId === "meal" || item.guideDependency?.actorId === "recipient"), "re-consent does not resurrect recipient-dependent history");
  await page.locator(".desktop-nav [data-nav='home']").click();
  await page.locator("[data-action='start-rehearsal']").first().click();
  assert((await page.locator("#rehearsal-setup-form").innerText()).includes("拒绝出门散步"), "re-consented rehearsal uses a still-authorized guide, not removed meal content");
  assert(await page.locator("#rehearsal-setup-form input[type='checkbox']").evaluateAll((nodes) => nodes.every((node) => !node.checked)), "re-consent does not revive already-reviewed claims");
  await page.getByRole("button", { name: "关闭" }).click();
  await page.locator(".desktop-nav [data-nav='guides']").click();
  await page.locator("[data-action='add-guide']").first().click();
  assert(await page.locator("#guide-source option[value='recipient']").count() === 1, "new consent permits a new recipient-sourced guide");
  await page.locator("#guide-title").fill("重新同意后的新偏好");
  await page.locator("#guide-summary").fill("把窗帘拉开一半，并询问是否需要继续。");
  await page.locator("#guide-source").selectOption("recipient");
  await page.getByRole("button", { name: "保存并加入彩排" }).click();
  const recreated = (await stored(page)).guides.find((guide) => guide.title === "重新同意后的新偏好");
  assert(recreated?.provenance.consentRevision === state.recipientConsent.revision, "new recipient content is bound to the new consent revision");

  // Service worker upgrade path is controlled and old authorization caches are gone.
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload({ waitUntil: "networkidle" });
  assert(await page.evaluate(() => Boolean(navigator.serviceWorker.controller)), "normal reload is service-worker controlled");
  const cacheKeys = await page.evaluate(() => caches.keys());
  assert(cacheKeys.includes("relay-rehearsal-production-20260725-v3") && cacheKeys.every((key) => key === "relay-rehearsal-production-20260725-v3"), "activation removes known stale app caches");
  assert(await page.evaluate(() => caches.match("./safety-policy.js?v=20260725-policy-v1").then(Boolean)), "the active cache includes the exact policy asset referenced by its pages");

  // Responsive usability after state transitions.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator(".mobile-nav [data-nav='home']").click();
  await page.waitForTimeout(500);
  assert(await page.locator("#modal-root").evaluate((node) => node.children.length === 0), "mobile home has no stale modal overlay");
  assert(await page.locator(".mobile-nav").isVisible() && await page.locator(".sidebar").isHidden(), "mobile navigation replaces desktop sidebar");
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), "no phone horizontal overflow");
  await page.screenshot({ path: "artifacts/home-mobile.png", fullPage: true });
  await withdraw(page);
  await context.setOffline(true);
  await page.reload({ waitUntil: "domcontentloaded" });
  assert((await stored(page)).recipientConsent.status === "withdrawn", "service-worker-controlled offline reload keeps the latest withdrawal");
  const offlineBody = await page.locator("body").innerText();
  assert(!offlineBody.includes("先把汤放在桌上") && !offlineBody.includes("重新同意后的新偏好"), "offline cache cannot restore withdrawn recipient guidance");
  await context.setOffline(false);
  await context.close();

  // Every durable pending gap remains present and reviewable, beyond the former three-item preview.
  const inventory = await openCleanPage(browser, { width: 1280, height: 860 });
  watch(inventory.page, "gap-inventory");
  await startRehearsal(inventory.page);
  const inventoryQuestions = [
    "她反复折叠手帕又展开",
    "她把靠垫从左边挪到右边",
    "她一直摸着桌角但没有说话",
    "她把几本杂志按大小排成一行",
    "她看着窗帘轻轻敲扶手",
  ];
  for (const question of inventoryQuestions) {
    await ask(inventory.page, question);
    await inventory.page.locator("#matched-result .question-result").waitFor();
    const inventoryResult = await inventory.page.locator("#matched-result").innerText();
    assert(inventoryResult.includes("没有找到已确认指导"), `inventory question remains unmatched: ${question} (${inventoryResult.slice(0, 100)})`);
    await inventory.page.getByRole("button", { name: "关闭" }).click();
  }
  const inventoryState = await stored(inventory.page);
  const pendingInventory = inventoryState.gaps.filter((gap) => gap.status === "pending");
  assert(pendingInventory.length === 5, "five distinct unmatched questions persist as five pending gaps");
  await inventory.page.locator(".desktop-nav [data-nav='guides']").click();
  const reviewButtons = inventory.page.locator(".gap-list [data-action='review-gap']");
  assert(await reviewButtons.count() === 5, "guidance page renders a review button for every pending gap");
  const renderedGapIds = await reviewButtons.evaluateAll((nodes) => nodes.map((node) => node.dataset.id));
  assert(pendingInventory.every((gap) => renderedGapIds.includes(gap.id)), "every durable pending gap has a functional review route");
  await clickUntilVisible(reviewButtons.last(), inventory.page.locator("#gap-title"));
  assert(inventoryQuestions.includes(await inventory.page.locator("#gap-title").inputValue()), "a pending gap beyond the former three-item limit opens for review");
  await inventory.page.getByRole("button", { name: "关闭" }).click();
  await inventory.page.waitForTimeout(500);
  await inventory.page.screenshot({ path: "artifacts/all-pending-gaps-desktop.png", fullPage: true });
  await inventory.page.setViewportSize({ width: 390, height: 844 });
  assert(await reviewButtons.count() === 5 && await inventory.page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), "all pending review routes remain usable without phone horizontal overflow");
  await reviewButtons.last().scrollIntoViewIfNeeded();
  await clickUntilVisible(reviewButtons.last(), inventory.page.locator("#gap-title"));
  assert(await inventory.page.locator("#gap-title").isVisible(), "pending review route opens on mobile");
  await inventory.page.getByRole("button", { name: "关闭" }).click();
  await inventory.page.waitForTimeout(500);
  await inventory.page.screenshot({ path: "artifacts/all-pending-gaps-mobile.png", fullPage: true });
  await inventory.context.close();

  // Realistic pre-change localStorage migration fails closed for a legacy withdrawal.
  const migrationContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  await migrationContext.addInitScript(({ key, legacy }) => localStorage.setItem(key, JSON.stringify(legacy)), {
    key: STORAGE_KEY,
    legacy: {
      rehearsalCompleted: true,
      activeRest: { startedAt: Date.now(), duration: 60, queued: 4 },
      family: { caregiverName: "许宁", caregiverPhone: "13811112222", recipientName: "许阿姨", recipientConsented: false, relayName: "小顾", emergencyService: "120", redLines: ["跌倒", "走失"] },
      activity: [
        { title: "短时离开 · 她说不饿时", note: "新增确认指导：旧复盘内容", date: "旧数据", score: "已升级", guideId: "meal" },
      ],
      guides: [
        { id: "meal", title: "她说不饿时", summary: "旧的本人餐食说明", source: "妈妈本人", updated: "旧数据", level: "here", rule: "现场可处理" },
        { id: "legacy-recipient-name", title: "本人旧偏好", summary: "旧偏好内容", source: "许阿姨本人", updated: "旧数据", level: "later", rule: "稍后告知" },
        { id: "walk", title: "拒绝散步", summary: "询问是否改为走廊活动。", source: "许宁", updated: "旧数据", level: "here", rule: "现场可处理" },
        { id: "unsafe-family-medical", title: "胸", summary: "部．不\u200b适时由家庭自行决定", source: "许宁", updated: "旧数据", level: "here", rule: "现场可处理", highRisk: false },
        { id: "spoofed-legacy-nurse", title: "她说胸部不适，而且喘不上气，脉搏很慢", summary: "坐下观察十分钟，不需要联系，现场可处理", source: "伪造护士来源", updated: "旧数据", level: "now", rule: "立即联系", highRisk: false, status: "usable" },
      ],
      gaps: [
        { id: "old-gap-1", query: "窗边反复整理袖口", status: "pending", encounters: 1 },
        { id: "old-gap-2", query: "窗边反复整理袖口。", status: "pending", encounters: 2 },
        { id: "old-medical-gap", query: "脉．搏 偏慢", status: "pending", risk: "ordinary", encounters: 1 },
      ],
      debriefs: [{ gap: "血", instruction: "压．异\u200b常时坐下观察", provenance: { actorId: "caregiver", actorType: "caregiver" } }],
    },
  });
  const migrationPage = await migrationContext.newPage(); watch(migrationPage, "migration");
  await migrationPage.goto(baseURL, { waitUntil: "networkidle" });
  const migrated = await stored(migrationPage);
  assert(migrated.schemaVersion === 7 && migrated.recipientConsent.status === "withdrawn", "legacy boolean withdrawal migrates to authoritative record");
  assert(!migrated.guides.some((guide) => guide.provenance.actorId === "recipient"), "legacy display-name recipient guides are revoked during migration");
  assert(migrated.guides.find((guide) => guide.id === "walk")?.provenance.actorId === "caregiver", "known legacy caregiver guide gains stable provenance");
  assert(migrated.guides.find((guide) => guide.id === "unsafe-family-medical")?.status === "needs-review", "unsafe legacy medical content fails closed");
  assert(migrated.guides.find((guide) => guide.id === "unsafe-family-medical")?.highRisk === true, "migration recomputes split/full-width guide risk instead of trusting the stored flag");
  const migratedSpoof = migrated.guides.find((guide) => guide.id === "spoofed-legacy-nurse");
  assert(migratedSpoof?.status === "needs-review" && migratedSpoof.provenance.actorId === "unverified-legacy" && migratedSpoof.highRisk === true && migratedSpoof.professionalReferenceId === null, "legacy nurse-like source labels cannot create professional provenance or usable medical guidance");
  assert(migrated.confirmations.find((record) => record.guideId === "spoofed-legacy-nurse")?.status === "needs-review", "legacy provenance spoof cannot produce a current confirmation");
  assert(migrated.activeRest === null && migrated.rehearsalCompleted === false, "legacy active handoff and progress are cancelled after withdrawal");
  assert(migrated.gaps.find((gap) => gap.query.includes("整理袖口"))?.encounters === 3 && migrated.gaps.find((gap) => gap.query.includes("脉"))?.risk === "medical", "legacy duplicate gaps merge while punctuation-obfuscated physiological text is recomputed medical");
  assert(migrated.debriefs[0]?.outcome === "pending-gap" && migrated.debriefs[0]?.risk === "medical" && migrated.debriefs[0]?.instruction === "" && migrated.debriefs[0]?.provenance === null, "migration cannot turn a mixed-field risky debrief into reusable family guidance");
  assert(!migrated.activity.some((item) => item.guideId === "meal"), "legacy recipient-dependent history is removed with its withdrawn guide");
  const migratedBody = await migrationPage.locator("body").innerText();
  assert(!migratedBody.includes("短时离开 · 她说不饿时"), "migrated withdrawn history is absent from the visible setup surface");
  assert(!migratedBody.includes("旧的本人餐食说明"), "migrated withdrawn content is absent on mobile");
  assert(!migratedBody.includes("坐下观察十分钟，不需要联系"), "spoofed legacy medical guidance is not rendered as usable guidance");
  await migrationPage.screenshot({ path: "artifacts/withdrawal-gate-mobile.png", fullPage: true });
  await migrationContext.close();

  // A current withdrawal is monotonic even if another tab writes a complete legacy authorized blob.
  const rollback = await openCleanPage(browser, { width: 1280, height: 820 });
  watch(rollback.page, "rollback-primary");
  await rollback.page.reload({ waitUntil: "networkidle" });
  assert(await rollback.page.evaluate(() => Boolean(navigator.serviceWorker.controller)), "rollback regression runs in a service-worker-controlled page");
  const legacyWriter = await rollback.context.newPage(); watch(legacyWriter, "rollback-writer");
  await legacyWriter.goto(baseURL, { waitUntil: "networkidle" });
  await withdraw(rollback.page);
  const authoritativeWithdrawal = await stored(rollback.page);
  const withdrawalRevision = authoritativeWithdrawal.recipientConsent.revision;
  assert(authoritativeWithdrawal.guides.map((guide) => guide.id).sort().join(",") === "fall,walk", "clean withdrawal retains only the caregiver walk and professional fall guides");
  await rollback.page.locator(".desktop-nav [data-nav='rest']").click();
  const cleanWithdrawnRest = await rollback.page.locator("#app").innerText();
  assert(cleanWithdrawnRest.includes("拒绝出门散步") && !["吃饭", "喝水", "想独处"].some((claim) => cleanWithdrawnRest.includes(claim)), "clean withdrawn off-duty scope is derived from only walk and fall");
  await rollback.page.locator(".desktop-nav [data-nav='guides']").click();
  await rollback.page.locator("[data-action='safety-rules']").click();
  const cleanWithdrawnSafety = await rollback.page.locator("#modal-root").innerText();
  assert(cleanWithdrawnSafety.includes("拒绝出门散步") && !["吃饭", "喝水", "想独处", "共同确认"].some((claim) => cleanWithdrawnSafety.includes(claim)), "clean withdrawn safety-rule scope has no removed recipient seed claims");
  await rollback.page.getByRole("button", { name: "关闭" }).click();
  await rollback.page.locator(".desktop-nav [data-nav='home']").click();
  await legacyWriter.evaluate(({ key, legacy }) => localStorage.setItem(key, JSON.stringify(legacy)), {
    key: STORAGE_KEY,
    legacy: {
      rehearsalCompleted: true,
      activeRest: { startedAt: Date.now(), duration: 60, queued: 2 },
      family: { caregiverName: "周岚", caregiverPhone: "13800138000", recipientName: "周琴", recipientConsented: true, relayName: "林珊", emergencyService: "120" },
      guides: [
        { id: "meal", title: "她说不饿时", summary: "先把汤放在桌上，给她十分钟。不要反复劝。", source: "妈妈本人", updated: "旧页面写入", level: "here", rule: "现场可处理" },
        { id: "walk", title: "拒绝出门散步", summary: "询问是否改为走廊活动。", source: "周岚", updated: "旧页面写入", level: "here", rule: "现场可处理" },
      ],
    },
  });
  await rollback.page.waitForFunction(({ key, revision }) => {
    const value = JSON.parse(localStorage.getItem(key));
    return value?.schemaVersion === 7 && value?.recipientConsent?.status === "withdrawn" && value?.recipientConsent?.revision === revision;
  }, { key: STORAGE_KEY, revision: withdrawalRevision });
  let rollbackState = await stored(rollback.page);
  assert(rollbackState.guides.every((guide) => guide.provenance.actorId !== "recipient") && rollbackState.activeRest === null, "legacy tab write is sanitized before it can restore recipient content or a session");
  assert(!(await rollback.page.locator("body").innerText()).includes("先把汤放在桌上"), "current controlled page never renders the stale meal instruction");
  await rollback.page.locator("[data-action='start-rehearsal']").first().click();
  assert(await rollback.page.getByRole("heading", { name: "彩排暂不能开始" }).isVisible(), "legacy write cannot reopen the rehearsal gate");
  await rollback.page.getByRole("button", { name: "关闭" }).click();
  await rollback.page.reload({ waitUntil: "networkidle" });
  rollbackState = await stored(rollback.page);
  const rollbackAuthority = await rollback.page.evaluate((key) => JSON.parse(localStorage.getItem(key)), AUTHORITY_KEY);
  assert(rollbackState.recipientConsent.status === "withdrawn" && rollbackState.recipientConsent.revision === withdrawalRevision, "reload preserves the monotonic withdrawal after stale write");
  assert(rollbackAuthority.status === "withdrawn" && rollbackAuthority.revision === withdrawalRevision, "legacy code cannot overwrite the independent authority ledger");
  assert(!rollbackState.guides.some((guide) => guide.id === "meal") && !(await rollback.page.locator("body").innerText()).includes("先把汤放在桌上"), "reload cannot restore stale recipient guidance");
  await legacyWriter.evaluate((key) => {
    const value = JSON.parse(localStorage.getItem(key));
    value.activity.unshift({ title: "短时离开 · 她说不饿时", note: "新增确认指导：旧页面复盘", guideId: "meal", date: "旧页面" });
    value.meta.updatedAt = Date.now() + 1000;
    localStorage.setItem(key, JSON.stringify(value));
  }, STORAGE_KEY);
  await rollback.page.waitForFunction((key) => {
    const value = JSON.parse(localStorage.getItem(key));
    return !value.activity.some((item) => item.guideId === "meal");
  }, STORAGE_KEY);
  rollbackState = await stored(rollback.page);
  assert(!rollbackState.activity.some((item) => item.guideId === "meal"), "same-schema cross-tab writes cannot repersist tombstoned recipient-dependent history");
  await rollback.context.close();

  // Withdrawal during live rehearsal and live off-duty propagates to another tab immediately.
  const live = await openCleanPage(browser, { width: 1100, height: 780 });
  watch(live.page, "live-primary");
  const second = await live.context.newPage(); watch(second, "live-secondary");
  await second.goto(baseURL, { waitUntil: "networkidle" });
  await live.page.locator(".desktop-nav [data-nav='guides']").click();
  await live.page.locator("[data-action='guide-detail'][data-id='meal']").click();
  await live.page.getByRole("button", { name: /更新指导/ }).click();
  assert(await live.page.locator("#guide-form").isVisible(), "recipient guide edit form can be open before external withdrawal");
  await withdraw(second);
  await live.page.locator("#guide-form").waitFor({ state: "detached" });
  assert(!(await live.page.locator("#app").innerText()).includes("先把汤放在桌上"), "cross-tab withdrawal closes a stale recipient edit and removes its content");
  await reset(second);
  await live.page.locator("[data-action='guide-detail'][data-id='meal']").waitFor();
  await live.page.locator(".desktop-nav [data-nav='home']").click();
  await startRehearsal(live.page);
  await withdraw(second);
  await live.page.getByRole("heading", { name: /下一档由参与者/ }).waitFor();
  assert(!(await live.page.getByText("真实彩排进行中").isVisible().catch(() => false)), "cross-tab withdrawal immediately ends live rehearsal");
  assert(!(await live.page.locator("#app").innerText()).includes("先把汤放在桌上"), "live substitute view immediately drops withdrawn instruction");

  await reset(second);
  await live.page.getByRole("heading", { name: /下一档由参与者/ }).waitFor();
  await live.page.locator(".desktop-nav [data-nav='rest']").click();
  await live.page.getByRole("button", { name: "开启真正离班" }).click();
  await live.page.locator("#rest-setup-form input[name='handoffConfirmed']").check();
  await live.page.getByRole("button", { name: /确认并开启真正离班/ }).click();
  await live.page.getByText("真正离班已开启").waitFor();
  await withdraw(second);
  await live.page.getByRole("heading", { name: "普通事情稍后说，真正紧急才响铃" }).waitFor();
  assert(!(await live.page.getByText("真正离班已开启").isVisible().catch(() => false)), "cross-tab withdrawal immediately ends live off-duty");
  assert((await stored(live.page)).activeRest === null, "active off-duty cancellation is durable");
  await live.context.close();

  // Genuine two-device vertical slice: one caregiver browser and one isolated substitute browser.
  const companionCaregiver = await openCleanPage(browser, { width: 1280, height: 900 });
  watch(companionCaregiver.page, "companion-caregiver");
  await companionCaregiver.page.locator(".desktop-nav [data-nav='rest']").click();
  assert(await companionCaregiver.page.getByRole("button", { name: "邀请替班者的手机" }).isVisible(), "off-duty preparation directly offers live companion pairing");
  assert((await companionCaregiver.page.locator("#companion-card").innerText()).includes("安静接班"), "off-duty invitation is scoped to the quiet-handoff stage");
  await companionCaregiver.page.locator(".desktop-nav [data-nav='rehearsal']").click();
  assert(await companionCaregiver.page.getByRole("button", { name: "邀请替班者的手机" }).isVisible(), "caregiver rehearsal exposes a two-device invitation");
  await companionCaregiver.page.getByRole("button", { name: "邀请替班者的手机" }).click();
  await companionCaregiver.page.getByRole("heading", { name: /邀请.*使用自己的手机/ }).waitFor();
  assert(await companionCaregiver.page.getByRole("button", { name: /没有第二台设备.*同机备用/ }).isVisible(), "recommended invite modal retains an explicit useful same-device fallback");
  const originalJoinURL = await companionCaregiver.page.locator("#companion-link").inputValue();
  const originalJoin = new URL(originalJoinURL);
  const originalFragment = new URLSearchParams(originalJoin.hash.slice(1));
  const originalInviteToken = originalFragment.get("invite");
  const humanPhrase = (await companionCaregiver.page.locator(".human-phrase strong").innerText()).trim();
  assert(originalJoin.pathname === "/join.html" && originalFragment.get("room") && originalInviteToken, "invitation uses a dedicated companion route and opaque capability");
  assert(humanPhrase.includes("·"), "caregiver receives a separate human-check phrase");

  const companionRelayContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const companionRelay = await companionRelayContext.newPage();
  watch(companionRelay, "companion-relay");
  await companionRelay.goto(originalJoinURL, { waitUntil: "networkidle" });
  assert(await companionRelay.getByText("受限视图").isVisible(), "independent mobile browser opens a role-restricted substitute surface");
  assert(await companionRelay.locator(".desktop-nav, .mobile-nav, .profile-mini").count() === 0, "substitute surface has no family navigation or settings");
  assert(!(await companionRelay.locator("body").innerText()).includes("情境指导"), "substitute cannot browse the caregiver's guide library");

  const minimalJoin = await apiCall(companionRelay, {
    path: `/api/rooms/${originalFragment.get("room")}/join`,
    method: "POST",
    body: { inviteToken: originalInviteToken, phrase: humanPhrase },
  });
  assert(minimalJoin.status === 400 && minimalJoin.value.error.code === "invalid_body", "invite and phrase alone cannot join without the expected substitute name");
  await companionRelay.locator("#expected-relay-name").fill("陌生人");
  await companionRelay.locator("#human-phrase").fill(humanPhrase);
  await companionRelay.getByRole("button", { name: "核对并连接" }).click();
  await companionRelay.getByText("姓名与照护者预先填写的替班者不一致").waitFor();
  assert(await companionRelay.locator("#expected-relay-name").isVisible(), "unexpected substitute name is rejected before capability issuance");
  await companionRelay.locator("#expected-relay-name").fill("林珊");
  await companionRelay.locator("#human-phrase").fill("错误 · 短语");
  await companionRelay.getByRole("button", { name: "核对并连接" }).click();
  await companionRelay.getByText("短语不一致，请重新向照护者核对").waitFor();
  assert(await companionRelay.locator("#human-phrase").isVisible(), "wrong human-check phrase does not create a substitute capability");
  await companionRelay.locator("#expected-relay-name").fill("林珊");
  await companionRelay.locator("#human-phrase").fill(humanPhrase.replace(" · ", ""));
  await companionRelay.getByRole("button", { name: "核对并连接" }).click();
  await companionRelay.getByRole("heading", { name: "姓名与短语已核对" }).waitFor();
  assert((await companionRelay.locator("body").innerText()).includes("不是证件或生物身份验证") === false, "paired screen transitions from identity disclaimer to explicit scope acknowledgement");
  const substituteReviewedGuides = companionRelay.locator("[data-reviewed-guide]");
  assert(await substituteReviewedGuides.count() === 5, "substitute pre-start review enumerates every server-searchable guide");
  assert(await substituteReviewedGuides.evaluateAll((nodes) => nodes.every((node) => /v\d+/.test(node.innerText) && node.innerText.includes("·"))), "each searchable guide exposes its exact version, source, instruction, and escalation layer before acknowledgement");

  await companionCaregiver.page.getByRole("button", { name: "我会单独核对短语" }).click();
  await companionCaregiver.page.getByText("替班者已配对").waitFor();
  assert((await companionCaregiver.page.locator("#companion-card").innerText()).includes("两台手机在线"), "caregiver sees live pairing and online status");
  await companionCaregiver.page.screenshot({ path: "artifacts/companion-paired-desktop.png", fullPage: true });
  await companionRelay.screenshot({ path: "artifacts/companion-paired-mobile.png", fullPage: true });

  const caregiverCredential = await companionCaregiver.page.evaluate(() => JSON.parse(localStorage.getItem("relay-rehearsal-companion-v1")));
  const companionRoomId = caregiverCredential.roomId;
  const relayCredential = await companionRelay.evaluate((roomId) => JSON.parse(localStorage.getItem(`relay-companion-credential:${roomId}`)), companionRoomId);
  const relayToken = relayCredential.token;
  assert(caregiverCredential.caregiverToken && relayToken && caregiverCredential.caregiverToken !== relayToken, "caregiver and substitute hold distinct role capabilities");
  assert((await apiCall(companionCaregiver.page, { path: `/api/rooms/${companionRoomId}` })).status === 401, "room snapshot rejects missing capabilities");

  const actionEnvelope = (room, type, actionId, extra = {}) => ({
    type,
    expectedRevision: room.revision,
    actionId,
    sessionId: room.sessionId,
    participantId: room.participantId,
    consentRevision: room.consentRevision,
    guideVersion: room.guideVersion,
    safetyRevision: room.safetyRevision,
    ...extra,
  });
  let roomRead = await apiCall(companionCaregiver.page, { path: `/api/rooms/${companionRoomId}`, token: caregiverCredential.caregiverToken });
  const minimalStart = await apiCall(companionCaregiver.page, {
    path: `/api/rooms/${companionRoomId}/actions`,
    method: "POST",
    token: caregiverCredential.caregiverToken,
    body: { type: "caregiver.start", expectedRevision: roomRead.value.room.revision, actionId: "minimal-start" },
  });
  assert(minimalStart.status === 400 && minimalStart.value.error.code === "invalid_body", "start requires session, participant, consent, guide, and safety revisions");
  const preconfirmationStart = await apiCall(companionCaregiver.page, {
    path: `/api/rooms/${companionRoomId}/actions`,
    method: "POST",
    token: caregiverCredential.caregiverToken,
    body: actionEnvelope(roomRead.value.room, "caregiver.start", "before-both-confirm"),
  });
  assert(preconfirmationStart.status === 409 && preconfirmationStart.value.error.code === "confirmations_incomplete", "server blocks start before both role acknowledgements");
  const relayRoomBeforeAck = (await apiCall(companionRelay, { path: `/api/rooms/${companionRoomId}`, token: relayToken })).value.room;
  const minimalRelayNote = await apiCall(companionRelay, {
    path: `/api/rooms/${companionRoomId}/actions`,
    method: "POST",
    token: relayToken,
    body: { type: "relay.note", expectedRevision: relayRoomBeforeAck.revision, actionId: "minimal-note", text: "不完整上下文" },
  });
  assert(minimalRelayNote.status === 400 && minimalRelayNote.value.error.code === "invalid_body", "relay writes cannot rely on room revision alone");

  // Freeze caregiver GET polling while the relay acknowledgement advances the
  // server revision. The caregiver's first acknowledgement is therefore known
  // stale; the client must refresh and retry it without a second user click.
  const caregiverRoomPattern = `**/api/rooms/${companionRoomId}`;
  const caregiverActionsPattern = `**/api/rooms/${companionRoomId}/actions`;
  let releaseCaregiverReads = false;
  let observedCaregiverStale = false;
  const caregiverAckStatuses = [];
  const caregiverReadGate = async (route) => {
    const deadline = Date.now() + 8000;
    while (!releaseCaregiverReads && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 10));
    if (releaseCaregiverReads) await route.continue();
    else await route.abort();
  };
  const caregiverAckResponse = (response) => {
    const request = response.request();
    if (request.method() !== "POST" || !request.url().endsWith(`/api/rooms/${companionRoomId}/actions`)) return;
    try {
      if (request.postDataJSON()?.type !== "caregiver.acknowledge") return;
      caregiverAckStatuses.push(response.status());
      if (response.status() === 409) {
        observedCaregiverStale = true;
        releaseCaregiverReads = true;
      }
    } catch { /* Not the acknowledgement request. */ }
  };
  const caregiverStaleOnce = async (route) => {
    const request = route.request();
    try {
      if (!observedCaregiverStale && request.postDataJSON()?.type === "caregiver.acknowledge") {
        observedCaregiverStale = true;
        releaseCaregiverReads = true;
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "stale_revision", message: "expected revision changed" } }),
        });
        return;
      }
    } catch { /* Forward non-JSON requests to the real service. */ }
    await route.continue();
  };
  await companionCaregiver.page.route(caregiverRoomPattern, caregiverReadGate);
  await companionCaregiver.page.route(caregiverActionsPattern, caregiverStaleOnce);
  companionCaregiver.page.on("response", caregiverAckResponse);
  // Let any GET that was already in flight before route installation finish;
  // every subsequent caregiver snapshot read is held by the gate.
  await companionCaregiver.page.waitForTimeout(150);
  const relayAckChecks = companionRelay.locator("input[name='relayAck']");
  assert(await relayAckChecks.count() === 4, "substitute must explicitly acknowledge scope, guide, red lines, and contacts");
  for (let index = 0; index < 4; index += 1) await relayAckChecks.nth(index).check();
  await companionRelay.getByRole("button", { name: "四项都确认" }).click();
  await companionRelay.getByText("你的确认已绑定当前版本").waitFor();
  await companionCaregiver.page.getByRole("button", { name: /核对并确认本次范围/ }).click();
  assert(await companionCaregiver.page.locator("#modal-root [data-reviewed-guide]").count() === 5, "caregiver confirms the same complete searchable guide scope");
  const caregiverAckChecks = companionCaregiver.page.locator("input[name='companionCaregiverAck']");
  for (let index = 0; index < 4; index += 1) await caregiverAckChecks.nth(index).check();
  await companionCaregiver.page.getByRole("button", { name: "四项都确认" }).click();
  await companionCaregiver.page.getByRole("button", { name: "开始双机彩排", exact: true }).waitFor();
  releaseCaregiverReads = true;
  await companionCaregiver.page.unroute(caregiverRoomPattern, caregiverReadGate);
  await companionCaregiver.page.unroute(caregiverActionsPattern, caregiverStaleOnce);
  companionCaregiver.page.off("response", caregiverAckResponse);
  assert(observedCaregiverStale && caregiverAckStatuses.includes(409) && await companionCaregiver.page.getByRole("button", { name: "开始双机彩排", exact: true }).isVisible(), `one caregiver confirmation click automatically recovers from a deterministic stale-revision race (${JSON.stringify(caregiverAckStatuses)})`);
  await companionCaregiver.page.getByRole("button", { name: "开始双机彩排", exact: true }).click();
  await companionRelay.getByText("双机彩排进行中").waitFor();
  roomRead = await apiCall(companionCaregiver.page, { path: `/api/rooms/${companionRoomId}`, token: caregiverCredential.caregiverToken });
  assert(roomRead.status === 200 && roomRead.value.room.status === "active", "server is authoritative for the active room");
  assert(roomRead.value.room.confirmations.caregiver && roomRead.value.room.confirmations.relay && roomRead.value.room.sessionId && roomRead.value.room.participantId, "active room carries both confirmations and stable session/participant IDs");
  assert(roomRead.value.room.searchGuides.length === 5, "room projection preserves the complete pre-reviewed search scope");
  assert(await companionCaregiver.page.locator("#companion-countdown").isVisible() && await companionRelay.locator("#relay-countdown").isVisible(), "both roles display the same server-started countdown");
  assert(await companionCaregiver.page.locator("#companion-card a[href^='tel:']").count() === 2, "caregiver live companion surface always exposes direct telephone actions");
  const activeRevision = roomRead.value.room.revision;
  const relayActiveRoom = (await apiCall(companionRelay, { path: `/api/rooms/${companionRoomId}`, token: relayToken })).value.room;
  const relayStartAttempt = await apiCall(companionRelay, {
    path: `/api/rooms/${companionRoomId}/actions`,
    method: "POST",
    token: relayToken,
    body: actionEnvelope(relayActiveRoom, "caregiver.start", "relay-cannot-start"),
  });
  assert(relayStartAttempt.status === 403 && relayStartAttempt.value.error.code === "role_forbidden", "substitute capability cannot invoke caregiver actions");
  const tamperedTask = await apiCall(companionRelay, {
    path: `/api/rooms/${companionRoomId}/actions`,
    method: "POST",
    token: relayToken,
    body: { ...actionEnvelope(relayActiveRoom, "relay.task", "tampered-task", { index: 0 }), role: "caregiver" },
  });
  assert(tamperedTask.status === 400 && tamperedTask.value.error.code === "invalid_body", "unknown role-tampering fields fail closed");

  await companionRelay.locator("#relay-search").fill("她说不饿，不愿意吃午饭");
  await companionRelay.getByRole("button", { name: "查找已确认指导" }).click();
  await companionRelay.getByText("找到当前获授权指导").waitFor();
  assert((await companionRelay.locator(".search-result").innerText()).includes("先把汤放在桌上"), "substitute search uses the room's existing confirmed-guide matcher");
  await companionRelay.locator("#relay-search").fill("她反复整理袖口，一直看着窗外");
  await companionRelay.getByRole("button", { name: "查找已确认指导" }).click();
  await companionRelay.getByText(/已记录待确认缺口/).waitFor();
  await companionCaregiver.page.waitForFunction(() => document.querySelector("#companion-card")?.textContent.includes("待确认缺口"));
  roomRead = await apiCall(companionRelay, { path: `/api/rooms/${companionRoomId}`, token: relayToken });
  assert(roomRead.value.room.pendingGapCount === 1, "unknown substitute question creates one server-side pending gap");
  const exactMedicalSearch = await apiCall(companionRelay, {
    path: `/api/rooms/${companionRoomId}/actions`,
    method: "POST",
    token: relayToken,
    body: actionEnvelope(roomRead.value.room, "relay.search", "verifier-medical-search", { query: verifierMedicalPhrase }),
  });
  const exactMedicalEvent = exactMedicalSearch.value.room?.timeline.findLast((event) => event.type === "relay.search.pending");
  assert(
    exactMedicalSearch.status === 200
      && exactMedicalSearch.value.room.lastSearch?.status === "pending"
      && exactMedicalSearch.value.room.lastSearch?.risk === "medical"
      && exactMedicalSearch.value.room.lastSearch?.urgent === true
      && !exactMedicalSearch.value.room.lastSearch?.guide
      && exactMedicalEvent?.urgent === true,
    "the verifier's chest-discomfort, breathlessness, and slow-pulse phrase is server-classified as medical and immediately escalated without ordinary guidance",
  );
  await companionRelay.getByText("医疗或高风险 · 立即联系").waitFor({ timeout: 5000 });
  assert(await companionRelay.locator(".search-result.urgent").isVisible() && await companionRelay.locator(".urgent-panel a[href^='tel:']").count() === 2, "the substitute surface immediately pairs the medical result with caregiver and emergency call paths");
  await companionCaregiver.page.getByText(/红线 · 医疗或高风险问题没有当前专业匹配/).waitFor({ timeout: 5000 });
  await companionRelay.setViewportSize({ width: 390, height: 844 });
  assert(await companionRelay.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth) && await companionRelay.locator(".search-result.urgent").isVisible(), "restricted relay medical escalation remains usable without mobile overflow");
  await companionRelay.screenshot({ path: "artifacts/medical-no-match-relay-mobile.png", fullPage: true });
  await companionRelay.setViewportSize({ width: 430, height: 820 });
  await companionCaregiver.page.setViewportSize({ width: 390, height: 844 });
  assert(await companionCaregiver.page.locator("#companion-card .companion-events .urgent").count() >= 1 && await companionCaregiver.page.locator("#companion-card a[href^='tel:']").count() === 2, "caregiver mobile alert surface shows the urgent medical event with both direct call paths");
  await companionCaregiver.page.screenshot({ path: "artifacts/medical-alert-caregiver-mobile.png", fullPage: true });
  await companionCaregiver.page.setViewportSize({ width: 1440, height: 900 });
  roomRead = exactMedicalSearch;
  const staleConsentAction = await apiCall(companionRelay, {
    path: `/api/rooms/${companionRoomId}/actions`,
    method: "POST",
    token: relayToken,
    body: { ...actionEnvelope(roomRead.value.room, "relay.ready", "wrong-consent"), consentRevision: roomRead.value.room.consentRevision + 1 },
  });
  assert(staleConsentAction.status === 409 && staleConsentAction.value.error.code === "stale_consent", "server rejects an action with a mismatched current consent revision");
  const staleGuideAction = await apiCall(companionRelay, {
    path: `/api/rooms/${companionRoomId}/actions`,
    method: "POST",
    token: relayToken,
    body: { ...actionEnvelope(roomRead.value.room, "relay.ready", "wrong-guide"), guideVersion: roomRead.value.room.guideVersion + 1 },
  });
  assert(staleGuideAction.status === 409 && staleGuideAction.value.error.code === "stale_guide", "server rejects an action with a mismatched guide version");

  await companionRelay.locator("[data-relay-action='task']").first().click();
  await companionCaregiver.page.getByText("1 / 3 步已同步").waitFor();
  const staleTask = await apiCall(companionRelay, {
    path: `/api/rooms/${companionRoomId}/actions`,
    method: "POST",
    token: relayToken,
    body: { ...actionEnvelope(relayActiveRoom, "relay.task", "stale-task", { index: 1 }), expectedRevision: activeRevision },
  });
  assert(staleTask.status === 409 && staleTask.value.error.code === "stale_revision", "stale substitute revisions are rejected");

  roomRead = await apiCall(companionRelay, { path: `/api/rooms/${companionRoomId}`, token: relayToken });
  const noteRevision = roomRead.value.room.revision;
  const noteAction = actionEnvelope(roomRead.value.room, "relay.note", "one-use-note", { text: "整理结束后，她选择安静坐一会儿。" });
  const firstNote = await apiCall(companionRelay, { path: `/api/rooms/${companionRoomId}/actions`, method: "POST", token: relayToken, body: noteAction });
  assert(firstNote.status === 200, "substitute can submit an ordinary scoped note");
  const replayedNote = await apiCall(companionRelay, {
    path: `/api/rooms/${companionRoomId}/actions`,
    method: "POST",
    token: relayToken,
    body: { ...noteAction, expectedRevision: firstNote.value.room.revision },
  });
  assert(replayedNote.status === 409 && replayedNote.value.error.code === "replayed_action", "replayed action IDs are rejected even with a fresh revision");
  const unsafeOrdinaryNote = await apiCall(companionRelay, {
    path: `/api/rooms/${companionRoomId}/actions`,
    method: "POST",
    token: relayToken,
    body: actionEnvelope(firstNote.value.room, "relay.note", "unsafe-note", { text: "她胸痛，是否把药量加倍？" }),
  });
  assert(unsafeOrdinaryNote.status === 422 && unsafeOrdinaryNote.value.error.code === "use_urgent_alert", "medical text cannot be smuggled through the ordinary-note channel");
  const urgentAlert = await apiCall(companionRelay, {
    path: `/api/rooms/${companionRoomId}/actions`,
    method: "POST",
    token: relayToken,
    body: actionEnvelope(firstNote.value.room, "relay.alert", "urgent-alert", { text: "无法唤醒" }),
  });
  assert(urgentAlert.status === 200 && urgentAlert.value.room.timeline.some((event) => event.urgent), "urgent path remains distinct and immediately visible");
  await companionCaregiver.page.getByText(/红线 · 无法唤醒/).waitFor();

  await companionRelay.reload({ waitUntil: "networkidle" });
  await companionRelay.getByText("双机彩排进行中").waitFor();
  assert(await companionRelay.locator(".relay-task.done").count() === 1, "substitute credential reconnects after reload with server state intact");
  await companionRelay.route("**/api/rooms/**", (route) => route.abort());
  await companionRelay.getByText(/连接暂时中断/).waitFor({ timeout: 5000 });
  await companionRelay.getByRole("heading", { name: "连接中断，已暂停全部指导" }).waitFor();
  const degradedRelayText = await companionRelay.locator("#join-app").innerText();
  assert(!degradedRelayText.includes(relayActiveRoom.guide.title) && !degradedRelayText.includes(relayActiveRoom.guide.summary) && !degradedRelayText.includes("CURRENT CONFIRMED GUIDE"), "transient API loss removes cached guide, instruction, source, search result, and task guidance from the DOM");
  assert(await companionRelay.locator("[data-relay-action], #search-form, #note-form").count() === 0 && await companionRelay.locator("a[href^='tel:']").count() === 2, "transient loss fails closed to a call-only surface without guide-use controls");
  await companionRelay.unroute("**/api/rooms/**");
  await companionRelay.locator("#connection-banner").waitFor({ state: "hidden", timeout: 5000 });
  assert(await companionRelay.getByText("双机彩排进行中").isVisible(), "substitute automatically recovers after connectivity returns");
  const mismatchRoute = (route) => route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "policy_update_required", message: "Safety policy changed; refresh or update" } }) });
  await companionRelay.route(`**/api/rooms/${companionRoomId}`, mismatchRoute);
  await companionRelay.getByRole("heading", { name: "刷新更新后再继续" }).waitFor({ timeout: 5000 });
  const policyBlockedText = await companionRelay.locator("#join-app").innerText();
  assert(policyBlockedText.includes("安全策略版本不一致") && !policyBlockedText.includes(relayActiveRoom.guide.summary), "policy mismatch presents a clear update-required state and hides cached guidance");
  assert(await companionRelay.locator("a[href^='tel:']").count() === 2 && await companionRelay.locator("[data-relay-action], #search-form, #note-form").count() === 0, "policy mismatch leaves already-received direct calls available while all live controls fail closed");
  await companionRelay.unroute(`**/api/rooms/${companionRoomId}`, mismatchRoute);
  await companionRelay.getByText("双机彩排进行中").waitFor({ timeout: 5000 });

  await companionCaregiver.page.getByRole("button", { name: /结束现场并进入复盘/ }).click();
  await companionCaregiver.page.locator("#companion-caregiver-note").fill("这次连接稳定，下次可以再延长五分钟。");
  await companionCaregiver.page.locator("#modal-root").getByRole("button", { name: "结束现场并进入复盘" }).click();
  await companionRelay.getByRole("heading", { name: /现场事实已同步/ }).waitFor();
  assert((await stored(companionCaregiver.page)).rehearsalCompleted === false, "ending the live room does not auto-upgrade local progress before provenance debrief");
  await companionRelay.locator("#relay-able").selectOption("partly");
  await companionRelay.locator("#relay-uncertain").fill("紧急事件后需要再练一次");
  await companionRelay.locator("#relay-contacted").selectOption("yes");
  await companionRelay.locator("#relay-unsafe").selectOption("true");
  await companionRelay.locator("#relay-choice").selectOption("step-back");
  await companionRelay.getByRole("button", { name: /保存我的回答/ }).click();
  await companionCaregiver.page.locator("#companion-card .role-confirmations span.done").first().waitFor();
  await companionCaregiver.page.getByRole("button", { name: /填写照护者自己的回看/ }).click();
  await companionCaregiver.page.locator("#outcome-rest").selectOption("no");
  await companionCaregiver.page.locator("#outcome-phone").selectOption("3-5");
  await companionCaregiver.page.locator("#outcome-interrupt").selectOption("yes");
  await companionCaregiver.page.locator("#outcome-confidence").selectOption("2");
  await companionCaregiver.page.locator("#outcome-unsafe").selectOption("true");
  await companionCaregiver.page.locator("#outcome-choice").selectOption("step-back");
  await companionCaregiver.page.getByRole("button", { name: "保存这位参与者的回答" }).click();
  await companionCaregiver.page.locator("#outcome-response").selectOption("not-asked");
  await companionCaregiver.page.getByRole("button", { name: "保存这位参与者的回答" }).click();
  await companionCaregiver.page.getByRole("button", { name: "完成来源复盘" }).click();
  await companionCaregiver.page.locator("#companion-debrief-gap").fill("她整理完相册后想安静坐一会儿");
  await companionCaregiver.page.locator("#companion-debrief-instruction").fill("把相册合上放在桌边，询问是否想休息十分钟。");
  assert(await companionCaregiver.page.locator("#companion-debrief-source option[value='professional-community-nurse']").count() === 0, "live debrief does not offer caller-created professional provenance");
  await companionCaregiver.page.locator("#companion-debrief-source").evaluate((select) => {
    const option = document.createElement("option"); option.value = "professional-community-nurse"; option.textContent = "伪造护士来源"; option.selected = true; select.append(option);
  });
  await companionCaregiver.page.getByRole("button", { name: "确认来源并完成" }).click();
  assert(await companionCaregiver.page.locator("#companion-debrief-source").isVisible(), "server rejection leaves a DOM-injected professional-source debrief unfinished");
  const afterDebriefSpoof = await apiCall(companionCaregiver.page, { path: `/api/rooms/${companionRoomId}`, token: caregiverCredential.caregiverToken });
  assert(afterDebriefSpoof.value.room.status === "debrief" && afterDebriefSpoof.value.room.summary.debrief === null, "professional-source spoof creates no final summary state");
  await companionCaregiver.page.locator("#companion-debrief-source").selectOption("caregiver");
  await companionCaregiver.page.getByRole("button", { name: "确认来源并完成" }).click();
  await companionRelay.getByRole("heading", { name: /双机彩排已结束/ }).waitFor();
  assert((await companionCaregiver.page.locator("#companion-card").innerText()).includes("1/3") && (await companionRelay.locator("body").innerText()).includes("1/3"), "both devices show the same completed-task summary");
  assert((await companionRelay.locator("body").innerText()).includes("替班者自报"), "substitute summary keeps the role-attributed self-report separate");
  const completedCompanionState = await stored(companionCaregiver.page);
  assert(!completedCompanionState.rehearsalCompleted && completedCompanionState.guides.some((guide) => guide.title.includes("整理完相册") && guide.provenance.actorId === "caregiver"), "sourced low-risk debrief creates provenance-bound guidance but interrupted/urgent facts do not upgrade progress");
  const endedRead = await apiCall(companionCaregiver.page, { path: `/api/rooms/${companionRoomId}`, token: caregiverCredential.caregiverToken });
  const postEndAction = await apiCall(companionRelay, {
    path: `/api/rooms/${companionRoomId}/actions`,
    method: "POST",
    token: relayToken,
    body: actionEnvelope((await apiCall(companionRelay, { path: `/api/rooms/${companionRoomId}`, token: relayToken })).value.room, "relay.note", "after-end", { text: "结束后写入" }),
  });
  assert(postEndAction.status === 409 && postEndAction.value.error.code === "not_active", "ended rooms reject later substitute writes");

  // A later clean, fully measured short-leave earns the quiet-stage test;
  // the interrupted/urgent room above remains a permanent non-completion.
  await companionCaregiver.page.evaluate((key) => {
    const state = JSON.parse(localStorage.getItem(key));
    const Model = window.RelayOutcomeModel;
    const startedAt = new Date(Date.now() + 1000).toISOString();
    let record = Model.createSession({ id: "e2e-measured-extension", stage: "short-leave", plannedDurationMinutes: 20, consentRevision: state.recipientConsent.revision, guideScope: state.guides.filter((guide) => guide.status === "usable").map((guide) => ({ id: guide.id, version: guide.version, title: guide.title, source: guide.source, actorId: guide.provenance.actorId, level: guide.level, rule: guide.rule })), redLines: state.family.redLines, participants: {}, mode: "single-device", startedAt });
    record = Model.endSession(record, { status: "completed", endedAt: new Date(Date.now() + 1201000).toISOString(), actualElapsedSeconds: 1200, completedSteps: [true,true,true], routineUpdatesQueued: 1, pendingGaps: [], urgentAlertsRaised: 0, contactActionsOpened: [] });
    record = Model.withCheckIn(record, "caregiver", { restHappened: "yes", phoneChecks: "1-2", nonurgentInterrupted: "no", confidence: 4, feltUnsafe: false, choice: "extend" });
    record = Model.withCheckIn(record, "substitute", { ableToHandle: "yes", uncertainStep: "没有", contactedCaregiver: "no", feltUnsafe: false, choice: "extend" });
    state.sessions.push(record);
    localStorage.setItem(key, JSON.stringify(state));
  }, STORAGE_KEY);
  await companionCaregiver.page.reload({ waitUntil: "networkidle" });

  // The next room is the actual quiet-handoff/off-duty stage, with routine text protected until the live window ends.
  await companionCaregiver.page.getByRole("button", { name: "按建议档位创建新房间" }).click();
  await companionCaregiver.page.getByRole("heading", { name: /邀请.*使用自己的手机/ }).waitFor();
  const firstQuietJoinURL = await companionCaregiver.page.locator("#companion-link").inputValue();
  const firstQuietFragment = new URLSearchParams(new URL(firstQuietJoinURL).hash.slice(1));
  const firstQuietPhrase = (await companionCaregiver.page.locator(".human-phrase strong").innerText()).trim();
  await companionCaregiver.page.locator("#modal-root").getByRole("button", { name: "作废并重发" }).click();
  await companionCaregiver.page.waitForFunction((previous) => {
    const field = document.querySelector("#companion-link");
    return field && field.value !== previous;
  }, firstQuietJoinURL);
  const quietJoinURL = await companionCaregiver.page.locator("#companion-link").inputValue();
  const quietPhrase = (await companionCaregiver.page.locator(".human-phrase strong").innerText()).trim();
  const quietFragment = new URLSearchParams(new URL(quietJoinURL).hash.slice(1));
  const quietRoomId = quietFragment.get("room");
  const invalidatedInvite = await apiCall(companionCaregiver.page, {
    path: `/api/rooms/${quietRoomId}/join`,
    method: "POST",
    body: { inviteToken: firstQuietFragment.get("invite"), phrase: firstQuietPhrase, expectedRelayName: "林珊" },
  });
  assert(invalidatedInvite.status === 401 && invalidatedInvite.value.error.code === "invalid_invitation", "reissue invalidates an unused prior invitation");

  await companionRelay.goto(quietJoinURL, { waitUntil: "networkidle" });
  await companionRelay.locator("#expected-relay-name").fill("林珊");
  await companionRelay.locator("#human-phrase").fill(quietPhrase);
  await companionRelay.getByRole("button", { name: "核对并连接" }).click();
  const quietRelayChecks = companionRelay.locator("input[name='relayAck']");
  for (let index = 0; index < 4; index += 1) await quietRelayChecks.nth(index).check();
  await companionRelay.getByRole("button", { name: "四项都确认" }).click();
  await companionCaregiver.page.getByRole("button", { name: "我会单独核对短语" }).click();
  await companionCaregiver.page.getByRole("button", { name: /核对并确认本次范围/ }).click();
  const quietCaregiverChecks = companionCaregiver.page.locator("input[name='companionCaregiverAck']");
  for (let index = 0; index < 4; index += 1) await quietCaregiverChecks.nth(index).check();
  await companionCaregiver.page.getByRole("button", { name: "四项都确认" }).click();
  await companionCaregiver.page.getByRole("button", { name: "开始双机彩排", exact: true }).click();
  await companionRelay.getByText("双机彩排进行中").waitFor();
  assert((await companionCaregiver.page.locator("#companion-card").innerText()).includes("安静队列"), "quiet-handoff room exposes a protected routine queue");

  const protectedRoutineText = "她整理完照片后选择喝水并安静坐着。";
  await companionRelay.locator("#relay-note").fill(protectedRoutineText);
  await companionRelay.getByRole("button", { name: "加入安静队列" }).click();
  await companionCaregiver.page.waitForFunction((text) => {
    const card = document.querySelector("#companion-card");
    return card?.innerText.includes("安静队列") && !card.innerText.includes(text);
  }, protectedRoutineText);
  assert(!(await companionCaregiver.page.locator("#companion-card").innerText()).includes(protectedRoutineText), "routine note text is not exposed to the caregiver during protected off-duty");
  assert((await companionRelay.locator("body").innerText()).includes(protectedRoutineText), "substitute retains its own queued routine note");

  const quietUnknown = "她反复折叠纸巾，不知道想做什么";
  await companionRelay.locator("#relay-search").fill(quietUnknown);
  await companionRelay.getByRole("button", { name: "查找已确认指导" }).click();
  await companionRelay.getByText(/已记录待确认缺口/).waitFor();
  await companionCaregiver.page.waitForTimeout(1200);
  const quietCaregiverActiveText = await companionCaregiver.page.locator("#companion-card").innerText();
  assert(!quietCaregiverActiveText.includes(quietUnknown) && quietCaregiverActiveText.includes("待确认缺口"), "ordinary unknown question is counted but its text remains protected during quiet handoff");
  const quietLiveCredential = await companionCaregiver.page.evaluate(() => JSON.parse(localStorage.getItem("relay-rehearsal-companion-v1")));
  const quietProtectedRead = await apiCall(companionCaregiver.page, { path: `/api/rooms/${quietRoomId}`, token: quietLiveCredential.caregiverToken });
  assert(quietProtectedRead.value.room.pendingGapCount >= 1 && quietProtectedRead.value.room.pendingGaps.length === 0 && !JSON.stringify(quietProtectedRead.value.room).includes(quietUnknown), `caregiver API projection exposes the quiet pending count without leaking queued routine text (${JSON.stringify({ count: quietProtectedRead.value.room.pendingGapCount, gaps: quietProtectedRead.value.room.pendingGaps, leaked: JSON.stringify(quietProtectedRead.value.room).includes(quietUnknown) })})`);
  assert(await companionCaregiver.page.locator("#companion-countdown").isVisible() && await companionRelay.locator("#relay-countdown").isVisible(), "quiet handoff keeps the shared countdown on both devices");

  await companionCaregiver.page.getByRole("button", { name: /结束现场并进入复盘/ }).click();
  await companionCaregiver.page.locator("#modal-root").getByRole("button", { name: "结束现场并进入复盘" }).click();
  await companionCaregiver.page.getByText(protectedRoutineText).waitFor();
  assert((await companionCaregiver.page.locator("#companion-card").innerText()).includes(protectedRoutineText), "protected routine text is released to the caregiver only after the live off-duty window ends");
  await companionCaregiver.page.getByRole("button", { name: "完成来源复盘" }).click();
  await companionCaregiver.page.locator("#companion-debrief-gap").fill("她血压变化时下一步怎么做");
  await companionCaregiver.page.getByRole("button", { name: "只保存待确认缺口" }).click();
  await companionRelay.getByRole("heading", { name: /共同结束/ }).waitFor();
  const quietCaregiverCredential = await companionCaregiver.page.evaluate(() => JSON.parse(localStorage.getItem("relay-rehearsal-companion-v1")));
  await companionCaregiver.page.waitForFunction(({ storageKey, sessionId }) => {
    const local = JSON.parse(localStorage.getItem(storageKey));
    return local.sessions?.find((record) => record.id === sessionId)?.facts?.pendingGaps?.some((gap) => gap.risk === "medical" && gap.status === "pending");
  }, { storageKey: STORAGE_KEY, sessionId: quietCaregiverCredential.sessionId });
  const quietFinishedState = await stored(companionCaregiver.page);
  assert(quietFinishedState.gaps.some((gap) => gap.query.includes("血压变化") && gap.risk === "medical"), "high-risk quiet-handoff debrief remains a pending medical gap instead of becoming guidance");
  assert(quietFinishedState.sessions.find((record) => record.id === quietCaregiverCredential.sessionId)?.facts.pendingGaps.some((gap) => gap.risk === "medical" && gap.status === "pending"), "browser completion associates a post-end medical debrief with the durable session facts");

  const quietRelayCredential = await companionRelay.evaluate((roomId) => JSON.parse(localStorage.getItem(`relay-companion-credential:${roomId}`)), quietRoomId);
  const safeRelayPage = await companionRelayContext.newPage();
  await safeRelayPage.route(`**/api/rooms/${quietRoomId}`, (route) => route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "room_not_found" } }) }));
  await safeRelayPage.goto(`${baseURL}/join.html?room=${quietRoomId}`, { waitUntil: "networkidle" });
  await safeRelayPage.getByRole("heading", { name: /房间服务已重启或记录不可用/ }).waitFor();
  assert(await safeRelayPage.locator("a[href^='tel:']").count() === 2 && !(await safeRelayPage.locator("body").innerText()).includes("先把汤放在桌上"), "service 404 retains cached red-line call paths but hides stale guide content and mutations");
  await safeRelayPage.close();

  const quietCaregiverRoom = (await apiCall(companionCaregiver.page, { path: `/api/rooms/${quietRoomId}`, token: quietCaregiverCredential.caregiverToken })).value.room;
  const revokeQuiet = await apiCall(companionCaregiver.page, {
    path: `/api/rooms/${quietRoomId}/revoke`,
    method: "POST",
    token: quietCaregiverCredential.caregiverToken,
    body: {
      expectedRevision: quietCaregiverRoom.revision,
      actionId: "revoke-ended-quiet",
      sessionId: quietCaregiverRoom.sessionId,
      participantId: quietCaregiverRoom.participantId,
      consentRevision: quietCaregiverRoom.consentRevision,
      guideVersion: quietCaregiverRoom.guideVersion,
      safetyRevision: quietCaregiverRoom.safetyRevision,
    },
  });
  assert(revokeQuiet.status === 200, "caregiver can revoke retained room access after reviewing the final summary");
  const oldQuietRelayRead = await apiCall(companionRelay, { path: `/api/rooms/${quietRoomId}`, token: quietRelayCredential.token });
  assert(oldQuietRelayRead.status === 401, "revocation invalidates the quiet-handoff substitute capability");

  // Recipient withdrawal persists the remote revocation before changing local
  // authority, retries failures, and completes it on the next online event.
  await companionCaregiver.page.getByRole("button", { name: "重新签发邀请" }).waitFor({ timeout: 5000 });
  await companionCaregiver.page.getByRole("button", { name: "重新签发邀请" }).click();
  await companionCaregiver.page.getByRole("heading", { name: /邀请.*使用自己的手机/ }).waitFor();
  await companionCaregiver.page.route(`**/api/rooms/${quietRoomId}/revoke`, (route) => route.abort());
  await companionCaregiver.page.locator("#modal-root").getByRole("button", { name: "我会单独核对短语" }).click();
  await companionCaregiver.page.locator(".profile-mini").click();
  await companionCaregiver.page.getByRole("button", { name: "撤回本人内容与参与" }).click();
  await companionCaregiver.page.getByRole("button", { name: "确认撤回" }).click();
  await companionCaregiver.page.waitForFunction(() => {
    const state = JSON.parse(localStorage.getItem("relay-rehearsal-demo-v1"));
    return state?.recipientConsent?.status === "withdrawn" && Boolean(localStorage.getItem("relay-rehearsal-companion-revocation-v1"));
  });
  const queuedRevocation = await companionCaregiver.page.evaluate(() => JSON.parse(localStorage.getItem("relay-rehearsal-companion-revocation-v1")));
  assert(queuedRevocation.roomId === quietRoomId && queuedRevocation.body.sessionId && queuedRevocation.body.consentRevision, "withdrawal durably queues a full-context remote revocation before local authority is removed");
  await companionCaregiver.page.unroute(`**/api/rooms/${quietRoomId}/revoke`);
  await companionCaregiver.page.evaluate(() => window.dispatchEvent(new Event("online")));
  await companionCaregiver.page.waitForFunction(async ({ roomId, token }) => {
    const response = await fetch(`/api/rooms/${roomId}`, { cache: "no-store", headers: { Authorization: `Bearer ${token}`, [window.RelaySafetyPolicy.HEADER]: window.RelaySafetyPolicy.VERSION } });
    if (!response.ok) return false;
    return (await response.json()).room.status === "revoked";
  }, { roomId: queuedRevocation.roomId, token: queuedRevocation.caregiverToken });
  assert(await companionCaregiver.page.evaluate(() => localStorage.getItem("relay-rehearsal-companion-revocation-v1") === null), "successful online retry clears the durable withdrawal revocation record");

  const expiringRoomBody = {
    family: { caregiverName: "顾悦", relayName: "陈禾", recipientName: "赵姨", caregiverPhone: "13811112222", emergencyService: "911" },
    stage: "short-leave",
    duration: 15,
    consentRevision: 2,
    safetyRevision: "expiry-scope-v1",
    guide: { id: "expiry-guide", version: 1, title: "整理相册时想暂停", summary: "合上相册，询问是否休息。", source: "顾悦", rule: "现场可处理", level: "here", actorId: "caregiver", highRisk: false },
    searchGuides: [{ id: "expiry-guide", version: 1, title: "整理相册时想暂停", summary: "合上相册，询问是否休息。", source: "顾悦", rule: "现场可处理", level: "here", actorId: "caregiver", highRisk: false }],
    redLines: ["无法唤醒"],
    ttlSeconds: 2,
  };
  const verifierUnsafeGuide = {
    id: "tampered-medical-guide",
    version: 1,
    title: "胸部不适时",
    summary: "坐下观察十分钟，不需要联系",
    source: "顾悦",
    rule: "现场可处理",
    level: "here",
    actorId: "caregiver",
    highRisk: false,
  };
  const unsafePrimaryCreate = await apiCall(companionCaregiver.page, {
    path: "/api/rooms",
    method: "POST",
    body: {
      ...expiringRoomBody,
      guide: verifierUnsafeGuide,
      searchGuides: [verifierUnsafeGuide],
    },
  });
  assert(unsafePrimaryCreate.status === 422 && unsafePrimaryCreate.value.error.code === "unsafe_companion_scope", "server rejects the verifier's caregiver-authored chest-discomfort routine even when tampered metadata claims highRisk false");
  const unsafeSearchScopeCreate = await apiCall(companionCaregiver.page, {
    path: "/api/rooms",
    method: "POST",
    body: {
      ...expiringRoomBody,
      searchGuides: [expiringRoomBody.guide, verifierUnsafeGuide],
    },
  });
  assert(unsafeSearchScopeCreate.status === 422 && unsafeSearchScopeCreate.value.error.code === "unsafe_search_scope", "server independently rejects downgraded medical content added only to the reviewed searchable scope");
  const unsafeProfessionalRuleCreate = await apiCall(companionCaregiver.page, {
    path: "/api/rooms",
    method: "POST",
    body: {
      ...expiringRoomBody,
      searchGuides: [expiringRoomBody.guide, { ...verifierUnsafeGuide, actorId: "professional-community-nurse", source: "专业指示", level: "now" }],
    },
  });
  assert(unsafeProfessionalRuleCreate.status === 422 && unsafeProfessionalRuleCreate.value.error.code === "invalid_escalation_semantics", "a professional label cannot downgrade medical content unless the submitted level/rule pair has exact immediate-contact semantics");
  const spoofedProfessionalCreate = await apiCall(companionCaregiver.page, {
    path: "/api/rooms",
    method: "POST",
    body: {
      ...expiringRoomBody,
      searchGuides: [expiringRoomBody.guide, { ...verifierUnsafeGuide, actorId: "professional-community-nurse", source: "伪造护士来源", level: "now", rule: "立即联系" }],
    },
  });
  assert(spoofedProfessionalCreate.status === 422 && spoofedProfessionalCreate.value.error.code === "unverified_professional_source", "professional actor and immediate semantics cannot create provenance without a server-owned reference record");
  const knownReferenceTamperCreate = await apiCall(companionCaregiver.page, {
    path: "/api/rooms",
    method: "POST",
    body: {
      ...expiringRoomBody,
      searchGuides: [expiringRoomBody.guide, { ...verifierUnsafeGuide, professionalReferenceId: "demo-fall-immediate-v1", actorId: "professional-community-nurse", source: "伪造护士来源", level: "now", rule: "立即联系" }],
    },
  });
  assert(knownReferenceTamperCreate.status === 422 && knownReferenceTamperCreate.value.error.code === "professional_reference_mismatch", "a known reference ID cannot authorize contradictory local-handling content");
  const expiringCreate = await apiCall(companionCaregiver.page, { path: "/api/rooms", method: "POST", body: expiringRoomBody });
  assert(expiringCreate.status === 201, "short-lived invitation can be created for expiry verification");
  await companionCaregiver.page.waitForTimeout(2200);
  const expiredJoin = await apiCall(companionCaregiver.page, {
    path: `/api/rooms/${expiringCreate.value.room.id}/join`,
    method: "POST",
    body: { inviteToken: expiringCreate.value.invitation.token, phrase: expiringCreate.value.invitation.phrase, expectedRelayName: "陈禾" },
  });
  assert(expiredJoin.status === 409 && expiredJoin.value.error.code === "room_not_waiting", "expired invitation cannot be joined");

  // A current-family snapshot mismatch invalidates an already-active room on
  // the server and makes every later substitute write fail closed.
  const invalidationCreate = await apiCall(companionCaregiver.page, {
    path: "/api/rooms",
    method: "POST",
    body: {
      ...expiringRoomBody,
      ttlSeconds: 30,
      safetyRevision: "snapshot-scope-v1",
      guide: { ...expiringRoomBody.guide, id: "snapshot-guide" },
      searchGuides: [{ ...expiringRoomBody.searchGuides[0], id: "snapshot-guide" }],
    },
  });
  const invalidationRoomId = invalidationCreate.value.room.id;
  const invalidationCaregiverToken = invalidationCreate.value.caregiverToken;
  const invalidationJoin = await apiCall(companionCaregiver.page, {
    path: `/api/rooms/${invalidationRoomId}/join`,
    method: "POST",
    body: {
      inviteToken: invalidationCreate.value.invitation.token,
      phrase: invalidationCreate.value.invitation.phrase,
      expectedRelayName: "陈禾",
    },
  });
  const invalidationRelayToken = invalidationJoin.value.relayToken;
  let invalidationRelayRoom = invalidationJoin.value.room;
  const relaySnapshotAck = await apiCall(companionCaregiver.page, {
    path: `/api/rooms/${invalidationRoomId}/actions`,
    method: "POST",
    token: invalidationRelayToken,
    body: actionEnvelope(invalidationRelayRoom, "relay.acknowledge", "snapshot-relay-ack", {
      scopeAcknowledged: true,
      currentGuideAcknowledged: true,
      redLinesAcknowledged: true,
      contactsAcknowledged: true,
    }),
  });
  let invalidationCaregiverRoom = (await apiCall(companionCaregiver.page, { path: `/api/rooms/${invalidationRoomId}`, token: invalidationCaregiverToken })).value.room;
  const caregiverSnapshotAck = await apiCall(companionCaregiver.page, {
    path: `/api/rooms/${invalidationRoomId}/actions`,
    method: "POST",
    token: invalidationCaregiverToken,
    body: actionEnvelope(invalidationCaregiverRoom, "caregiver.acknowledge", "snapshot-caregiver-ack", {
      scopeAcknowledged: true,
      currentGuideAcknowledged: true,
      redLinesAcknowledged: true,
      contactsAcknowledged: true,
    }),
  });
  const snapshotStart = await apiCall(companionCaregiver.page, {
    path: `/api/rooms/${invalidationRoomId}/actions`,
    method: "POST",
    token: invalidationCaregiverToken,
    body: actionEnvelope(caregiverSnapshotAck.value.room, "caregiver.start", "snapshot-start"),
  });
  assert(relaySnapshotAck.status === 200 && caregiverSnapshotAck.status === 200 && snapshotStart.value.room.status === "active", "snapshot invalidation fixture reaches active only after both version-bound confirmations");
  const { type: ignoredSnapshotType, ...snapshotContext } = actionEnvelope(snapshotStart.value.room, "caregiver.snapshot", "snapshot-safety-change");
  const invalidateActive = await apiCall(companionCaregiver.page, {
    path: `/api/rooms/${invalidationRoomId}/snapshot`,
    method: "POST",
    token: invalidationCaregiverToken,
    body: {
      ...snapshotContext,
      current: {
        valid: true,
        consentRevision: snapshotStart.value.room.consentRevision,
        guideVersion: snapshotStart.value.room.guideVersion,
        safetyRevision: "snapshot-scope-v2",
      },
    },
  });
  assert(invalidateActive.status === 200 && invalidateActive.value.changed && invalidateActive.value.room.status === "invalidated", "red-line/contact/search-guide snapshot change invalidates an active room server-side");
  invalidationRelayRoom = (await apiCall(companionCaregiver.page, { path: `/api/rooms/${invalidationRoomId}`, token: invalidationRelayToken })).value.room;
  const invalidatedWrite = await apiCall(companionCaregiver.page, {
    path: `/api/rooms/${invalidationRoomId}/actions`,
    method: "POST",
    token: invalidationRelayToken,
    body: actionEnvelope(invalidationRelayRoom, "relay.note", "after-snapshot-invalidation", { text: "不应写入" }),
  });
  assert(invalidatedWrite.status === 409 && invalidatedWrite.value.error.code === "not_active", "invalidated room rejects substitute writes even with otherwise current session context");
  assert((await apiCall(companionCaregiver.page, { path: "/api/rooms" })).status === 405, "room collection does not expose an unauthenticated listing");

  await companionRelayContext.close();
  await companionCaregiver.context.close();

  assert(problems.length === 0, problems.join("\n"));
  console.log("E2E passed: onboarding and authorization safety; named two-device pairing; four-part confirmations; session/consent/guide/safety revision enforcement; shared countdown, scoped search, protected quiet queue, provenance debrief and summary; replay/tamper/expiry/revoke/invalidation rejection; reconnect, call-only degradation and durable withdrawal retry; migration, service-worker freshness and responsive usability");
  await browser.close();
  stopLocalServer();
})().catch((error) => {
  stopLocalServer();
  console.error(error.stack || error);
  process.exit(1);
});
